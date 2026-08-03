// [LIVE] src/api/main.py 실제 연결 — 이미 구현·배포된 채팅 엔드포인트(윤혜민 담당).
// AgentPage.jsx의 MOCK_THREAD를 이 함수들로 교체한다.
import { apiFetch } from './client';

/** @returns {Promise<{id, workspace_id, user_id, title, created_at, updated_at}>} */
export function createChatSession(title) {
  return apiFetch('/chat/sessions', { method: 'POST', body: { title } });
}

/**
 * ChatMessage.jsx가 기대하는 형태로 오지 않는다 — role이 'user'|'assistant'(BE) vs
 * 'me'|'ai'(FE 목업)라 매핑이 필요하다. citations는 message_citations 그대로 옴
 * (document_version_id만 있고 출처 라벨은 없음 — wiki.js의 sources와 동일한 제약).
 * @returns {Promise<{id, session_id, role, content, model_name, prompt_version, created_at,
 *   citations: {id, document_version_id, quoted_text, relevance_score, citation_order}[]}[]>}
 */
export function fetchChatMessages(sessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages`);
}

/**
 * 근거 부족(has_answer=false)일 땐 assistant_message.content가
 * "[근거 부족] <사유>" 문자열로 옴 — AgentPage.jsx의 `none:{title, desc}` 카드 분기는
 * 이 접두사로 판별해서 프론트에서 구성해야 한다(백엔드가 title/desc를 나눠 주지 않음).
 * @returns {Promise<{user_message, assistant_message, has_answer}>}
 */
export function sendChatMessage(sessionId, content) {
  return apiFetch(`/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: { content },
  });
}

// AgentPage.jsx 우측 "근거 원문"(MOCK_EVIDENCE: excerpt/footer 포함)에 대응하는 백엔드는
// 없음 — citations에는 quoted_text/relevance_score까지만 있고, 원문 발췌 카드 형태의
// 별도 조회는 필요시 추가 논의.
