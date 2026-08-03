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

// 백엔드 메시지 하나 → 화면 메시지 하나
function toViewMessage(msg) {
  const role = toViewRole(msg.role);

  if (role === 'me') {
    return { role: 'me', text: msg.content, _id: msg.id };
  }

  // 근거 부족 응답
  if (typeof msg.content === 'string' && msg.content.startsWith(NO_ANSWER_PREFIX)) {
    return {
      role: 'ai',
      none: parseNoAnswer(msg.content),
      acts: ['수집 소스 추가', '관련 문서 찾아보기'],
      _id: msg.id,
    };
  }

  // 정상 응답 — 백엔드 content는 평문 한 덩어리라 각주 번호를 문장에 끼워 넣을 수 없습니다.
  // paragraphs는 [[문자열]] 형태 하나로 두고, 근거는 cites/evidence로만 표시합니다.
  return {
    role: 'ai',
    paragraphs: [[msg.content]],
    cites: toCites(msg.citations),
    acts: ['위키에 저장', '복사', '다시 생성'],
    _id: msg.id,
  };
}

// 세션 하나 → 화면 대화 하나 (메시지는 아직 안 불러온 상태)
function toViewConversation(session) {
  return {
    id: session.id,
    title: session.title || '제목 없는 대화',
    meta: formatMeta(session.updated_at ?? session.created_at),
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
 * 백엔드에 세션 소유(팀 공유 vs 개인) 구분이 없어, 실제 세션은 전부 'mine'에 넣습니다.
 * 'team' pane은 백엔드가 소유 구분을 지원할 때까지 목업을 유지합니다.
 */
export async function fetchAgentPanes() {
  if (USE_MOCK) return MOCK_AGENT_PANES;

  // TODO: 백엔드에 세션 목록 조회 엔드포인트가 없습니다(생성/메시지만 있음).
  // 목록 API가 추가되면 아래 주석을 해제하고 목업 대체를 제거합니다.
  // const sessions = await agentApi.fetchChatSessions();
  // return {
  //   ...MOCK_AGENT_PANES,
  //   mine: { ...MOCK_AGENT_PANES.mine, conversations: sessions.map(toViewConversation) },
  // };

  return MOCK_AGENT_PANES;
}

/** 대화방 하나의 메시지 + 근거 원문을 불러옵니다. */
export async function fetchConversation(sessionId) {
  if (USE_MOCK) {
    return { messages: [], evidence: [] };
  }

  const raw = await agentApi.fetchChatMessages(sessionId);
  const messages = raw.map(toViewMessage);

  // 근거 원문 컬럼은 마지막 AI 응답의 citations를 씁니다.
  const lastAi = [...raw].reverse().find((m) => m.role === 'assistant');
  const evidence = toEvidence(lastAi?.citations);

  return { messages, evidence };
}

/** 새 대화 생성. */
export async function createConversation(title) {
  if (USE_MOCK) {
    return {
      id: `local-${Date.now()}`,
      title: title || '새 대화',
      meta: '오늘',
      messages: [],
      evidence: [],
    };
  }

  const session = await agentApi.createChatSession(title || '새 대화');
  return toViewConversation(session);
}

/**
 * 질문 전송. 사용자 메시지와 AI 응답을 화면 shape으로 함께 돌려줍니다.
 * @returns {Promise<{userMessage, aiMessage, evidence, hasAnswer}>}
 */
export async function askAgent(sessionId, content) {
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
    userMessage: toViewMessage(res.user_message),
    aiMessage: toViewMessage(res.assistant_message),
    evidence: toEvidence(res.assistant_message?.citations),
    hasAnswer: res.has_answer,
  };
}