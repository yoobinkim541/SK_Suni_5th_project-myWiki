// 에이전트 API 호출부.
// USE_MOCK=true면 data/mockWiki.js를 그대로 돌려주고, false면 api/agent.js를 호출합니다.
// 백엔드 응답 shape과 화면(AgentPage.jsx)이 기대하는 shape이 달라서 아래 어댑터로 변환합니다.

import * as agentApi from '../api/agent';
import { MOCK_AGENT_PANES, MOCK_AGENT_REPLY } from '../data/mockWiki';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// 근거 부족 응답 판별용 접두사 — 백엔드가 content 앞에 붙여서 보냅니다.
const NO_ANSWER_PREFIX = '[근거 부족]';

// ---------- 변환 함수 ----------

// 백엔드 role → 화면 role
function toViewRole(role) {
  return role === 'assistant' ? 'ai' : 'me';
}

// "[근거 부족] 사유" 문자열을 화면의 none:{title, desc} 카드로 분리합니다.
// 백엔드가 title/desc를 나눠 주지 않아 프론트에서 구성합니다.
function parseNoAnswer(content) {
  const reason = content.slice(NO_ANSWER_PREFIX.length).trim();
  return {
    title: '축적된 근거에서 답을 찾지 못했습니다',
    desc: reason || '근거가 부족해 답변을 생성하지 않았습니다.',
  };
}

// citations[] → 화면 cites[{no, key}]
// 주의: 백엔드는 document_version_id만 주고 출처 종류(dart/etnews 등)를 알려주지 않습니다.
// key를 임의로 지어내면 잘못된 출처를 표시하게 되므로 null로 둡니다.
// (documents 조인이 백엔드에 추가되면 여기서 실제 key를 채웁니다.)
function toCites(citations = []) {
  return citations.map((c, i) => ({
    no: c.citation_order ?? i + 1,
    key: null,
    documentVersionId: c.document_version_id,
  }));
}

// citations[] → 우측 "근거 원문" 카드
// title/foot에 해당하는 데이터가 백엔드에 없어 확인 가능한 값만 채웁니다.
function toEvidence(citations = []) {
  return citations.map((c, i) => ({
    no: c.citation_order ?? i + 1,
    key: null,
    title: `근거 문서 #${c.citation_order ?? i + 1}`,
    excerpt: c.quoted_text ?? '',
    foot: '출처 정보 확인 중',
  }));
}

// author_name → 화면 author{initial, name}. 백엔드가 이름을 안 주면(과거 메시지 등) 생략합니다.
function toAuthor(authorName) {
  if (!authorName) return undefined;
  return { initial: authorName.charAt(0).toUpperCase(), name: authorName };
}

// 백엔드 메시지 하나 → 화면 메시지 하나.
// scope='mine'인 답변에만 "팀에 공유"를 붙입니다 — 이미 team 세션에 있는 답변을 다시
// 팀에 공유하는 건 의미가 없고, 백엔드 share-to-team도 개인 세션 기준입니다.
function toViewMessage(msg, scope) {
  const role = toViewRole(msg.role);

  if (role === 'me') {
    return { role: 'me', text: msg.content, author: toAuthor(msg.author_name), _id: msg.id };
  }

  // 근거 부족 응답
  if (typeof msg.content === 'string' && msg.content.startsWith(NO_ANSWER_PREFIX)) {
    return {
      role: 'ai',
      none: parseNoAnswer(msg.content),
      acts: ['수집 소스 추가', '관련 문서 찾아보기', '다시 생성', '삭제'],
      _id: msg.id,
    };
  }

  // 정상 응답 — 백엔드 content는 평문 한 덩어리라 각주 번호를 문장에 끼워 넣을 수 없습니다.
  // paragraphs는 [[문자열]] 형태 하나로 두고, 근거는 cites/evidence로만 표시합니다.
  return {
    role: 'ai',
    paragraphs: [[msg.content]],
    cites: toCites(msg.citations),
    acts:
      scope === 'mine'
        ? ['팀에 공유', '위키에 저장', '복사', '다시 생성', '삭제']
        : ['위키에 저장', '복사', '다시 생성', '삭제'],
    _id: msg.id,
  };
}

// 세션 하나 → 화면 대화 하나 (메시지는 아직 안 불러온 상태)
function toViewConversation(session) {
  return {
    id: session.id,
    title: session.title || '제목 없는 대화',
    meta: formatMeta(session.updated_at ?? session.created_at),
    archivedAt: session.archived_at ?? null,
    messages: [],
    evidence: [],
    _loaded: false,
  };
}

function formatMeta(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const today = new Date();
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  if (sameDay) return '오늘';
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${mm}.${dd}`;
}

// ---------- 화면에서 쓰는 함수 ----------

/**
 * 팀/개인 두 pane 전체.
 * label/ctx/hints 같은 화면 문구는 백엔드가 내려주지 않는 고정 UI 카피라 목업(MOCK_AGENT_PANES)
 * 값을 그대로 쓰고, conversations만 실제 세션 목록(scope=mine|team)으로 교체합니다.
 * team 세션은 여러 개일 수 있고(공유할 때마다 고르거나 새로 만듦), 0개일 수도 있습니다
 * (아직 아무도 공유한 적 없는 워크스페이스) — 0개인 경우는 AgentPage.jsx가 빈 상태로 보여줍니다.
 */
export async function fetchAgentPanes() {
  if (USE_MOCK) return MOCK_AGENT_PANES;

  const [teamSessions, mineSessions] = await Promise.all([
    agentApi.fetchChatSessions('team'),
    agentApi.fetchChatSessions('mine'),
  ]);

  return {
    team: { ...MOCK_AGENT_PANES.team, conversations: teamSessions.map(toViewConversation) },
    mine: { ...MOCK_AGENT_PANES.mine, conversations: mineSessions.map(toViewConversation) },
  };
}

/**
 * 대화방 하나의 메시지 + 근거 원문을 불러옵니다.
 * @param {string} sessionId
 * @param {'team'|'mine'} scope 어느 pane의 대화인지 — "팀에 공유" 버튼 노출 여부에 씁니다.
 */
export async function fetchConversation(sessionId, scope) {
  if (USE_MOCK) {
    return { messages: [], evidence: [] };
  }

  const raw = await agentApi.fetchChatMessages(sessionId);
  const messages = raw.map((m) => toViewMessage(m, scope));

  // 근거 원문 컬럼은 마지막 AI 응답의 citations를 씁니다.
  const lastAi = [...raw].reverse().find((m) => m.role === 'assistant');
  const evidence = toEvidence(lastAi?.citations);

  return { messages, evidence };
}

/**
 * 새 대화 생성.
 * @param {'team'|'private'} visibility
 */
export async function createConversation(title, visibility = 'private') {
  if (USE_MOCK) {
    return {
      id: `local-${Date.now()}`,
      title: title || '새 대화',
      meta: '오늘',
      messages: [],
      evidence: [],
    };
  }

  const session = await agentApi.createChatSession(title || '새 대화', visibility);
  return toViewConversation(session);
}

/**
 * 질문 전송. 사용자 메시지와 AI 응답을 화면 shape으로 함께 돌려줍니다.
 * @param {'team'|'mine'} scope 방금 보낸 pane — 응답의 "팀에 공유" 버튼 노출 여부에 씁니다.
 * @returns {Promise<{userMessage, aiMessage, evidence, hasAnswer}>}
 */
export async function askAgent(sessionId, content, scope) {
  if (USE_MOCK) {
    return {
      userMessage: { role: 'me', text: content },
      aiMessage: { role: 'ai', ...MOCK_AGENT_REPLY },
      evidence: [],
      hasAnswer: true,
    };
  }

  const res = await agentApi.sendChatMessage(sessionId, content);
  return {
    userMessage: toViewMessage(res.user_message, scope),
    aiMessage: toViewMessage(res.assistant_message, scope),
    evidence: toEvidence(res.assistant_message?.citations),
    hasAnswer: res.has_answer,
  };
}

/**
 * "다시 생성" — 같은 질문으로 답변을 새로 받아 이 메시지를 그 자리에서 교체합니다
 * (근거 부족 카드였어도 다시 시도할 수 있습니다).
 * @returns {Promise<{message: object, evidence: object[]}>} 교체된 답변(화면 shape)과 근거 원문
 */
export async function regenerateMessage(sessionId, messageId, scope) {
  const updated = await agentApi.regenerateChatMessage(sessionId, messageId);
  return { message: toViewMessage(updated, scope), evidence: toEvidence(updated.citations) };
}

/**
 * "삭제" — 이 질문/답변 쌍을 DB에서 완전히 지웁니다(정상 답변도 대상 — 위키 저장이나
 * 팀 공유로 이미 복사된 게 있다면 그건 별도 행이라 영향받지 않습니다).
 */
export async function deleteMessage(sessionId, messageId) {
  await agentApi.deleteChatMessage(sessionId, messageId);
}

/**
 * "팀에 공유" — 개인 세션의 답변(질문 쌍)을 팀 공유 세션으로 복사합니다.
 * @param {string} [targetSessionId] 지정하면 그 팀 세션으로, 생략하면 새 팀 세션을 만듭니다.
 * @returns {Promise<{message: object, targetSessionId: string}>} 복사된 메시지(화면 shape)와
 *   실제로 사용된(혹은 새로 만들어진) 팀 세션 id — 호출부가 그 세션으로 전환할 때 씁니다.
 */
export async function shareToTeam(sessionId, messageId, targetSessionId) {
  if (USE_MOCK) return null;
  const copied = await agentApi.shareMessageToTeam(sessionId, messageId, targetSessionId);
  return { message: toViewMessage(copied, 'team'), targetSessionId: copied.session_id };
}

/**
 * "위키에 저장" — 답변을 위키 문서로 저장합니다.
 * citation이 없는 답변(근거 부족 응답)이면 백엔드가 400을 던지므로, 호출부에서
 * ApiError를 잡아 "근거가 없어 저장할 수 없습니다" 같은 안내로 보여줘야 합니다.
 * @returns {Promise<{page_id: string, version_id: string, slug: string}>}
 */
export async function saveToWiki(sessionId, messageId) {
  if (USE_MOCK) return { page_id: 'mock-page', version_id: 'mock-version', slug: 'mock-slug' };
  return agentApi.saveMessageToWiki(sessionId, messageId);
}

/**
 * 보관 토글. 성공하면 갱신된 archivedAt(없으면 null)을 돌려준다.
 * @returns {Promise<string|null>}
 */
export async function toggleArchive(sessionId) {
  if (USE_MOCK) return null;
  const updated = await agentApi.archiveChatSession(sessionId);
  return updated.archived_at ?? null;
}

/** 소프트 삭제. */
export async function deleteConversation(sessionId) {
  if (USE_MOCK) return;
  await agentApi.deleteChatSession(sessionId);
}

/** 팀 세션 참여자 목록. */
export async function listParticipants(sessionId) {
  if (USE_MOCK) return [];
  return agentApi.fetchSessionParticipants(sessionId);
}

/** 참여자 추가. */
export async function addParticipant(sessionId, userId) {
  if (USE_MOCK) return null;
  return agentApi.addSessionParticipant(sessionId, userId);
}

/** 참여자 제거(본인 탈퇴 포함). */
export async function removeParticipant(sessionId, userId) {
  if (USE_MOCK) return;
  await agentApi.removeSessionParticipant(sessionId, userId);
}

/** "참여자 추가" 선택지용 워크스페이스 멤버 전체 목록. */
export async function listWorkspaceMembers() {
  if (USE_MOCK) return [];
  return agentApi.fetchWorkspaceMembers();
}
