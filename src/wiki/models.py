from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from ..analysis.models import Category


class WikiSearchRequest(BaseModel):
    workspace_id: str
    query: str | None = None
    query_terms: tuple[str, ...] = ()
    category: Category | None = None
    limit: int = Field(ge=1)

    @field_validator("workspace_id", mode="before")
    @classmethod
    def validate_workspace_id(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("workspace_id must not be empty.")
        return text

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("query_terms", mode="before")
    @classmethod
    def normalize_query_terms(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            candidates = [value]
        else:
            try:
                candidates = list(value)
            except TypeError as exc:
                raise ValueError("query_terms must be a sequence of strings.") from exc

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            term = str(candidate).strip()
            if not term or term in seen:
                continue
            normalized.append(term)
            seen.add(term)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_search_input(self) -> "WikiSearchRequest":
        if self.query is None and not self.query_terms:
            raise ValueError("query or query_terms must be provided.")
        return self


class WikiSearchResult(BaseModel):
    wiki_page_id: str
    wiki_version_id: str
    workspace_id: str
    slug: str
    title: str
    content: str
    score: float = Field(ge=0.0, le=1.0)
    updated_at: datetime | None = None
    source_document_version_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "wiki_page_id",
        "wiki_version_id",
        "workspace_id",
        "slug",
        "title",
        "content",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("required text fields must not be empty.")
        return text

    @field_validator("updated_at", mode="before")
    @classmethod
    def parse_updated_at(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @field_validator("source_document_version_ids", mode="before")
    @classmethod
    def normalize_source_document_version_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = list(value)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            identifier = str(item).strip()
            if not identifier or identifier in seen:
                continue
            normalized.append(identifier)
            seen.add(identifier)
        return normalized
