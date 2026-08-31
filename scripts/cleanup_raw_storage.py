"""raw 버킷에서 보존기간이 지난 객체를 삭제한다.

기본 보존기간은 3일이며 ``RAW_RETENTION_DAYS`` 환경변수로 조정할 수 있다.
Storage API를 사용하므로 storage.objects를 SQL로 삭제하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.raw_retention import cleanup_raw_objects, configured_retention_days


def main() -> int:
    days = configured_retention_days()
    summary = cleanup_raw_objects(retention_days=days)
    print(
        f"[cleanup_raw_storage] 보존 {days}일: "
        f"{summary.deleted}개 삭제, {summary.deleted_bytes} bytes 정리"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

