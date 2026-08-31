from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from .classifier import create_json_completion, get_openrouter_settings, parse_json_response
from .concurrency import run_concurrently
from .exceptions import (
    ClassificationLoadFailedError,
    ClassificationSaveFailedError,
    DocumentNotFoundError,
    DocumentVersionNotFoundError,
    DocumentWorkspaceMismatchError,
    InvalidCategoryError,
    InvalidJsonResponseError,
    InvalidScoreError,
    MarkdownNotFoundError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from .importance_models import (
    DEFAULT_IMPORTANCE_PROMPT_VERSION,
    ImportanceDocument,
    ImportanceEvaluationFailure,
    ImportanceEvaluationRequest,
    ImportanceEvaluationResult,
    ImportanceLLMResult,
    ImportanceMachineSignals,
    StoredImportanceResult,
)
from .importance_prompts import IMPORTANCE_SYSTEM_PROMPT, build_importance_user_prompt
from .importance_scoring import apply_importance_caps, build_importance_final_result, validate_importance_enums
from .interface import get_document_refs, get_markdown
from .reliability import _detect_duplicate_republish
from .repository import (
    get_importance_result,
    get_latest_classification_result,
    get_reliability_result,
    save_importance_failure,
    save_importance_result,
    validate_document_workspace,
)

logger = logging.getLogger(__name__)
CURRENT_DATE = datetime(2026, 8, 2)


class ImportanceSummaryValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def evaluate_importance(request: ImportanceEvaluationRequest) -> ImportanceEvaluationResult:
    settings = get_openrouter_settings()
    if not settings.api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")

    machine_signals = build_importance_machine_signals(request)
    response_text = create_json_completion(
        system_prompt=IMPORTANCE_SYSTEM_PROMPT,
        user_prompt=build_importance_user_prompt(request),
        model=settings.model,
        max_tokens=4096,
    )
    llm_result = parse_importance_response(
        response_text,
        allowed_document_version_ids=[document.document_version_id for document in request.documents],
    )
    validate_importance_enums(llm_result)

    breakdown, caps = apply_importance_caps(llm_result=llm_result, signals=machine_signals)
    return build_importance_final_result(
        issue_id=request.issue_id,
        issue_title=request.issue_title,
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        signals=machine_signals,
        evaluated_document_version_ids=[document.document_version_id for document in request.documents],
        additional_warnings=machine_signals.warnings,
    )


def evaluate_importance_for_documents(*, workspace_id: str, document_version_ids: list[str], issue_id: str | None = None, issue_title: str | None = None, primary_category: str, secondary_categories: list[str] | None = None, reliability_score: int | None = None, reliability_level: str | None = None, independent_source_count: int | None = None, first_seen_at: str | None = None, last_seen_at: str | None = None,) -> ImportanceEvaluationResult | ImportanceEvaluationFailure:
    try:
        documents = build_importance_documents(workspace_id=workspace_id, document_version_ids=document_version_ids)

        if reliability_score is None or reliability_level is None:
            stored_reliability = get_reliability_result(
                workspace_id=workspace_id,
                document_version_id=document_version_ids[0],
            )
            if (
                stored_reliability is None
                or stored_reliability.reliability_status != "completed"
                or stored_reliability.reliability_score is None
                or stored_reliability.reliability_level is None
            ):
                return _build_failure(issue_id, issue_title or "", document_version_ids, "RELIABILITY_NOT_COMPLETED", "RELIABILITY_NOT_COMPLETED")
            reliability_score = stored_reliability.reliability_score
            reliability_level = stored_reliability.reliability_level.value

        request = ImportanceEvaluationRequest(
            workspace_id=workspace_id,
            issue_id=issue_id,
            issue_title=issue_title or documents[0].title,
            primary_category=primary_category,
            secondary_categories=secondary_categories or [],
            documents=documents,
            reliability_score=reliability_score,
            reliability_level=reliability_level,
            independent_source_count=independent_source_count or _count_independent_sources(documents),
            first_seen_at=first_seen_at or _min_published_at(documents),
            last_seen_at=last_seen_at or _max_published_at(documents),
        )
        return evaluate_importance(request)
    except MissingApiKeyError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, "MISSING_API_KEY", str(exc))
    except DocumentNotFoundError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, "DOCUMENT_NOT_FOUND", str(exc))
    except MarkdownNotFoundError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, "MARKDOWN_NOT_FOUND", str(exc))
    except OpenRouterTimeoutError as exc:
        logger.warning("importance failed: %s OPENROUTER_TIMEOUT", ",".join(document_version_ids))
        return _build_failure(issue_id, issue_title or "", document_version_ids, "OPENROUTER_TIMEOUT", str(exc))
    except OpenRouterApiError as exc:
        logger.warning("importance failed: %s OPENROUTER_API_ERROR", ",".join(document_version_ids))
        return _build_failure(issue_id, issue_title or "", document_version_ids, "OPENROUTER_API_ERROR", str(exc))
    except InvalidJsonResponseError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, "INVALID_JSON_RESPONSE", str(exc))
    except InvalidScoreError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, "INVALID_SCORE", str(exc))
    except InvalidCategoryError as exc:
        code = "INVALID_IMPACT_DIRECTION" if "impact_direction" in str(exc) else "INVALID_TIME_HORIZON"
        return _build_failure(issue_id, issue_title or "", document_version_ids, code, str(exc))
    except ImportanceSummaryValidationError as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, exc.code, str(exc))
    except (ValidationError, ValueError) as exc:
        return _build_failure(issue_id, issue_title or "", document_version_ids, _map_importance_validation_error(exc), str(exc))


def evaluate_and_save_importance(*, workspace_id: str, document_version_id: str, force: bool = False) -> StoredImportanceResult:
    settings = get_openrouter_settings()
    model_name = settings.model
    prompt_version = DEFAULT_IMPORTANCE_PROMPT_VERSION

    try:
        validate_document_workspace(workspace_id=workspace_id, document_version_id=document_version_id)
        classification = get_latest_classification_result(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
        )
        if classification is None:
            return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "ANALYSIS_RESULT_NOT_FOUND", "ANALYSIS_RESULT_NOT_FOUND")
        if classification.status != "completed" or classification.primary_category is None:
            return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "CLASSIFICATION_NOT_COMPLETED", "CLASSIFICATION_NOT_COMPLETED")

        reliability = get_reliability_result(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
        )
        if (
            reliability is None
            or reliability.reliability_status != "completed"
            or reliability.reliability_score is None
            or reliability.reliability_level is None
        ):
            return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "RELIABILITY_NOT_COMPLETED", "RELIABILITY_NOT_COMPLETED")

        existing = get_importance_result(workspace_id=workspace_id, document_version_id=document_version_id)
        if (
            existing is not None
            and existing.importance_status == "completed"
            and existing.importance_model_name == model_name
            and existing.importance_prompt_version == prompt_version
            and not force
        ):
            return existing

        documents = build_importance_documents(workspace_id=workspace_id, document_version_ids=[document_version_id])
        request = ImportanceEvaluationRequest(
            workspace_id=workspace_id,
            issue_id=document_version_id,
            issue_title=documents[0].title,
            primary_category=classification.primary_category.value,
            secondary_categories=[category.value for category in classification.secondary_categories],
            documents=documents,
            reliability_score=reliability.reliability_score,
            reliability_level=reliability.reliability_level,
            independent_source_count=_count_independent_sources(documents),
            first_seen_at=_min_published_at(documents),
            last_seen_at=_max_published_at(documents),
        )
        result = evaluate_importance(request)
        return save_importance_result(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            result=result,
            model_name=model_name,
            prompt_version=prompt_version,
        )
    except MissingApiKeyError as exc:
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "MISSING_API_KEY", str(exc))
    except DocumentVersionNotFoundError as exc:
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "DOCUMENT_VERSION_NOT_FOUND", str(exc))
    except DocumentWorkspaceMismatchError as exc:
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "DOCUMENT_WORKSPACE_MISMATCH", str(exc))
    except MarkdownNotFoundError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "MARKDOWN_NOT_FOUND", str(exc))
    except OpenRouterTimeoutError as exc:
        logger.warning("importance failed: %s OPENROUTER_TIMEOUT", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_TIMEOUT", str(exc), keep_existing_completed=force)
    except OpenRouterApiError as exc:
        logger.warning("importance failed: %s OPENROUTER_API_ERROR", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_API_ERROR", str(exc), keep_existing_completed=force)
    except InvalidJsonResponseError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_JSON_RESPONSE", str(exc), keep_existing_completed=force)
    except InvalidScoreError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_SCORE", str(exc), keep_existing_completed=force)
    except InvalidCategoryError as exc:
        code = "INVALID_IMPACT_DIRECTION" if "impact_direction" in str(exc) else "INVALID_TIME_HORIZON"
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, code, str(exc), keep_existing_completed=force)
    except ImportanceSummaryValidationError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, exc.code, str(exc), keep_existing_completed=force)
    except ClassificationLoadFailedError as exc:
        error_code = str(exc)
        if error_code in {"ANALYSIS_RESULT_NOT_FOUND", "CLASSIFICATION_NOT_COMPLETED", "RELIABILITY_NOT_COMPLETED"}:
            return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, error_code, error_code)
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "IMPORTANCE_LOAD_FAILED", str(exc))
    except ClassificationSaveFailedError as exc:
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "IMPORTANCE_SAVE_FAILED", str(exc))
    except (ValidationError, ValueError) as exc:
        return _persisted_failure_result(
            document_version_id,
            workspace_id,
            model_name,
            prompt_version,
            _map_importance_validation_error(exc),
            str(exc),
            keep_existing_completed=force,
        )
    except Exception as exc:
        logger.exception("importance failed: %s UNEXPECTED_ERROR", document_version_id)
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "UNEXPECTED_ERROR", str(exc))


def evaluate_and_save_importances(*, workspace_id: str, document_version_ids: list[str], force: bool = False) -> list[StoredImportanceResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: evaluate_and_save_importance(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )


def build_importance_documents(*, workspace_id: str, document_version_ids: list[str]) -> list[ImportanceDocument]:
    refs = get_document_refs(workspace_id=workspace_id, document_version_ids=document_version_ids)
    refs_by_id = {ref.document_version_id: ref for ref in refs}
    documents: list[ImportanceDocument] = []
    for document_version_id in document_version_ids:
        ref = refs_by_id.get(document_version_id)
        if ref is None:
            raise DocumentNotFoundError(f"document_version_id={document_version_id}")
        markdown = get_markdown(workspace_id=workspace_id, document_version_id=document_version_id)
        documents.append(ImportanceDocument(document_version_id=ref.document_version_id, title=ref.title, source_name=ref.source_name or "출처 미상", source_type=ref.source_type, canonical_url=ref.canonical_url, published_at=ref.published_at, markdown=markdown, source_id=ref.source_id))
    return documents


def build_importance_machine_signals(request: ImportanceEvaluationRequest) -> ImportanceMachineSignals:
    documents = request.documents
    unique_source_count = _count_independent_sources(documents)
    unique_canonical_url_count = len({doc.canonical_url for doc in documents if doc.canonical_url})
    duplicated_republish_detected = _detect_duplicate_republish([type("Tmp", (), {"canonical_url": d.canonical_url, "title": d.title, "markdown": d.markdown})() for d in documents])
    sk_hynix_explicitly_mentioned = any(_mentions_sk_hynix(doc.title, doc.markdown) for doc in documents)
    core_business_mentioned = any(_mentions_core_business(doc.title, doc.markdown) for doc in documents)
    quantitative_impact_present = any(any(ch.isdigit() for ch in doc.markdown) for doc in documents)
    forecast_only = all(_is_forecast_like(doc.markdown) for doc in documents)
    promotional_or_event_only = all(_is_promotional_or_event(doc.title, doc.markdown) for doc in documents)
    event_already_ended = _is_already_ended(request.last_seen_at or _max_published_at(documents))

    warnings: list[str] = []
    if len(documents) == 1:
        warnings.append("단일 출처 기반 평가")
    if request.reliability_level is not None and request.reliability_level.value == "낮음":
        warnings.append("신뢰도가 낮아 추가 검증 필요")

    return ImportanceMachineSignals(document_count=len(documents), unique_source_count=unique_source_count, unique_canonical_url_count=unique_canonical_url_count, independent_source_count=max(request.independent_source_count, 1), has_official_source=any(_is_official_source(doc.source_type) for doc in documents), duplicated_republish_detected=duplicated_republish_detected, sk_hynix_explicitly_mentioned=sk_hynix_explicitly_mentioned, core_business_mentioned=core_business_mentioned, quantitative_impact_present=quantitative_impact_present, forecast_only=forecast_only, promotional_or_event_only=promotional_or_event_only, event_already_ended=event_already_ended, warnings=warnings)


def parse_importance_response(raw_content: str, allowed_document_version_ids: list[str] | None = None) -> ImportanceLLMResult:
    payload = parse_json_response(raw_content)
    sanitized_payload = _sanitize_importance_payload(payload, set(allowed_document_version_ids or []))
    try:
        return ImportanceLLMResult.model_validate(sanitized_payload)
    except ValidationError as exc:
        raise ImportanceSummaryValidationError(_map_importance_validation_error(exc), str(exc)) from exc


def _sanitize_importance_payload(payload: object, allowed_document_version_ids: set[str]) -> dict:
    if not isinstance(payload, dict):
        raise ImportanceSummaryValidationError("INVALID_JSON_RESPONSE", "중요도 응답은 JSON 객체여야 합니다.")

    sanitized = dict(payload)
    sanitized["core_summary"] = _normalize_required_text(sanitized.get("core_summary"), "INVALID_CORE_SUMMARY", "core_summary")
    sanitized["sk_hynix_implication"] = _normalize_required_text(sanitized.get("sk_hynix_implication"), "INVALID_SK_HYNIX_IMPLICATION", "sk_hynix_implication")
    sanitized["key_points"] = _sanitize_key_points(sanitized.get("key_points"))
    sanitized["key_numbers"] = _sanitize_key_numbers(sanitized.get("key_numbers"), allowed_document_version_ids)
    sanitized["summary_evidence_refs"] = _sanitize_summary_evidence_refs(
        sanitized.get("summary_evidence_refs"),
        allowed_document_version_ids,
        key_points_count=len(sanitized["key_points"]),
        key_numbers_count=len(sanitized["key_numbers"]),
    )
    return sanitized


def _sanitize_key_points(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ImportanceSummaryValidationError("INVALID_KEY_POINTS", "key_points는 리스트여야 합니다.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
        if len(normalized) >= 5:
            break
    if len(normalized) < 3:
        raise ImportanceSummaryValidationError("INVALID_KEY_POINTS", "key_points는 3개 이상 5개 이하로 제공되어야 합니다.")
    return normalized


def _sanitize_key_numbers(value: object, allowed_document_version_ids: set[str]) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportanceSummaryValidationError("INVALID_KEY_NUMBERS", "key_numbers는 리스트여야 합니다.")
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value[:8]:
        if not isinstance(item, dict):
            raise ImportanceSummaryValidationError("INVALID_KEY_NUMBERS", "key_numbers 항목은 객체여야 합니다.")
        label = _normalize_required_text(item.get("label"), "INVALID_KEY_NUMBERS", "key_numbers.label")
        context = _normalize_required_text(item.get("context"), "INVALID_KEY_NUMBERS", "key_numbers.context")
        doc_id = _normalize_required_text(item.get("evidence_document_version_id"), "INVALID_KEY_NUMBERS", "key_numbers.evidence_document_version_id")
        if allowed_document_version_ids and doc_id not in allowed_document_version_ids:
            raise ImportanceSummaryValidationError("INVALID_KEY_NUMBERS", "key_numbers evidence_document_version_id가 입력 기사 범위를 벗어났습니다.")
        value_text = _normalize_required_text(item.get("value"), "INVALID_KEY_NUMBERS", "key_numbers.value")
        information_type = _normalize_required_text(item.get("information_type"), "INVALID_KEY_NUMBERS", "key_numbers.information_type").lower()
        if information_type not in {"fact", "plan", "forecast", "estimate"}:
            raise ImportanceSummaryValidationError("INVALID_KEY_NUMBERS", "허용되지 않은 key_numbers information_type입니다.")
        quoted_text = str(item.get("quoted_text", "")).strip() or None
        dedupe_key = (label, value_text, doc_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "label": label,
                "value": value_text,
                "unit": str(item.get("unit", "")).strip() or None,
                "context": context,
                "information_type": information_type,
                "evidence_document_version_id": doc_id,
                "quoted_text": quoted_text,
                "source_start_line": item.get("source_start_line"),
                "source_end_line": item.get("source_end_line"),
            }
        )
    return normalized


def _sanitize_summary_evidence_refs(value: object, allowed_document_version_ids: set[str], *, key_points_count: int, key_numbers_count: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs는 리스트여야 합니다.")
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for item in value[:8]:
        if not isinstance(item, dict):
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs 항목은 객체여야 합니다.")
        doc_id = _normalize_required_text(item.get("document_version_id"), "INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs.document_version_id")
        if allowed_document_version_ids and doc_id not in allowed_document_version_ids:
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs document_version_id가 입력 기사 범위를 벗어났습니다.")
        quoted_text = _normalize_required_text(item.get("quoted_text"), "INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs.quoted_text")
        if len(quoted_text) > 500:
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs quoted_text는 500자를 초과할 수 없습니다.")
        raw_supports = item.get("supports")
        if not isinstance(raw_supports, list):
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs supports는 리스트여야 합니다.")
        supports: list[str] = []
        seen_supports: set[str] = set()
        for support in raw_supports:
            token = str(support).strip()
            if not token or token in seen_supports:
                continue
            if token in {"core_summary", "sk_hynix_implication"}:
                supports.append(token)
                seen_supports.add(token)
                continue
            if token.startswith("key_points[") and token.endswith("]"):
                index = _parse_index(token, "key_points")
                if index >= key_points_count:
                    raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs key_points 참조 인덱스가 범위를 벗어났습니다.")
                supports.append(token)
                seen_supports.add(token)
                continue
            if token.startswith("key_numbers[") and token.endswith("]"):
                index = _parse_index(token, "key_numbers")
                if index >= key_numbers_count:
                    raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs key_numbers 참조 인덱스가 범위를 벗어났습니다.")
                supports.append(token)
                seen_supports.add(token)
                continue
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "허용되지 않은 summary_evidence_refs supports 값입니다.")
        if not supports:
            raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs supports는 최소 1개 이상이어야 합니다.")
        dedupe_key = (doc_id, quoted_text, tuple(supports))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "document_version_id": doc_id,
                "quoted_text": quoted_text,
                "source_start_line": item.get("source_start_line"),
                "source_end_line": item.get("source_end_line"),
                "supports": supports,
            }
        )
    if not normalized:
        raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", "summary_evidence_refs는 최소 1개 이상이어야 합니다.")
    return normalized


def _parse_index(token: str, prefix: str) -> int:
    try:
        return int(token[len(prefix) + 1 : -1])
    except ValueError as exc:
        raise ImportanceSummaryValidationError("INVALID_SUMMARY_EVIDENCE", f"{prefix} 참조 인덱스가 잘못되었습니다.") from exc


def _normalize_required_text(value: object, code: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ImportanceSummaryValidationError(code, f"{field_name}는 비어 있을 수 없습니다.")
    return " ".join(text.split())


def _map_importance_validation_error(exc: Exception) -> str:
    if isinstance(exc, ImportanceSummaryValidationError):
        return exc.code
    if isinstance(exc, ValidationError):
        locations = [".".join(str(part) for part in error.get("loc", [])) for error in exc.errors()]
        if any(location.startswith("core_summary") for location in locations):
            return "INVALID_CORE_SUMMARY"
        if any(location.startswith("key_points") for location in locations):
            return "INVALID_KEY_POINTS"
        if any(location.startswith("key_numbers") for location in locations):
            return "INVALID_KEY_NUMBERS"
        if any(location.startswith("summary_evidence_refs") for location in locations):
            return "INVALID_SUMMARY_EVIDENCE"
        if any(location.startswith("sk_hynix_implication") for location in locations):
            return "INVALID_SK_HYNIX_IMPLICATION"
    return "VALIDATION_ERROR"


def _count_independent_sources(documents: list[ImportanceDocument]) -> int:
    source_ids = {doc.source_id for doc in documents if doc.source_id}
    if source_ids:
        return len(source_ids)
    return len({doc.source_name for doc in documents if doc.source_name})


def _min_published_at(documents: list[ImportanceDocument]) -> str | None:
    values = [doc.published_at for doc in documents if doc.published_at]
    return min(values) if values else None


def _max_published_at(documents: list[ImportanceDocument]) -> str | None:
    values = [doc.published_at for doc in documents if doc.published_at]
    return max(values) if values else None


def _mentions_sk_hynix(title: str, markdown: str) -> bool:
    text = f"{title} {markdown}".lower()
    return any(token in text for token in ["sk하이닉스", "sk hynix", "하이닉스"])


def _mentions_core_business(title: str, markdown: str) -> bool:
    text = f"{title} {markdown}".lower()
    return any(token in text for token in ["hbm", "dram", "nand", "ddr", "lpddr", "메모리", "ai 메모리"])


def _is_forecast_like(markdown: str) -> bool:
    text = markdown.lower()
    forecast_tokens = ["전망", "예상", "검토", "계획", "가능성", "예정"]
    execution_tokens = ["확정", "시행", "완료", "양산", "출시", "계약", "발표"]
    return any(token in text for token in forecast_tokens) and not any(token in text for token in execution_tokens)


def _is_promotional_or_event(title: str, markdown: str) -> bool:
    text = f"{title} {markdown}".lower()
    event_tokens = ["행사", "전시", "참가", "부스", "컨퍼런스", "세미나", "홍보"]
    hard_business_tokens = ["투자", "계약", "생산", "양산", "매출", "가격", "수율", "규제"]
    return any(token in text for token in event_tokens) and not any(token in text for token in hard_business_tokens)


def _is_already_ended(last_seen_at: str | None) -> bool:
    if not last_seen_at:
        return False
    try:
        normalized = last_seen_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return (CURRENT_DATE.date() - dt.date()).days > 180


def _is_official_source(source_type: str | None) -> bool:
    if not source_type:
        return False
    normalized = source_type.lower()
    return any(token in normalized for token in ["official", "government", "regulator", "filing", "press", "research", "conference"])


def _build_failure(issue_id: str | None, issue_title: str, document_version_ids: list[str], error_code: str, error_message: str) -> ImportanceEvaluationFailure:
    return ImportanceEvaluationFailure(issue_id=issue_id, issue_title=issue_title, error_code=error_code, error_message=error_message, evaluated_document_version_ids=document_version_ids)


def _runtime_failure_result(document_version_id: str, workspace_id: str, model_name: str, prompt_version: str, error_code: str, error_message: str) -> StoredImportanceResult:
    from datetime import timezone

    now = datetime.now(timezone.utc).isoformat()
    return StoredImportanceResult(
        id=f"runtime-{document_version_id}",
        analysis_result_id=None,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        status="failed",
        model_name=model_name,
        prompt_version="classification-v1",
        classified_at=now,
        created_at=now,
        updated_at=now,
        reliability_status="pending",
        importance_status="failed",
        importance_model_name=model_name,
        importance_prompt_version=prompt_version,
        importance_error_message=error_message,
        error_code=error_code,
    )


def _persisted_failure_result(document_version_id: str, workspace_id: str, model_name: str, prompt_version: str, error_code: str, error_message: str, keep_existing_completed: bool = False) -> StoredImportanceResult:
    if keep_existing_completed:
        existing = get_importance_result(workspace_id=workspace_id, document_version_id=document_version_id)
        if existing is not None and existing.importance_status == "completed":
            return existing
    return save_importance_failure(
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        model_name=model_name,
        prompt_version=prompt_version,
        error_code=error_code,
        error_message=error_message,
    )


