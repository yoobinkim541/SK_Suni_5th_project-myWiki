from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from .exceptions import (
    ClassificationLoadFailedError,
    ClassificationSaveFailedError,
    DocumentVersionNotFoundError,
    DocumentWorkspaceMismatchError,
    RankingLoadFailedError,
    RankingSaveFailedError,
)
from .importance_models import (
    AnalysisResultForReport,
    DEFAULT_IMPORTANCE_PROMPT_VERSION,
    ImportanceEvaluationResult,
    StoredImportanceResult,
)
from .models import (
    DEFAULT_CLASSIFICATION_PROMPT_VERSION,
    DOCUMENT_ANALYSIS_RESULTS_TABLE,
    ClassificationResult,
    StoredClassificationResult,
)
from .ranking_models import RankingCandidate, RankedAnalysisResult
from .reliability_models import (
    DEFAULT_RELIABILITY_PROMPT_VERSION,
    ReliabilityEvaluationResult,
    StoredReliabilityResult,
)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def validate_document_workspace(*, workspace_id: str, document_version_id: str, supabase: Client | None = None) -> dict[str, Any]:
    db = supabase or get_supabase()
    version_rows = (
        db.table("document_versions")
        .select("id, document_id")
        .eq("id", document_version_id)
        .limit(1)
        .execute()
        .data
    )
    if not version_rows:
        raise DocumentVersionNotFoundError("DOCUMENT_VERSION_NOT_FOUND")

    document_id = version_rows[0]["document_id"]
    document_rows = (
        db.table("documents")
        .select("id, workspace_id")
        .eq("id", document_id)
        .limit(1)
        .execute()
        .data
    )
    if not document_rows:
        raise DocumentVersionNotFoundError("DOCUMENT_VERSION_NOT_FOUND")
    if str(document_rows[0]["workspace_id"]) != str(workspace_id):
        raise DocumentWorkspaceMismatchError("DOCUMENT_WORKSPACE_MISMATCH")
    return {"document_id": document_id, "workspace_id": document_rows[0]["workspace_id"]}


def save_classification_result(*, workspace_id: str, document_version_id: str, result: ClassificationResult, model_name: str, prompt_version: str = DEFAULT_CLASSIFICATION_PROMPT_VERSION, supabase: Client | None = None) -> StoredClassificationResult:
    db = supabase or get_supabase()
    validate_document_workspace(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    now = _now_iso()
    row = {
        "workspace_id": workspace_id,
        "document_version_id": document_version_id,
        "primary_category": result.primary_category.value,
        "secondary_categories": [category.value for category in result.secondary_categories],
        "classification_confidence": float(result.confidence),
        "classification_reason": result.reason,
        "status": "completed",
        "error_message": None,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "classified_at": now,
        "updated_at": now,
    }
    return _upsert_row(row=row, supabase=db)


def save_classification_failure(*, workspace_id: str, document_version_id: str, model_name: str, prompt_version: str = DEFAULT_CLASSIFICATION_PROMPT_VERSION, error_message: str, error_code: str | None = None, supabase: Client | None = None) -> StoredClassificationResult:
    db = supabase or get_supabase()
    validate_document_workspace(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    now = _now_iso()
    row = {
        "workspace_id": workspace_id,
        "document_version_id": document_version_id,
        "primary_category": None,
        "secondary_categories": [],
        "classification_confidence": None,
        "classification_reason": None,
        "status": "failed",
        "error_message": _sanitize_error_message(error_message),
        "model_name": model_name,
        "prompt_version": prompt_version,
        "classified_at": now,
        "updated_at": now,
    }
    stored = _upsert_row(row=row, supabase=db)
    stored.error_code = error_code
    return stored


def get_classification_result(*, workspace_id: str, document_version_id: str, model_name: str, prompt_version: str, supabase: Client | None = None) -> StoredClassificationResult | None:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("document_version_id", document_version_id)
            .eq("model_name", model_name)
            .eq("prompt_version", prompt_version)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("CLASSIFICATION_LOAD_FAILED") from exc
    return _row_to_stored_result(rows[0]) if rows else None


def get_latest_classification_result(*, workspace_id: str, document_version_id: str, supabase: Client | None = None) -> StoredClassificationResult | None:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("document_version_id", document_version_id)
            .order("classified_at", desc=True)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("CLASSIFICATION_LOAD_FAILED") from exc
    return _row_to_stored_result(rows[0]) if rows else None


def get_classification_results(*, workspace_id: str, document_version_ids: list[str], supabase: Client | None = None) -> list[StoredClassificationResult]:
    if not document_version_ids:
        return []
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .order("classified_at", desc=True)
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("CLASSIFICATION_LOAD_FAILED") from exc

    latest_by_document: dict[str, StoredClassificationResult] = {}
    for row in rows:
        stored = _row_to_stored_result(row)
        if stored.document_version_id not in latest_by_document:
            latest_by_document[stored.document_version_id] = stored
    return [latest_by_document[doc_id] for doc_id in document_version_ids if doc_id in latest_by_document]


def save_reliability_result(*, workspace_id: str, document_version_id: str, result: ReliabilityEvaluationResult, model_name: str, prompt_version: str = DEFAULT_RELIABILITY_PROMPT_VERSION, supabase: Client | None = None) -> StoredReliabilityResult:
    db = supabase or get_supabase()
    row = _get_analysis_row_for_reliability(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    now = _now_iso()
    update_payload = {
        "id": row["id"],
        "reliability_status": "completed",
        "reliability_score": result.reliability_score,
        "reliability_level": result.reliability_level.value,
        "traceability_score": result.traceability_score,
        "source_authority_score": result.source_authority_score,
        "current_validity_score": result.current_validity_score,
        "independent_evidence_score": result.independent_evidence_score,
        "factual_consistency_score": result.factual_consistency_score,
        "reliability_summary_reason": result.summary_reason,
        "reliability_detail": _build_reliability_detail(result),
        "reliability_model_name": model_name,
        "reliability_prompt_version": prompt_version,
        "reliability_evaluated_at": now,
        "reliability_error_message": None,
        "updated_at": now,
    }
    return _update_reliability_row(update_payload=update_payload, supabase=db, workspace_id=workspace_id)


def save_reliability_failure(*, workspace_id: str, document_version_id: str, model_name: str, prompt_version: str = DEFAULT_RELIABILITY_PROMPT_VERSION, error_code: str, error_message: str, supabase: Client | None = None) -> StoredReliabilityResult:
    db = supabase or get_supabase()
    row = _get_analysis_row_for_reliability(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    if row.get("reliability_status") == "completed":
        stored = _row_to_stored_reliability_result(row)
        stored.error_code = error_code
        return stored

    now = _now_iso()
    update_payload = {
        "id": row["id"],
        "reliability_status": "failed",
        "reliability_score": None,
        "reliability_level": None,
        "traceability_score": None,
        "source_authority_score": None,
        "current_validity_score": None,
        "independent_evidence_score": None,
        "factual_consistency_score": None,
        "reliability_summary_reason": None,
        "reliability_detail": {},
        "reliability_model_name": model_name,
        "reliability_prompt_version": prompt_version,
        "reliability_evaluated_at": now,
        "reliability_error_message": _sanitize_error_message(error_message),
        "updated_at": now,
    }
    stored = _update_reliability_row(update_payload=update_payload, supabase=db, workspace_id=workspace_id)
    stored.error_code = error_code
    return stored


def get_reliability_result(*, workspace_id: str, document_version_id: str, supabase: Client | None = None) -> StoredReliabilityResult | None:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("document_version_id", document_version_id)
            .order("reliability_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("RELIABILITY_LOAD_FAILED") from exc
    for row in rows:
        if row.get("reliability_status") in {"completed", "failed"}:
            return _row_to_stored_reliability_result(row)
    return None


def get_reliability_results(*, workspace_id: str, document_version_ids: list[str], supabase: Client | None = None) -> list[StoredReliabilityResult]:
    if not document_version_ids:
        return []
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .order("reliability_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("RELIABILITY_LOAD_FAILED") from exc

    latest_by_document: dict[str, StoredReliabilityResult] = {}
    for row in rows:
        if row.get("reliability_status") not in {"completed", "failed"}:
            continue
        stored = _row_to_stored_reliability_result(row)
        if stored.document_version_id not in latest_by_document:
            latest_by_document[stored.document_version_id] = stored
    return [latest_by_document[doc_id] for doc_id in document_version_ids if doc_id in latest_by_document]


def get_documents_ready_for_classification(
    *, workspace_id: str, limit: int = 20, since_days: int = 7, supabase: Client | None = None
) -> list[str]:
    """document_analysis_results 행이 아예 없는(분류를 한 번도 안 받은) document_version을 찾는다.

    나머지 3단계(get_documents_ready_for_reliability/importance, ranking)는 기존
    document_analysis_results 행의 상태 필드만 보면 되지만, 분류는 그 행 자체가 생기기
    전 단계라 documents/document_versions에서 직접 찾아야 한다. 전체 이력을 매번 스캔하지
    않도록 최근 since_days일로 창을 제한한다(수집 배치가 2시간마다 도니 충분히 넉넉하다).
    """
    db = supabase or get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    document_rows = (
        db.table("documents")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("status", "active")
        .gte("created_at", since)
        .execute()
        .data
    )
    document_ids = [row["id"] for row in document_rows]
    if not document_ids:
        return []

    version_rows = (
        db.table("document_versions")
        .select("id,created_at")
        .in_("document_id", document_ids)
        .order("created_at", desc=True)
        .limit(limit * 5)
        .execute()
        .data
    )
    version_ids = [row["id"] for row in version_rows]
    if not version_ids:
        return []

    analyzed_rows = (
        db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
        .select("document_version_id")
        .in_("document_version_id", version_ids)
        .execute()
        .data
    )
    already_analyzed = {row["document_version_id"] for row in analyzed_rows}

    return [vid for vid in version_ids if vid not in already_analyzed][:limit]


def get_documents_ready_for_ranking(*, workspace_id: str, limit: int = 20, supabase: Client | None = None) -> list[str]:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("document_version_id,status,reliability_status,importance_status,ranking_status")
            .eq("workspace_id", workspace_id)
            .eq("status", "completed")
            .eq("reliability_status", "completed")
            .eq("importance_status", "completed")
            .order("importance_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .limit(limit * 5)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("RANKING_LOAD_FAILED") from exc

    results: list[str] = []
    seen: set[str] = set()
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id or document_version_id in seen:
            continue
        if row.get("ranking_status", "pending") in {"pending", "failed", None}:
            results.append(document_version_id)
            seen.add(document_version_id)
        if len(results) >= limit:
            break
    return results


def get_documents_ready_for_reliability(*, workspace_id: str, limit: int = 20, supabase: Client | None = None) -> list[str]:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("document_version_id,status,reliability_status")
            .eq("workspace_id", workspace_id)
            .eq("status", "completed")
            .order("classified_at", desc=True)
            .order("updated_at", desc=True)
            .limit(limit * 5)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("RELIABILITY_LOAD_FAILED") from exc

    results: list[str] = []
    seen: set[str] = set()
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id or document_version_id in seen:
            continue
        if row.get("reliability_status", "pending") in {"pending", "failed", None}:
            results.append(document_version_id)
            seen.add(document_version_id)
        if len(results) >= limit:
            break
    return results


def save_importance_result(*, workspace_id: str, document_version_id: str, result: ImportanceEvaluationResult, model_name: str, prompt_version: str = DEFAULT_IMPORTANCE_PROMPT_VERSION, supabase: Client | None = None) -> StoredImportanceResult:
    db = supabase or get_supabase()
    row = _get_analysis_row_for_importance(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    now = _now_iso()
    update_payload = {
        "id": row["id"],
        "importance_status": "completed",
        "importance_score": result.importance_score,
        "importance_level": result.importance_level.value,
        "direct_relevance_score": result.direct_relevance_score,
        "business_impact_score": result.business_impact_score,
        "urgency_score": result.urgency_score,
        "industry_impact_score": result.industry_impact_score,
        "duration_score": result.duration_score,
        "external_attention_score": result.external_attention_score,
        "impact_direction": result.impact_direction.value,
        "time_horizon": result.time_horizon.value,
        "importance_summary_reason": result.summary_reason,
        "core_summary": _normalize_optional_text(result.core_summary),
        "key_points": _normalize_key_points(result.key_points),
        "key_numbers": _json_ready_list(result.key_numbers),
        "sk_hynix_implication": _normalize_optional_text(result.sk_hynix_implication),
        "summary_evidence_refs": _json_ready_list(result.summary_evidence_refs),
        "affected_areas": _normalize_text_array(result.affected_areas),
        "opportunities": _normalize_text_array(result.opportunities),
        "risks": _normalize_text_array(result.risks),
        "watch_points": _normalize_text_array(result.watch_points),
        "importance_missing_information": _normalize_text_array(result.missing_information),
        "importance_detail": _build_importance_detail(result),
        "importance_model_name": model_name,
        "importance_prompt_version": prompt_version,
        "importance_evaluated_at": now,
        "importance_error_message": None,
        "updated_at": now,
    }
    return _update_importance_row(update_payload=update_payload, supabase=db, workspace_id=workspace_id)


def save_importance_failure(*, workspace_id: str, document_version_id: str, model_name: str, prompt_version: str = DEFAULT_IMPORTANCE_PROMPT_VERSION, error_code: str, error_message: str, supabase: Client | None = None) -> StoredImportanceResult:
    db = supabase or get_supabase()
    row = _get_analysis_row_for_importance(workspace_id=workspace_id, document_version_id=document_version_id, supabase=db)
    if row.get("importance_status") == "completed":
        stored = _row_to_stored_importance_result(row)
        stored.error_code = error_code
        return stored

    now = _now_iso()
    update_payload = {
        "id": row["id"],
        "importance_status": "failed",
        "importance_score": None,
        "importance_level": None,
        "direct_relevance_score": None,
        "business_impact_score": None,
        "urgency_score": None,
        "industry_impact_score": None,
        "duration_score": None,
        "external_attention_score": None,
        "impact_direction": None,
        "time_horizon": None,
        "importance_summary_reason": None,
        "core_summary": None,
        "key_points": [],
        "key_numbers": [],
        "sk_hynix_implication": None,
        "summary_evidence_refs": [],
        "affected_areas": [],
        "opportunities": [],
        "risks": [],
        "watch_points": [],
        "importance_missing_information": [],
        "importance_detail": {},
        "importance_model_name": model_name,
        "importance_prompt_version": prompt_version,
        "importance_evaluated_at": now,
        "importance_error_message": _sanitize_error_message(error_message),
        "updated_at": now,
    }
    stored = _update_importance_row(update_payload=update_payload, supabase=db, workspace_id=workspace_id)
    stored.error_code = error_code
    return stored


def get_importance_result(*, workspace_id: str, document_version_id: str, supabase: Client | None = None) -> StoredImportanceResult | None:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("document_version_id", document_version_id)
            .order("importance_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("IMPORTANCE_LOAD_FAILED") from exc
    for row in rows:
        if row.get("importance_status") in {"completed", "failed"}:
            return _row_to_stored_importance_result(row)
    return None


def get_importance_results(*, workspace_id: str, document_version_ids: list[str], supabase: Client | None = None) -> list[StoredImportanceResult]:
    if not document_version_ids:
        return []
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .order("importance_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("IMPORTANCE_LOAD_FAILED") from exc

    latest_by_document: dict[str, StoredImportanceResult] = {}
    for row in rows:
        if row.get("importance_status") not in {"completed", "failed"}:
            continue
        stored = _row_to_stored_importance_result(row)
        if stored.document_version_id not in latest_by_document:
            latest_by_document[stored.document_version_id] = stored
    return [latest_by_document[doc_id] for doc_id in document_version_ids if doc_id in latest_by_document]


def get_analysis_results_for_report(*, workspace_id: str, document_version_ids: list[str], supabase: Client | None = None) -> list[AnalysisResultForReport]:
    if not document_version_ids:
        return []
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .eq("status", "completed")
            .eq("reliability_status", "completed")
            .eq("importance_status", "completed")
            .order("importance_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("IMPORTANCE_LOAD_FAILED") from exc

    latest_by_document: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("document_version_id") not in latest_by_document and _row_has_report_summary(row):
            latest_by_document[row["document_version_id"]] = row

    version_rows = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", list(latest_by_document.keys()) or [""])
        .execute()
        .data
    ) if latest_by_document else []
    version_to_document = {row["id"]: row["document_id"] for row in version_rows}

    document_rows = (
        db.table("documents")
        .select("id, title, canonical_url, published_at, source_id")
        .in_("id", list(set(version_to_document.values())) or [""])
        .execute()
        .data
    ) if version_to_document else []
    documents_by_id = {row["id"]: row for row in document_rows}

    source_ids = [row.get("source_id") for row in document_rows if row.get("source_id")]
    source_rows = (
        db.table("sources")
        .select("id, name")
        .in_("id", list(set(source_ids)) or [""])
        .execute()
        .data
    ) if source_ids else []
    sources_by_id = {row["id"]: row for row in source_rows}

    results: list[AnalysisResultForReport] = []
    for document_version_id in document_version_ids:
        row = latest_by_document.get(document_version_id)
        if row is None:
            continue
        document = documents_by_id.get(version_to_document.get(document_version_id), {})
        source = sources_by_id.get(document.get("source_id"), {}) if document.get("source_id") else {}
        payload = dict(row)
        payload["analysis_result_id"] = payload.get("id")
        payload["title"] = document.get("title") or ""
        payload["canonical_url"] = document.get("canonical_url")
        payload["published_at"] = document.get("published_at")
        payload["source_name"] = source.get("name")
        results.append(AnalysisResultForReport.model_validate(payload))
    return results


def get_documents_ready_for_importance(*, workspace_id: str, limit: int = 20, supabase: Client | None = None) -> list[str]:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("document_version_id,status,reliability_status,importance_status")
            .eq("workspace_id", workspace_id)
            .eq("status", "completed")
            .eq("reliability_status", "completed")
            .order("reliability_evaluated_at", desc=True)
            .order("updated_at", desc=True)
            .limit(limit * 5)
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationLoadFailedError("IMPORTANCE_LOAD_FAILED") from exc

    results: list[str] = []
    seen: set[str] = set()
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id or document_version_id in seen:
            continue
        if row.get("importance_status", "pending") in {"pending", "failed", None}:
            results.append(document_version_id)
            seen.add(document_version_id)
        if len(results) >= limit:
            break
    return results


def _get_analysis_row_for_reliability(*, workspace_id: str, document_version_id: str, supabase: Client) -> dict[str, Any]:
    validate_document_workspace(workspace_id=workspace_id, document_version_id=document_version_id, supabase=supabase)
    rows = (
        supabase.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("document_version_id", document_version_id)
        .order("classified_at", desc=True)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
        .data
    )
    if not rows:
        raise ClassificationLoadFailedError("ANALYSIS_RESULT_NOT_FOUND")
    row = rows[0]
    if row.get("status") != "completed" or row.get("primary_category") is None:
        raise ClassificationLoadFailedError("CLASSIFICATION_NOT_COMPLETED")
    return row


def _get_analysis_row_for_importance(*, workspace_id: str, document_version_id: str, supabase: Client) -> dict[str, Any]:
    row = _get_analysis_row_for_reliability(workspace_id=workspace_id, document_version_id=document_version_id, supabase=supabase)
    if row.get("reliability_status") != "completed" or row.get("reliability_score") is None or row.get("reliability_level") is None:
        raise ClassificationLoadFailedError("RELIABILITY_NOT_COMPLETED")
    return row


def _update_reliability_row(*, update_payload: dict[str, Any], supabase: Client, workspace_id: str | None = None) -> StoredReliabilityResult:
    try:
        query = supabase.table(DOCUMENT_ANALYSIS_RESULTS_TABLE).update(update_payload).eq("id", update_payload["id"])
        if workspace_id is not None:
            query = query.eq("workspace_id", workspace_id)
        result_rows = query.execute().data
    except Exception as exc:
        raise ClassificationSaveFailedError("RELIABILITY_SAVE_FAILED") from exc
    if not result_rows:
        raise ClassificationSaveFailedError("RELIABILITY_SAVE_FAILED")
    return _row_to_stored_reliability_result(result_rows[0])


def _update_importance_row(*, update_payload: dict[str, Any], supabase: Client, workspace_id: str | None = None) -> StoredImportanceResult:
    try:
        query = supabase.table(DOCUMENT_ANALYSIS_RESULTS_TABLE).update(update_payload).eq("id", update_payload["id"])
        if workspace_id is not None:
            query = query.eq("workspace_id", workspace_id)
        result_rows = query.execute().data
    except Exception as exc:
        raise ClassificationSaveFailedError("IMPORTANCE_SAVE_FAILED") from exc
    if not result_rows:
        raise ClassificationSaveFailedError("IMPORTANCE_SAVE_FAILED")
    return _row_to_stored_importance_result(result_rows[0])


def _upsert_row(*, row: dict[str, Any], supabase: Client) -> StoredClassificationResult:
    try:
        result_rows = (
            supabase.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .upsert(row, on_conflict="workspace_id,document_version_id,model_name,prompt_version")
            .execute()
            .data
        )
    except Exception as exc:
        raise ClassificationSaveFailedError("CLASSIFICATION_SAVE_FAILED") from exc
    if not result_rows:
        raise ClassificationSaveFailedError("CLASSIFICATION_SAVE_FAILED")
    return _row_to_stored_result(result_rows[0])


def _build_reliability_detail(result: ReliabilityEvaluationResult) -> dict[str, Any]:
    criteria = {}
    for key in [
        "traceability",
        "source_authority",
        "current_validity",
        "independent_evidence",
        "factual_consistency",
    ]:
        criterion = result.criteria.get(key)
        if criterion is None:
            continue
        criteria[key] = {
            "score": criterion.score,
            "reason": criterion.reason,
            "evidence_document_ids": list(criterion.evidence_document_ids),
            "warnings": list(criterion.warnings),
        }

    unique_evidence_ids = set()
    for criterion in result.criteria.values():
        unique_evidence_ids.update(criterion.evidence_document_ids)

    return {
        "criteria": criteria,
        "conflicting_claims": list(result.conflicting_claims),
        "missing_information": list(result.missing_information),
        "evaluated_document_version_ids": list(result.evaluated_document_version_ids),
        "source_signals": {
            "document_count": len(result.evaluated_document_version_ids),
            "independent_source_count": len(unique_evidence_ids) if unique_evidence_ids else len(result.evaluated_document_version_ids),
            "official_source_included": False,
        },
    }


def _build_importance_detail(result: ImportanceEvaluationResult) -> dict[str, Any]:
    criteria = {}
    for key, criterion in result.criteria.items():
        criteria[key] = {
            "score": criterion.score,
            "reason": criterion.reason,
            "evidence_document_ids": list(criterion.evidence_document_ids),
            "uncertainties": _normalize_text_array(criterion.uncertainties),
        }
    return {
        "criteria": criteria,
        "applied_caps": list(result.applied_caps),
        "code_signals": dict(result.code_signals),
        "evaluated_document_version_ids": list(result.evaluated_document_version_ids),
    }


def _row_to_stored_result(row: dict[str, Any]) -> StoredClassificationResult:
    payload = dict(row)
    payload.setdefault("secondary_categories", [])
    return StoredClassificationResult.model_validate(payload)


def _row_to_stored_reliability_result(row: dict[str, Any]) -> StoredReliabilityResult:
    payload = dict(row)
    payload.setdefault("secondary_categories", [])
    payload.setdefault("reliability_detail", {})
    payload["analysis_result_id"] = payload.get("id")
    return StoredReliabilityResult.model_validate(payload)


def _row_to_stored_importance_result(row: dict[str, Any]) -> StoredImportanceResult:
    payload = dict(row)
    payload.setdefault("secondary_categories", [])
    payload.setdefault("reliability_detail", {})
    payload.setdefault("key_points", [])
    payload.setdefault("key_numbers", [])
    payload.setdefault("summary_evidence_refs", [])
    payload.setdefault("affected_areas", [])
    payload.setdefault("opportunities", [])
    payload.setdefault("risks", [])
    payload.setdefault("watch_points", [])
    payload.setdefault("importance_missing_information", [])
    payload.setdefault("importance_detail", {})
    payload["analysis_result_id"] = payload.get("id")
    return StoredImportanceResult.model_validate(payload)


def _row_has_report_summary(row: dict[str, Any]) -> bool:
    return bool(
        str(row.get("core_summary") or "").strip()
        and list(row.get("key_points") or [])
        and str(row.get("sk_hynix_implication") or "").strip()
        and list(row.get("summary_evidence_refs") or [])
    )


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _normalize_key_points(values: list[str] | None) -> list[str]:
    return _normalize_text_array(values, max_items=5)


def _normalize_text_array(values: list[str] | None, *, max_items: int = 10) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value).split())
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
        if len(normalized) >= max_items:
            break
    return normalized


def _json_ready_list(values: list[Any] | None) -> list[dict[str, Any]]:
    if not values:
        return []
    ready: list[dict[str, Any]] = []
    for item in values:
        if hasattr(item, "model_dump"):
            ready.append(item.model_dump(mode="json", exclude_none=True))
        elif isinstance(item, dict):
            ready.append(dict(item))
    return ready


def _sanitize_error_message(message: str) -> str:
    sanitized = str(message)
    for env_name in ["OPENROUTER_API_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_URL"]:
        secret = os.getenv(env_name, "")
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized[:500]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def get_ranking_candidates(*, workspace_id: str, document_version_ids: list[str], supabase: Client | None = None) -> list[RankingCandidate]:
    if not document_version_ids:
        return []
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .order("importance_evaluated_at", desc=True)
            .order("reliability_evaluated_at", desc=True)
            .order("classified_at", desc=True)
            .order("id")
            .execute()
            .data
        )
    except Exception as exc:
        raise RankingLoadFailedError("RANKING_CANDIDATES_LOAD_FAILED") from exc

    rows_by_document: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id:
            continue
        rows_by_document.setdefault(document_version_id, []).append(row)

    selected_by_document: dict[str, dict[str, Any]] = {}
    for document_version_id in document_version_ids:
        selected = _select_analysis_row_for_ranking(
            rows=rows_by_document.get(document_version_id, []),
            workspace_id=workspace_id,
            document_version_id=document_version_id,
        )
        if selected is not None:
            selected_by_document[document_version_id] = selected

    metadata = _load_document_metadata(db=db, document_version_ids=list(selected_by_document.keys()))
    results: list[RankingCandidate] = []
    for document_version_id in document_version_ids:
        row = selected_by_document.get(document_version_id)
        if row is None:
            continue
        payload = _build_ranking_payload(row=row, metadata=metadata.get(document_version_id, {}))
        results.append(RankingCandidate.model_validate(payload))
    return results


def save_ranking_results(*, workspace_id: str, results: list[RankedAnalysisResult], supabase: Client | None = None) -> list[RankedAnalysisResult]:
    if not results:
        return []
    db = supabase or get_supabase()
    saved: list[RankedAnalysisResult] = []
    for result in results:
        payload = {
            "ranking_status": result.ranking_status,
            "ranking_score": str(result.ranking_score) if result.ranking_score is not None else None,
            "recency_score": result.recency_score,
            "ranking_position": result.ranking_position,
            "selected_for_report": result.selected_for_report,
            "report_selection_position": result.report_selection_position,
            "selection_reason": result.selection_reason,
            "ranking_exclusion_reason": result.ranking_exclusion_reason,
            "ranking_formula_version": result.ranking_formula_version,
            "ranking_reference_time": result.ranking_reference_time.isoformat() if result.ranking_reference_time else None,
            "ranking_batch_date": result.ranking_batch_date.isoformat() if result.ranking_batch_date else None,
            "ranked_at": result.ranked_at.isoformat() if result.ranked_at else None,
            "ranking_detail": dict(result.ranking_detail or {}),
            "ranking_error_message": _sanitize_error_message(result.ranking_error_message) if result.ranking_error_message else None,
            "updated_at": _now_iso(),
        }
        try:
            updated_rows = (
                db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
                .update(payload)
                .eq("id", result.analysis_result_id)
                .eq("workspace_id", workspace_id)
                .eq("document_version_id", result.document_version_id)
                .execute()
                .data
            )
        except Exception as exc:
            raise RankingSaveFailedError(
                f"RANKING_PERSISTENCE_FAILED: analysis_result_id={result.analysis_result_id} workspace_id={workspace_id} document_version_id={result.document_version_id}"
            ) from exc
        if not updated_rows:
            raise RankingSaveFailedError(
                f"ANALYSIS_RESULT_NOT_FOUND: analysis_result_id={result.analysis_result_id} workspace_id={workspace_id} document_version_id={result.document_version_id}"
            )
        if len(updated_rows) != 1:
            raise RankingSaveFailedError(
                f"RANKING_RESULT_INCONSISTENT: analysis_result_id={result.analysis_result_id} workspace_id={workspace_id} document_version_id={result.document_version_id}"
            )
        updated_row = updated_rows[0]
        updated_ranking_score = updated_row.get("ranking_score")
        ranking_score_matches = (
            updated_ranking_score is None and result.ranking_score is None
        ) or (
            updated_ranking_score is not None
            and result.ranking_score is not None
            and Decimal(str(updated_ranking_score)) == Decimal(str(result.ranking_score))
        )
        if (
            str(updated_row.get("id")) != str(result.analysis_result_id)
            or str(updated_row.get("workspace_id")) != str(workspace_id)
            or str(updated_row.get("document_version_id")) != str(result.document_version_id)
            or str(updated_row.get("ranking_formula_version")) != str(result.ranking_formula_version)
            or not ranking_score_matches
        ):
            raise RankingSaveFailedError(
                f"RANKING_RESULT_INCONSISTENT: analysis_result_id={result.analysis_result_id} workspace_id={workspace_id} document_version_id={result.document_version_id}"
            )
        saved.append(_row_to_ranked_result(updated_row, metadata={
            "title": result.title,
            "primary_category": result.primary_category,
            "secondary_categories": list(result.secondary_categories),
            "canonical_url": result.canonical_url,
            "source_name": result.source_name,
            "published_at": result.published_at,
        }))
    return saved


def get_ranking_results(*, workspace_id: str, ranking_batch_date: date, supabase: Client | None = None) -> list[RankedAnalysisResult]:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("ranking_batch_date", ranking_batch_date.isoformat())
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise RankingLoadFailedError("RANKING_RESULTS_LOAD_FAILED") from exc

    selected_rows: list[dict[str, Any]] = []
    selected_document_ids: list[str] = []
    rows_by_document: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id:
            continue
        rows_by_document.setdefault(document_version_id, []).append(row)

    for document_version_id, document_rows in rows_by_document.items():
        selected = _select_ranked_analysis_row(
            rows=document_rows,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            include_selected_for_report_only=False,
        )
        if selected is None:
            continue
        selected_rows.append(selected)
        selected_document_ids.append(document_version_id)

    metadata = _load_document_metadata(db=db, document_version_ids=selected_document_ids)
    completed: list[RankedAnalysisResult] = []
    excluded_or_failed: list[RankedAnalysisResult] = []
    for row in selected_rows:
        document_version_id = row["document_version_id"]
        ranked = _row_to_ranked_result(row, metadata=metadata.get(document_version_id, {}))
        if ranked.ranking_status == "completed":
            completed.append(ranked)
        else:
            excluded_or_failed.append(ranked)

    completed.sort(key=lambda item: item.ranking_position or 10**9)
    excluded_or_failed.sort(key=lambda item: (item.document_version_id, item.title))
    return completed + excluded_or_failed


def get_ranked_results_for_report(*, workspace_id: str, ranking_batch_date: date, limit: int = 20, supabase: Client | None = None) -> list[AnalysisResultForReport]:
    db = supabase or get_supabase()
    try:
        rows = (
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("ranking_batch_date", ranking_batch_date.isoformat())
            .eq("ranking_status", "completed")
            .eq("selected_for_report", True)
            .eq("status", "completed")
            .eq("reliability_status", "completed")
            .eq("importance_status", "completed")
            .order("updated_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:
        raise RankingLoadFailedError("RANKED_REPORT_RESULTS_LOAD_FAILED") from exc

    selected_rows: list[dict[str, Any]] = []
    selected_document_ids: list[str] = []
    rows_by_document: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id:
            continue
        rows_by_document.setdefault(document_version_id, []).append(row)

    for document_version_id, document_rows in rows_by_document.items():
        selected = _select_ranked_analysis_row(
            rows=document_rows,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            include_selected_for_report_only=True,
        )
        if selected is None:
            continue
        selected_rows.append(selected)
        selected_document_ids.append(document_version_id)

    metadata = _load_document_metadata(db=db, document_version_ids=selected_document_ids)
    results: list[AnalysisResultForReport] = []
    for row in selected_rows:
        document_version_id = row["document_version_id"]
        payload = dict(row)
        payload["analysis_result_id"] = payload.get("id")
        payload["ranking_score"] = float(payload["ranking_score"]) if payload.get("ranking_score") is not None else None
        payload.update(metadata.get(document_version_id, {}))
        results.append(AnalysisResultForReport.model_validate(payload))
    results.sort(key=lambda item: item.report_selection_position or 10**9)
    return results[:limit]


def _select_analysis_row_for_ranking(*, rows: list[dict[str, Any]], workspace_id: str, document_version_id: str) -> dict[str, Any] | None:
    ready_rows = [row for row in rows if _row_is_ranking_candidate_ready(row)]
    if not ready_rows:
        return None

    current_version_rows = [
        row
        for row in ready_rows
        if row.get("prompt_version") == DEFAULT_CLASSIFICATION_PROMPT_VERSION
        and row.get("reliability_prompt_version") == DEFAULT_RELIABILITY_PROMPT_VERSION
        and row.get("importance_prompt_version") == DEFAULT_IMPORTANCE_PROMPT_VERSION
    ]
    preferred_rows = current_version_rows or ready_rows

    signatures: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for row in preferred_rows:
        signature = (
            row.get("model_name"),
            row.get("prompt_version"),
            row.get("reliability_model_name"),
            row.get("reliability_prompt_version"),
            row.get("importance_model_name"),
            row.get("importance_prompt_version"),
        )
        signatures.setdefault(signature, []).append(row)
    duplicate_signatures = [items for items in signatures.values() if len(items) > 1]
    if duplicate_signatures:
        raise RankingLoadFailedError(
            f"AMBIGUOUS_ANALYSIS_RESULT: workspace_id={workspace_id} document_version_id={document_version_id} analysis_result_id={duplicate_signatures[0][0].get('id')}"
        )

    preferred_rows.sort(key=lambda row: str(row.get("id") or ""))
    preferred_rows.sort(key=lambda row: row.get("classified_at") or "", reverse=True)
    preferred_rows.sort(key=lambda row: row.get("reliability_evaluated_at") or "", reverse=True)
    preferred_rows.sort(key=lambda row: row.get("importance_evaluated_at") or "", reverse=True)
    return preferred_rows[0]



def _select_ranked_analysis_row(
    *,
    rows: list[dict[str, Any]],
    workspace_id: str,
    document_version_id: str,
    include_selected_for_report_only: bool,
) -> dict[str, Any] | None:
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("ranking_status") not in {"completed", "excluded", "failed"}:
            continue
        if include_selected_for_report_only:
            if row.get("ranking_status") != "completed":
                continue
            if not row.get("selected_for_report"):
                continue
            if row.get("report_selection_position") is None:
                continue
            if not _row_is_ranking_candidate_ready(row):
                continue
            if not _row_has_report_summary(row):
                continue
        eligible_rows.append(row)

    if not eligible_rows:
        return None

    signatures: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for row in eligible_rows:
        signature = (
            row.get("ranking_status"),
            row.get("ranking_formula_version"),
            row.get("ranking_position"),
            row.get("report_selection_position"),
            row.get("selected_for_report"),
            row.get("ranking_score"),
        )
        signatures.setdefault(signature, []).append(row)
    duplicate_signatures = [items for items in signatures.values() if len(items) > 1]
    if duplicate_signatures:
        raise RankingLoadFailedError(
            f"AMBIGUOUS_ANALYSIS_RESULT: workspace_id={workspace_id} document_version_id={document_version_id} analysis_result_id={duplicate_signatures[0][0].get('id')}"
        )

    eligible_rows.sort(key=lambda row: str(row.get("id") or ""))
    eligible_rows.sort(key=lambda row: row.get("classified_at") or "", reverse=True)
    eligible_rows.sort(key=lambda row: row.get("reliability_evaluated_at") or "", reverse=True)
    eligible_rows.sort(key=lambda row: row.get("importance_evaluated_at") or "", reverse=True)
    return eligible_rows[0]


def _row_is_ranking_candidate_ready(row: dict[str, Any]) -> bool:
    return bool(
        row.get("status") == "completed"
        and row.get("primary_category")
        and row.get("reliability_status") == "completed"
        and row.get("reliability_score") is not None
        and row.get("reliability_level") is not None
        and row.get("importance_status") == "completed"
        and row.get("importance_score") is not None
        and row.get("importance_level") is not None
        and str(row.get("core_summary") or "").strip()
        and len(list(row.get("key_points") or [])) >= 3
        and str(row.get("sk_hynix_implication") or "").strip()
    )


def _load_document_metadata(*, db: Client, document_version_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not document_version_ids:
        return {}
    version_rows = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
        .data
    )
    version_to_document = {row["id"]: row["document_id"] for row in version_rows}
    document_ids = list(set(version_to_document.values()))
    document_rows = (
        db.table("documents")
        .select("id, title, canonical_url, published_at, source_id")
        .in_("id", document_ids or [""])
        .execute()
        .data
    ) if document_ids else []
    documents_by_id = {row["id"]: row for row in document_rows}
    source_ids = [row.get("source_id") for row in document_rows if row.get("source_id")]
    source_rows = (
        db.table("sources")
        .select("id, name")
        .in_("id", list(set(source_ids)) or [""])
        .execute()
        .data
    ) if source_ids else []
    sources_by_id = {row["id"]: row for row in source_rows}

    metadata: dict[str, dict[str, Any]] = {}
    for document_version_id in document_version_ids:
        document = documents_by_id.get(version_to_document.get(document_version_id), {})
        source = sources_by_id.get(document.get("source_id"), {}) if document.get("source_id") else {}
        metadata[document_version_id] = {
            "title": document.get("title") or "",
            "canonical_url": document.get("canonical_url"),
            "published_at": document.get("published_at"),
            "source_name": source.get("name"),
        }
    return metadata


def _build_ranking_payload(*, row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["analysis_result_id"] = payload.get("id")
    payload["title"] = metadata.get("title") or ""
    payload["canonical_url"] = metadata.get("canonical_url")
    payload["published_at"] = metadata.get("published_at")
    payload["source_name"] = metadata.get("source_name")
    payload["existing_ranking_status"] = payload.get("ranking_status")
    payload["existing_ranking_score"] = payload.get("ranking_score")
    payload["existing_recency_score"] = payload.get("recency_score")
    payload["existing_ranking_position"] = payload.get("ranking_position")
    payload["existing_selected_for_report"] = payload.get("selected_for_report", False)
    payload["existing_report_selection_position"] = payload.get("report_selection_position")
    payload["existing_selection_reason"] = payload.get("selection_reason")
    payload["existing_ranking_exclusion_reason"] = payload.get("ranking_exclusion_reason")
    payload["existing_ranking_formula_version"] = payload.get("ranking_formula_version")
    payload["existing_ranking_reference_time"] = payload.get("ranking_reference_time")
    payload["existing_ranking_batch_date"] = payload.get("ranking_batch_date")
    payload["existing_ranked_at"] = payload.get("ranked_at")
    payload["existing_ranking_detail"] = payload.get("ranking_detail") or {}
    payload["existing_ranking_error_message"] = payload.get("ranking_error_message")
    return payload


def _row_to_ranked_result(row: dict[str, Any], metadata: dict[str, Any]) -> RankedAnalysisResult:
    payload = dict(row)
    payload["analysis_result_id"] = payload.get("id")
    payload.setdefault("secondary_categories", [])
    payload.setdefault("key_points", [])
    payload.setdefault("key_numbers", [])
    payload.setdefault("summary_evidence_refs", [])
    payload.setdefault("opportunities", [])
    payload.setdefault("risks", [])
    payload.setdefault("watch_points", [])
    payload.setdefault("ranking_detail", {})
    payload["title"] = metadata.get("title") or payload.get("title") or ""
    payload["primary_category"] = payload.get("primary_category") or metadata.get("primary_category") or ""
    payload["canonical_url"] = metadata.get("canonical_url")
    payload["published_at"] = metadata.get("published_at")
    payload["source_name"] = metadata.get("source_name")
    return RankedAnalysisResult.model_validate(payload)
