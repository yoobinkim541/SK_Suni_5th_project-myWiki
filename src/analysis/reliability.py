from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from .classifier import create_json_completion, get_openrouter_settings, parse_json_response
from .concurrency import run_concurrently
from .exceptions import (
    ClassificationLoadFailedError,
    ClassificationSaveFailedError,
    DocumentVersionNotFoundError,
    DocumentWorkspaceMismatchError,
    InsufficientEvidenceError,
    InvalidJsonResponseError,
    InvalidScoreError,
    MarkdownNotFoundError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from .interface import get_document_refs, get_markdown
from .models import DEFAULT_CLASSIFICATION_PROMPT_VERSION
from .reliability_models import (
    DEFAULT_RELIABILITY_PROMPT_VERSION,
    EvidenceDocument,
    MachineSignals,
    ReliabilityEvaluationRequest,
    ReliabilityEvaluationResult,
    ReliabilityLLMResult,
    StoredReliabilityResult,
)
from .reliability_prompts import RELIABILITY_SYSTEM_PROMPT, build_reliability_user_prompt
from .reliability_scoring import apply_machine_score_caps, build_final_result
from .repository import (
    get_latest_classification_result,
    get_reliability_result,
    save_reliability_failure,
    save_reliability_result,
    validate_document_workspace,
)

logger = logging.getLogger(__name__)


def evaluate_reliability(request: ReliabilityEvaluationRequest) -> ReliabilityEvaluationResult:
    settings = get_openrouter_settings()
    if not settings.api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")

    if not request.documents:
        raise InsufficientEvidenceError("신뢰도 평가를 위한 근거 문서가 없습니다.")

    machine_signals = build_machine_signals(request.documents)
    response_text = create_json_completion(
        system_prompt=RELIABILITY_SYSTEM_PROMPT,
        user_prompt=build_reliability_user_prompt(request),
        model=settings.model,
    )

    llm_result = parse_reliability_response(response_text)
    machine_signals.conflicting_claims_present = bool(llm_result.conflicting_claims)
    machine_signals.official_correction_detected = _detect_official_correction(llm_result)

    breakdown, caps = apply_machine_score_caps(llm_result=llm_result, signals=machine_signals)
    return build_final_result(
        issue_id=request.issue_id,
        issue_title=request.issue_title,
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        evaluated_document_version_ids=[document.document_version_id for document in request.documents],
        additional_warnings=machine_signals.warnings,
    )


def evaluate_and_save_reliability(*, workspace_id: str, document_version_id: str, force: bool = False) -> StoredReliabilityResult:
    settings = get_openrouter_settings()
    model_name = settings.model
    prompt_version = DEFAULT_RELIABILITY_PROMPT_VERSION

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

        existing = get_reliability_result(workspace_id=workspace_id, document_version_id=document_version_id)
        if (
            existing is not None
            and existing.reliability_status == "completed"
            and existing.reliability_model_name == model_name
            and existing.reliability_prompt_version == prompt_version
            and not force
        ):
            return existing

        docs = build_evidence_documents(workspace_id=workspace_id, document_version_ids=[document_version_id])
        request = ReliabilityEvaluationRequest(
            workspace_id=workspace_id,
            issue_id=document_version_id,
            issue_title=docs[0].title,
            category=classification.primary_category.value,
            documents=docs,
        )
        result = evaluate_reliability(request)
        return save_reliability_result(
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
        logger.warning("reliability failed: %s OPENROUTER_TIMEOUT", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_TIMEOUT", str(exc), keep_existing_completed=force)
    except OpenRouterApiError as exc:
        logger.warning("reliability failed: %s OPENROUTER_API_ERROR", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_API_ERROR", str(exc), keep_existing_completed=force)
    except InvalidJsonResponseError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_JSON_RESPONSE", str(exc), keep_existing_completed=force)
    except InvalidScoreError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_RELIABILITY_SCORE", str(exc), keep_existing_completed=force)
    except ClassificationLoadFailedError as exc:
        error_code = str(exc)
        if error_code in {"ANALYSIS_RESULT_NOT_FOUND", "CLASSIFICATION_NOT_COMPLETED"}:
            return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, error_code, error_code)
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "RELIABILITY_LOAD_FAILED", str(exc))
    except ClassificationSaveFailedError as exc:
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "RELIABILITY_SAVE_FAILED", str(exc))
    except (ValidationError, ValueError) as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_RELIABILITY_SCORE", str(exc), keep_existing_completed=force)
    except Exception as exc:
        logger.exception("reliability failed: %s UNEXPECTED_ERROR", document_version_id)
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "UNEXPECTED_ERROR", str(exc))


def evaluate_and_save_reliabilities(*, workspace_id: str, document_version_ids: list[str], force: bool = False) -> list[StoredReliabilityResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: evaluate_and_save_reliability(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )


def evaluate_reliability_for_documents(*, workspace_id: str, document_version_ids: list[str], force: bool = False) -> list[StoredReliabilityResult]:
    return evaluate_and_save_reliabilities(
        workspace_id=workspace_id,
        document_version_ids=document_version_ids,
        force=force,
    )


def build_evidence_documents(*, workspace_id: str, document_version_ids: list[str]) -> list[EvidenceDocument]:
    refs = get_document_refs(workspace_id=workspace_id, document_version_ids=document_version_ids)
    refs_by_id = {ref.document_version_id: ref for ref in refs}

    documents: list[EvidenceDocument] = []
    for document_version_id in document_version_ids:
        ref = refs_by_id.get(document_version_id)
        if ref is None:
            raise DocumentVersionNotFoundError("DOCUMENT_VERSION_NOT_FOUND")
        markdown = get_markdown(workspace_id=workspace_id, document_version_id=document_version_id)
        documents.append(_build_evidence_document(ref, markdown))
    return documents


def build_machine_signals(documents: list[EvidenceDocument]) -> MachineSignals:
    has_any_url = any(bool((document.canonical_url or "").strip()) for document in documents)
    has_any_markdown = any(bool(document.markdown.strip()) for document in documents)
    missing_markdown_documents = [document.document_version_id for document in documents if not document.markdown.strip()]
    missing_url_documents = [document.document_version_id for document in documents if not (document.canonical_url or "").strip()]
    missing_metadata_documents = [
        document.document_version_id
        for document in documents
        if not all([
            document.title.strip(),
            document.source_name.strip(),
            bool(document.published_at),
            bool(document.document_version_id),
            bool(document.markdown_object_key),
        ])
    ]
    source_ids = {document.source_id for document in documents if document.source_id}
    canonical_urls = {document.canonical_url for document in documents if document.canonical_url}
    has_official_source = any(_is_official_source(document.source_type) for document in documents)
    duplicated_republish_detected = _detect_duplicate_republish(documents)

    warnings: list[str] = []
    if len(documents) == 1:
        warnings.append("단일 출처 기반 평가")

    return MachineSignals(
        has_any_url=has_any_url,
        has_any_markdown=has_any_markdown,
        has_complete_metadata=not missing_metadata_documents,
        document_count=len(documents),
        unique_source_count=len(source_ids) if source_ids else len({document.source_name for document in documents if document.source_name}),
        unique_canonical_url_count=len(canonical_urls),
        has_official_source=has_official_source,
        single_source_only=(len(source_ids) <= 1 and len({document.source_name for document in documents}) <= 1),
        duplicated_republish_detected=duplicated_republish_detected,
        missing_markdown_documents=missing_markdown_documents,
        missing_url_documents=missing_url_documents,
        missing_metadata_documents=missing_metadata_documents,
        warnings=warnings,
    )


def parse_reliability_response(raw_content: str) -> ReliabilityLLMResult:
    payload = parse_json_response(raw_content)
    return ReliabilityLLMResult.model_validate(payload)


def _build_evidence_document(ref, markdown: str) -> EvidenceDocument:
    return EvidenceDocument(
        document_version_id=ref.document_version_id,
        document_id=ref.document_id,
        title=ref.title,
        canonical_url=ref.canonical_url,
        source_name=ref.source_name or "출처 미상",
        source_type=ref.source_type,
        source_reliability_score=ref.source_reliability_score,
        published_at=ref.published_at,
        markdown=markdown,
        version_no=ref.version_no,
        source_id=ref.source_id,
        markdown_object_key=ref.markdown_object_key,
    )


def _detect_duplicate_republish(documents: list[EvidenceDocument]) -> bool:
    if len(documents) <= 1:
        return False
    canonical_urls = [document.canonical_url for document in documents if document.canonical_url]
    if canonical_urls and len(set(canonical_urls)) == 1:
        return True
    normalized_titles = [_normalize_text(document.title) for document in documents]
    if len(set(normalized_titles)) == 1 and len(documents) > 1:
        return True
    normalized_prefixes = {_normalize_text(document.markdown[:400]) for document in documents if document.markdown.strip()}
    return len(normalized_prefixes) == 1 and len(documents) > 1


def _is_official_source(source_type: str | None) -> bool:
    if not source_type:
        return False
    normalized = source_type.lower()
    return any(token in normalized for token in ["official", "government", "regulator", "filing", "press", "research", "conference", "disclosure"])


_CORRECTION_KEYWORDS = ("정정", "철회", "반박", "취소")
_NEGATED_CORRECTION_TERMS = (
    "없",
    "않",
    "아니",
    "미확인",
    "불가",
    "부재",
    "미제공",
    "미상",
    "확인되지",
    "확인할 수 없",
    "발견되지",
    "파악되지",
)
_UNCERTAIN_CORRECTION_TERMS = ("여부", "가능성", "필요", "검토", "주의", "여지")


def _detect_official_correction(llm_result: ReliabilityLLMResult) -> bool:
    text = " ".join(
        llm_result.current_validity.warnings
        + llm_result.conflicting_claims
        + llm_result.missing_information
        + [llm_result.current_validity.reason]
    )
    for clause in _correction_clauses(text):
        if not any(keyword in clause for keyword in _CORRECTION_KEYWORDS):
            continue
        if _is_negated_or_uncertain_correction_context(clause):
            continue
        return True
    return False


def _correction_clauses(text: str) -> list[str]:
    return [clause.strip() for clause in re.split(r"[\n\r.;!?]|[\u3002\uff01\uff1f]", text) if clause.strip()]


def _is_negated_or_uncertain_correction_context(clause: str) -> bool:
    normalized = " ".join(clause.split())
    if any(term in normalized for term in _NEGATED_CORRECTION_TERMS):
        return True
    return any(term in normalized for term in _UNCERTAIN_CORRECTION_TERMS)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _runtime_failure_result(document_version_id: str, workspace_id: str, model_name: str, prompt_version: str, error_code: str, error_message: str) -> StoredReliabilityResult:
    now = datetime.now(timezone.utc).isoformat()
    return StoredReliabilityResult(
        id=f"runtime-{document_version_id}",
        analysis_result_id=None,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        status="failed",
        model_name=model_name,
        prompt_version=DEFAULT_CLASSIFICATION_PROMPT_VERSION,
        classified_at=now,
        created_at=now,
        updated_at=now,
        reliability_status="failed",
        reliability_model_name=model_name,
        reliability_prompt_version=prompt_version,
        reliability_error_message=error_message,
        error_code=error_code,
    )


def _persisted_failure_result(document_version_id: str, workspace_id: str, model_name: str, prompt_version: str, error_code: str, error_message: str, keep_existing_completed: bool = False) -> StoredReliabilityResult:
    if keep_existing_completed:
        existing = get_reliability_result(workspace_id=workspace_id, document_version_id=document_version_id)
        if existing is not None and existing.reliability_status == "completed":
            return existing
    return save_reliability_failure(
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        model_name=model_name,
        prompt_version=prompt_version,
        error_code=error_code,
        error_message=error_message,
    )
