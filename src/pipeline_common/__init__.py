"""
collectors / preprocessing 두 파트가 공유하는 계층.

- constants : DB CHECK 제약과 1:1 대응하는 상태값 (명세 §0)
- models    : 파트 간 주고받는 데이터 계약 (명세 §2)
- db        : Supabase 클라이언트 (service_role)
- storage   : 버킷 경로 규칙 (명세 §6)
- repository: sources/documents/document_versions 접근을 한곳에 모은 계층
- jobs      : pipeline_jobs 기록 (명세 §4-4, §5-2)
- versioning: next_document_version_no (명세 §3-5)
- refs      : 하류 조회 헬퍼 get_markdown / get_document_refs (명세 §3-6, §3-7)
"""
