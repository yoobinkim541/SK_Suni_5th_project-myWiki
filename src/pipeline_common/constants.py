"""
상태값 문자열을 코드 전체에 흩뿌리지 않기 위해 한곳에 모은다 (명세 §0).
다른 파트도 이 모듈을 import해 쓴다.

DB에 값을 추가·변경하면 이 파일을 먼저 고친다.
"""
from __future__ import annotations

# --- DB CHECK 제약과 1:1 대응. 임의로 값을 늘리지 않는다 ---
SOURCE_TYPES = ("news", "rss", "disclosure", "report", "website", "manual_upload")
DOCUMENT_STATUSES = ("active", "deleted", "blocked", "failed")
JOB_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
JOB_TYPES = ("collect", "parse_document", "index_qmd", "generate_wiki", "generate_report")
TARGET_TYPES = ("document", "document_version", "wiki_page", "report")  # 'source' 없음 주의

# --- Storage 버킷 (myWiki_v2_supabase.sql 생성분) ---
BUCKET_RAW = "raw"
BUCKET_PROCESSED = "processed"
BUCKET_WIKI = "wiki"  # Wiki 파트 전용. 이 파트는 쓰지 않음

# --- 이 파트 운영 상수 (변경 가능, config로 override) ---
MAX_RETRY = 3
HASH_ALGORITHM = "sha256"

# --- 자주 쓰는 개별 상태값 (오타 방지용 별칭) ---
JOB_TYPE_COLLECT = "collect"
JOB_TYPE_PARSE_DOCUMENT = "parse_document"

TARGET_TYPE_DOCUMENT = "document"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

DOC_STATUS_ACTIVE = "active"
DOC_STATUS_DELETED = "deleted"
DOC_STATUS_BLOCKED = "blocked"
DOC_STATUS_FAILED = "failed"
