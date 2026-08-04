"""
대화 제목 자동 생성 — 첫 질문에서 짧은 주제 라벨을 뽑는다.

WikiAgent(tool-use RAG)와는 완전히 별개의 부가 기능이라 분리했다. 실패해도
메시지 저장 자체를 막으면 안 되므로, 모든 예외를 삼키고 None을 돌려준다 —
호출부(main.py)는 None이면 단순 truncate(_truncate_title)로 대신한다.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from openai import OpenAI

from .core import MODEL_NAME, OPENROUTER_BASE_URL

logger = logging.getLogger(__name__)

# deepseek-v4-flash는 답을 내기 전에 "reasoning" 토큰을 먼저 쓰고, 그것도 max_tokens
# 예산에 포함된다. 같은 프롬프트로도 reasoning 토큰 소비량이 호출마다 0~280개 사이로
# 들쭉날쭉해서(직접 5~10회 측정해 확인) max_tokens를 아무리 올려도 안전을 보장할 수
# 없었다 — 그래서 extra_body의 reasoning.enabled=False로 이 모델의 reasoning 자체를
# 꺼버렸다(OpenRouter 통합 reasoning 파라미터). 이후 5회 재현에서 reasoning_tokens=0으로
# 고정되는 걸 확인했다.
MAX_TOKENS = 60

TITLE_PROMPT = """\
다음은 채팅방에 방금 올라온 첫 질문이다. 이 질문의 주제를 8~20자 사이의 짧은
한국어 명사구로 요약해라. 설명이나 부연 없이 제목 문자열만 출력하고, 따옴표나
마침표는 붙이지 마라.

질문: {question}
"""


def generate_session_title(question: str, client: Optional[OpenAI] = None) -> Optional[str]:
    try:
        openai_client = client or OpenAI(
            base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"]
        )
        response = openai_client.chat.completions.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            extra_body={"reasoning": {"enabled": False}},
            messages=[
                {"role": "user", "content": TITLE_PROMPT.format(question=question[:300])},
            ],
        )
        choice = response.choices[0]
        title = choice.message.content
        if not title:
            logger.warning(
                "제목 생성 결과가 비어 있음 (finish_reason=%s)", choice.finish_reason
            )
            return None
        title = title.strip().strip('"“”').strip("'").strip("`").strip()
        return title[:60] or None
    except Exception:
        logger.warning("제목 생성 실패", exc_info=True)
        return None
