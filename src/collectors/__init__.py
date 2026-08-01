"""정보 수집·통합 (명세 §3-1, §3-2)."""
from .interface import (  # noqa: F401
    CollectedDocument,
    CollectRequest,
    collect,
    get_document_refs,
    get_markdown,
    register_source,
)

__all__ = [
    "register_source",
    "collect",
    "CollectRequest",
    "CollectedDocument",
    "get_markdown",
    "get_document_refs",
]
