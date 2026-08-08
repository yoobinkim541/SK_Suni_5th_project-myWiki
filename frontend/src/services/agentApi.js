// 에이전트 API 호출부.
// USE_MOCK=true면 data/mockWiki.js를 그대로 돌려주고, false면 api/agent.js를 호출합니다.
// 백엔드 응답 shape과 화면(AgentPage.jsx)이 기대하는 shape이 달라서 아래 어댑터로 변환합니다.

import * as agentApi from '../api/agent';
import { MOCK_AGENT_PANES, MOCK_AGENT_REPLY } from '../data/mockWiki';
import { formatDate, reliabilityLabel } from './wikiApi';

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

// citations[] → 화면 cites[{no, key, url}]
// 주의: 백엔드는 출처 종류(dart/etnews 등) 자체는 안 주기 때문에 key는 임의로
// 지어내지 않고 null로 둡니다(mock 전용 registry 조회용 — getSource(null)은 못 찾음).
// url은 백엔드가 document_versions -> documents(canonical_url) 조인으로 채워 주는
// source_url을 그대로 씁니다 — ChatMessage.jsx가 본문 [N] 각주를 이 url로 링크합니다.
function toCites(citations = []) {
  return citations.map((c, i) => ({
    no: c.citation_order ?? i + 1,
    key: null,
    url: c.source_url ?? null,
    documentVersionId: c.document_version_id,
  }));
}

// citations[] → 우측 "근거 원문" 카드
// list_message_citations가 wikiApi.js의 _enrich_sources와 같은 패턴으로 document_title/
// source_name/published_at/reliability_score를 채워 주므로, wikiApi.js의 toDoc()과 같은
// 포맷(YYYY.MM.DD · 신뢰도 라벨)으로 footer를 만든다. 문서를 못 찾은 근거만 null이 남는다.
function evidenceFoot(c) {
  const parts = [];
  const date = formatDate(c.published_at);
  if (date) parts.push(date);
  if (c.reliability_score != null) parts.push(`신뢰도 ${reliabilityLabel(c.reliability_score)}`);
  return parts.join(' · ') || '출처 정보 확인 중';
}

// document_version_id가 없으면 DB 문서(위키/원문)가 아니라 실시간 웹 검색 근거다
// (src/agent/core.py의 _web_search_answer가 source_url만 채우고 document_version_id는
// 항상 None으로 강제한다). sources 테이블에 연결된 매체 정보가 없어 source_name도
// 항상 null이라, "출처 확인 중"(문서인데 아직 못 채운 경우)과 헷갈리지 않게 구분한다.
function toEvidence(citations = []) {
  return citations.map((c, i) => {
    const isWeb = c.document_version_id == null;
    return {
      no: c.citation_order ?? i + 1,
      title: c.document_title || `근거 문서 #${c.citation_order ?? i + 1}`,
      sourceName: c.source_name ?? (isWeb ? '웹 검색' : null),
      url: c.source_url ?? null,
      excerpt: c.quoted_text ?? '',
      foot: evidenceFoot(c),
      documentVersionId: c.document_version_id,
      isWeb,
    };
  });
}

// askAgent/regenerateMessage 직후 사이드바 갱신 — 새 답변의 근거를 기존 목록에 이어붙인다
// (fetchConversation의 mergeConversationCitations와 같은 "대화 전체 누적" 원칙).
// documentVersionId로 중복을 제거하고 no는 합친 순서로 다시 매긴다 — 원래 no는 그
// 답변 하나 안에서만 유효한 번호라 그대로 이어붙이면 겹친다.
//
// 다시 생성(regenerate)으로 인용이 바뀐 경우, 그 메시지가 이전에 인용했던 문서를 이
// 목록에서 정확히 빼지는 못한다(어떤 근거가 어느 메시지 것인지까지는 추적하지 않음) —
// 근거가 사라지진 않으니 실사용에 문제는 없지만, 완벽히 맞추려면 대화 새로고침
// (fetchConversation)이 정본이다.
export function mergeEvidenceLists(existing = [], incoming = []) {
  const byDocumentVersionId = new Map();
  for (const e of existing) byDocumentVersionId.set(e.documentVersionId, e);
  for (const e of incoming) {
    if (!byDocumentVersionId.has(e.documentVersionId)) byDocumentVersionId.set(e.documentVersionId, e);
  }
  return Array.from(byDocumentVersionId.values()).map((e, i) => ({ ...e, no: i + 1 }));
}

// 근거 원문 컬럼 — 대화 전체에서 위키 근거로 답한 모든 assistant 메시지의 citations를
// document_version_id 기준으로 합쳐서 보여준다(먼저 나온 인용을 우선하고, 같은 문서를
// 여러 답변이 인용해도 한 번만 보인다). 이전에는 마지막 AI 응답의 citations만 써서,
// 대화가 길어지면 중간의 위키 근거 답변들이 사이드바에서 전부 빠지는 문제가 있었다.
//
// citation_order는 지운다 — 메시지별로 1부터 매겨진 번호라 그대로 합치면 서로 다른
// 답변의 citation_order가 겹친다(예: 두 답변 모두 citation_order=1). undefined로 두면
// toEvidence()의 `c.citation_order ?? i + 1`가 병합된 배열의 위치로 새로 번호를 매긴다.
// LLM 폴백 답변(is_llm_fallback)은 citations가 항상 빈 배열이라 자연히 제외된다.
function mergeConversationCitations(rawMessages = []) {
  const byDocumentVersionId = new Map();
  for (const msg of rawMessages) {
    if (msg.role !== 'assistant') continue;
    for (const c of msg.citations || []) {
      if (!byDocumentVersionId.has(c.document_version_id)) {
        byDocumentVersionId.set(c.document_version_id, { ...c, citation_order: undefined });
      }
    }
  }
  return Array.from(byDocumentVersionId.values());
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

  // LLM 폴백 응답 — 위키 근거를 못 찾아 일반 지식으로 답한 것(core.py의 is_llm_fallback).
  // has_answer=true라 NO_ANSWER_PREFIX 체크에는 안 걸리지만, 위키 citations가 있는
  // 정상 응답과는 절대 헷갈리면 안 되므로 이 분기를 그보다 먼저 둔다 — citations
  // 파싱 자체를 안 하고 llmFallback 플래그만 세워서, ChatMessage.jsx가 근거 태그
  // 대신 "LLM 답변" 배지를 그리게 한다.
  if (msg.is_llm_fallback) {
    return {
      role: 'ai',
      llmFallback: true,
      paragraphs: [[msg.content]],
      acts:
        scope === 'mine'
          ? ['팀에 공유', '관련 문서 찾아보기', '복사', '다시 생성', '삭제']
          : ['관련 문서 찾아보기', '복사', '다시 생성', '삭제'],
      _id: msg.id,
    };
  }

  // 근거 부족 응답 — 위키·원문까지만 시도한 1턴 결과다(백엔드가 allow_web_search 없이
  // 호출됐을 때의 기본 동작). "웹에서 찾아줘"를 누르면 regenerateMessage를
  // allowWebSearch=true로 다시 호출해 실시간 웹 검색까지 이어가는 2턴을 시도한다.
  if (typeof msg.content === 'string' && msg.content.startsWith(NO_ANSWER_PREFIX)) {
    return {
      role: 'ai',
      none: parseNoAnswer(msg.content),
      acts: ['웹에서 찾아줘', '수집 소스 추가', '관련 문서 찾아보기', '다시 생성', '삭제'],
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
        ? ['팀에 공유', '위키에 저장', '관련 문서 찾아보기', '복사', '다시 생성', '삭제']
        : ['위키에 저장', '관련 문서 찾아보기', '복사', '다시 생성', '삭제'],
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

  // 근거 원문 컬럼 — 대화 전체의 위키 근거 답변들을 합쳐서 보여줍니다(mergeConversationCitations 참고).
  const evidence = toEvidence(mergeConversationCitations(raw));

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
 * @param {boolean} [allowWebSearch] "웹에서 찾아줘" 버튼용 — true면 위키·원문 실패 후
 *   실시간 웹 검색(그리고 그것도 실패하면 일반 지식 답변)까지 자동으로 이어간다.
 * @returns {Promise<{message: object, evidence: object[]}>} 교체된 답변(화면 shape)과 근거 원문
 */
export async function regenerateMessage(sessionId, messageId, scope, allowWebSearch = false) {
  const updated = await agentApi.regenerateChatMessage(sessionId, messageId, allowWebSearch);
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
 * 대화 제목 직접 수정. 성공하면 갱신된 제목을 돌려준다.
 * @returns {Promise<string>}
 */
export async function renameConversation(sessionId, title) {
  if (USE_MOCK) return title;
  const updated = await agentApi.renameChatSession(sessionId, title);
  return updated.title;
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
