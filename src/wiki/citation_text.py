from __future__ import annotations

import re

# 본문의 [N] 표기 중 citations/sources 배열 범위(1..citation_count)를 벗어난 것을 찾는다.
# 앞에 붙는 공백까지 같이 지워서 "문장입니다 [4]."처럼 공백이 남지 않게 한다.
_CITATION_MARKER_RE = re.compile(r"\s?\[(\d+)\]")


def strip_orphaned_citation_markers(text: str, citation_count: int) -> str:
    """근거 개수 범위를 벗어난 [N] 각주를 텍스트에서 제거한다.

    LLM이 본문에는 [1]~[N]을 인용해놓고 실제 근거(citations/sources)는 그보다 적게
    제출/저장하는 경우(실사용 데이터에서 확인된 버그) — 죽은 각주(클릭해도 갈 곳
    없는 번호)가 화면에 남지 않도록, 에이전트 답변 생성 시점과 기존 위키 문서
    정리 배치 양쪽에서 공용으로 쓴다.
    """
    def _replace(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= citation_count:
            return match.group(0)
        return ""

    return _CITATION_MARKER_RE.sub(_replace, text)
