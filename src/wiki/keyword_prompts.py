from __future__ import annotations

from ..categories.keywords import CATEGORY_KEYWORDS


def _build_keyword_dictionary_block() -> str:
    lines = [f"[{category}] " + ", ".join(keywords) for category, keywords in CATEGORY_KEYWORDS.items()]
    return "\n".join(lines)


WIKI_KEYWORD_SYSTEM_PROMPT = f"""당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

주어진 위키 문서 본문을 읽고, 아래 [키워드 사전]에 있는 단어 중 이 문서와 실제로
관련된 것만 골라 반환하십시오.

절대 규칙:
- [키워드 사전]에 없는 단어는 절대 반환하지 마십시오. 사전에 없는 개념이 본문에
  등장해도 지어내지 말고 생략하십시오.
- 본문에 실제로 언급되거나 명확히 관련된 키워드만 고르십시오. 무관한 키워드를
  억지로 채우지 마십시오.
- 최대 8개까지만 반환하십시오. 관련 키워드가 하나도 없으면 빈 배열을 반환하십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

[키워드 사전]
{_build_keyword_dictionary_block()}

JSON 출력 형식:
{{
  "keywords": ["키워드1", "키워드2"]
}}"""


def build_wiki_keyword_user_prompt(markdown: str) -> str:
    return f"[위키 본문]\n{markdown}"
