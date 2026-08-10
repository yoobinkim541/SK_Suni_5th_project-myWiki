from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from .classifier import classify_document, get_openrouter_settings
from .concurrency import run_concurrently
from .exceptions import (
    ClassificationLoadFailedError,
    ClassificationSaveFailedError,
    DocumentVersionNotFoundError,
    DocumentWorkspaceMismatchError,
    InvalidCategoryError,
    InvalidJsonResponseError,
    MarkdownNotFoundError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from .models import (
    DEFAULT_CLASSIFICATION_PROMPT_VERSION,
    StoredClassificationResult,
)
from .repository import (
    get_classification_result,
    get_supabase,
    save_classification_failure,
    save_classification_result,
    validate_document_workspace,
)
from ..pipeline_common.storage import download as download_object

logger = logging.getLogger(__name__)


@dataclass
class EvidenceRef:
    document_version_id: str
    quoted_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    relevance_score: Optional[float] = None


@dataclass
class SectionDraft:
    category: str
    title: str
    content: Optional[str]
    confidence_score: Optional[float]
    evidences: list[EvidenceRef]
    status: str


class DocumentRef(BaseModel):
    document_version_id: str
    document_id: str
    title: str
    canonical_url: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    source_type: str | None = None
    source_reliability_score: float | None = None
    published_at: str | None = None
    markdown_object_key: str
    version_no: int | None = None



def get_document_refs(*, workspace_id: str, document_version_ids: list[str]) -> list[DocumentRef]:
    if not document_version_ids:
        return []

    db = get_supabase()
    version_rows = (
        db.table("document_versions")
        .select("id, document_id, markdown_object_key, version_no")
        .in_("id", document_version_ids)
        .execute()
        .data
    )
    versions_by_id = {row["id"]: row for row in version_rows}

    document_ids = list({row["document_id"] for row in version_rows})
    document_rows = []
    if document_ids:
        document_rows = (
            db.table("documents")
            .select("id, workspace_id, title, canonical_url, published_at, source_id")
            .eq("workspace_id", workspace_id)
            .in_("id", document_ids)
            .execute()
            .data
        )
    documents_by_id = {row["id"]: row for row in document_rows}

    source_ids = list({row["source_id"] for row in document_rows if row.get("source_id")})
    source_rows = []
    if source_ids:
        source_rows = (
            db.table("sources")
            .select("id, name, source_type, reliability_score")
            .in_("id", source_ids)
            .execute()
            .data
        )
    sources_by_id = {row["id"]: row for row in source_rows}

    refs: list[DocumentRef] = []
    for document_version_id in document_version_ids:
        version = versions_by_id.get(document_version_id)
        if version is None:
            continue

        document = documents_by_id.get(version["document_id"])
        if document is None:
            continue

        source = sources_by_id.get(document.get("source_id")) if document.get("source_id") else None
        refs.append(
            DocumentRef(
                document_version_id=document_version_id,
                document_id=document["id"],
                title=document["title"],
                canonical_url=document.get("canonical_url"),
                source_id=document.get("source_id"),
                source_name=source.get("name") if source else None,
                source_type=source.get("source_type") if source else None,
                source_reliability_score=_coerce_float(source.get("reliability_score") if source else None),
                published_at=_normalize_datetime_string(document.get("published_at")),
                markdown_object_key=version["markdown_object_key"],
                version_no=version.get("version_no"),
            )
        )

    return refs



def get_markdown(*, workspace_id: str, document_version_id: str) -> str:
    refs = get_document_refs(workspace_id=workspace_id, document_version_ids=[document_version_id])
    if not refs:
        raise DocumentVersionNotFoundError("DOCUMENT_VERSION_NOT_FOUND")

    # object_key는 버킷 접두사를 포함한다(예: "processed/ws/doc/1.md").
    # pipeline_common.storage.download()가 접두사를 분리해 올바른 버킷에서 내려받는다.
    object_key = refs[0].markdown_object_key
    markdown_bytes = download_object(object_key)
    markdown = markdown_bytes.decode("utf-8").strip()
    if not markdown:
        raise MarkdownNotFoundError("MARKDOWN_NOT_FOUND")
    return markdown



def classify_document_version(
    *,
    workspace_id: str,
    document_version_id: str,
    force: bool = False,
) -> StoredClassificationResult:
    settings = get_openrouter_settings()
    model_name = settings.model
    prompt_version = DEFAULT_CLASSIFICATION_PROMPT_VERSION

    try:
        validate_document_workspace(workspace_id=workspace_id, document_version_id=document_version_id)
        existing = get_classification_result(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            model_name=model_name,
            prompt_version=prompt_version,
        )
        if existing is not None and existing.status == "completed" and not force:
            return existing

        ref = get_document_refs(workspace_id=workspace_id, document_version_ids=[document_version_id])
        title = ref[0].title if ref else ""
        markdown = get_markdown(workspace_id=workspace_id, document_version_id=document_version_id)
        classification = classify_document(
            title=title,
            markdown=markdown,
            source_name=ref[0].source_name if ref else None,
            published_at=ref[0].published_at if ref else None,
        )
        return save_classification_result(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            result=classification,
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
        logger.warning("classification failed: %s OPENROUTER_TIMEOUT", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_TIMEOUT", str(exc))
    except OpenRouterApiError as exc:
        logger.warning("classification failed: %s OPENROUTER_API_ERROR", document_version_id)
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "OPENROUTER_API_ERROR", str(exc))
    except InvalidJsonResponseError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "INVALID_JSON_RESPONSE", str(exc))
    except InvalidCategoryError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "VALIDATION_ERROR", str(exc))
    except (ClassificationLoadFailedError, ClassificationSaveFailedError) as exc:
        code = "CLASSIFICATION_LOAD_FAILED" if isinstance(exc, ClassificationLoadFailedError) else "CLASSIFICATION_SAVE_FAILED"
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, code, str(exc))
    except ValueError as exc:
        return _persisted_failure_result(document_version_id, workspace_id, model_name, prompt_version, "VALIDATION_ERROR", str(exc))
    except Exception as exc:
        logger.exception("classification failed: %s UNEXPECTED_ERROR", document_version_id)
        return _runtime_failure_result(document_version_id, workspace_id, model_name, prompt_version, "UNEXPECTED_ERROR", str(exc))



def classify_document_versions(
    *,
    workspace_id: str,
    document_version_ids: list[str],
    force: bool = False,
) -> list[StoredClassificationResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: classify_document_version(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )



def classify_documents(
    *,
    workspace_id: str,
    document_version_ids: list[str],
    force: bool = False,
) -> list[StoredClassificationResult]:
    return classify_document_versions(
        workspace_id=workspace_id,
        document_version_ids=document_version_ids,
        force=force,
    )



def evaluate_reliability_for_documents(*, workspace_id: str, document_version_ids: list[str], force: bool = False):
    from .reliability import evaluate_reliability_for_documents as _evaluate_reliability_for_documents

    return _evaluate_reliability_for_documents(
        workspace_id=workspace_id,
        document_version_ids=document_version_ids,
        force=force,
    )



def analyze(document_version_ids: list[str]) -> list[SectionDraft]:
    raise NotImplementedError("Use classify_documents(workspace_id=..., document_version_ids=...) instead.")



def _runtime_failure_result(
    document_version_id: str,
    workspace_id: str,
    model_name: str,
    prompt_version: str,
    error_code: str,
    error_message: str,
) -> StoredClassificationResult:
    now = datetime.now(timezone.utc).isoformat()
    return StoredClassificationResult(
        id=f"runtime-{document_version_id}",
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        primary_category=None,
        secondary_categories=[],
        classification_confidence=None,
        classification_reason=None,
        status="failed",
        error_message=error_message,
        error_code=error_code,
        model_name=model_name,
        prompt_version=prompt_version,
        classified_at=now,
        created_at=now,
        updated_at=now,
    )



def _persisted_failure_result(
    document_version_id: str,
    workspace_id: str,
    model_name: str,
    prompt_version: str,
    error_code: str,
    error_message: str,
) -> StoredClassificationResult:
    stored = save_classification_failure(
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        model_name=model_name,
        prompt_version=prompt_version,
        error_message=error_message,
        error_code=error_code,
    )
    stored.error_code = error_code
    return stored



def _normalize_datetime_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)



def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
