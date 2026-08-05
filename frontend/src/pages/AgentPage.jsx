// 에이전트 페이지 — PC/모바일 공용 (#v-agent)
//
// 시안 구조 그대로 "팀 공유 에이전트 / 내 에이전트"를 세그먼트(.ag-seg)로 나눕니다.
//  · 각 탭은 컨텍스트 배너(.ag-ctx) + 대화 목록(.ag-list) + 스레드(.thread)
//    + 입력창(.composer) + 근거 원문 컬럼(.col)으로 구성됩니다.
//  · 대화방(.ag-conv)을 누르면 스레드와 우측 근거 원문이 같이 바뀝니다.
//  · "+ 새 대화"를 누르면 빈 대화가 하나 생기고 바로 그 대화로 들어갑니다.
//  · 입력창에서 보낸 질문은 그 대화에만 쌓입니다(탭을 옮겨도 유지).
//
// 데이터는 services/agentApi.js를 통해서만 가져옵니다.
// VITE_USE_MOCK=true면 목업, false면 실제 백엔드(api/agent.js)를 호출합니다.
//
// team 세션은 여러 개일 수 있습니다(공유할 때마다 고르거나 새로 만듦) — "팀에 공유"는
// ShareToTeamModal로 대상을 고르게 하고, 성공하면 팀 탭으로 전환해 그 세션을 보여줍니다.

import { useEffect, useRef, useState } from 'react';
import {
  fetchAgentPanes,
  fetchConversation,
  createConversation,
  askAgent,
  regenerateMessage,
  deleteMessage,
  saveToWiki,
  shareToTeam,
  toggleArchive,
  renameConversation,
  deleteConversation,
  listParticipants,
  addParticipant,
  removeParticipant,
  listWorkspaceMembers,
  mergeEvidenceLists,
} from '../services/agentApi';
import ChatMessage from '../components/agent/ChatMessage';
import ChatComposer from '../components/agent/ChatComposer';
import ShareToTeamModal from '../components/agent/ShareToTeamModal';
import ParticipantsModal from '../components/agent/ParticipantsModal';
import mascotImg from '../assets/mascot.png';

const PANE_KEYS = ['team', 'mine'];
const PANE_VISIBILITY = { team: 'team', mine: 'private' };

// 근거 원문 컬럼(.col)에 두는 마스코트 — 근거가 0개면 목록이 비어있는 자리에,
// 1개 이상이면 .ev 카드 목록 아래에 온다(JSX 흐름상 배치라 근거가 늘어나면
// 같이 밀려 내려간다 — position: absolute로 겹치게 띄우지 않음).
function MascotFloat() {
  return (
    <div className="mascot-float">
      <img src={mascotImg} alt="마이위키 마스코트" />
    </div>
  );
}

export default function AgentPage({ profile }) {
  const [panes, setPanes] = useState(null);
  const [activePane, setActivePane] = useState('team');
  const [currentIds, setCurrentIds] = useState({ team: null, mine: null });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  // 메시지별 "위키에 저장"/"팀에 공유" 진행 상태 — { [messageId]: { wiki, team } }
  const [actionState, setActionState] = useState({});
  const [shareTarget, setShareTarget] = useState(null); // 공유 모달 대상 메시지
  const [sharing, setSharing] = useState(false);
  const [openMenuId, setOpenMenuId] = useState(null); // 대화 목록의 "⋯" 드롭다운이 열려 있는 대화 id
  const menuRef = useRef(null);
  const [participantsSessionId, setParticipantsSessionId] = useState(null); // 참여자 모달 대상 대화 id
  const [participants, setParticipants] = useState(null);
  const [workspaceMembers, setWorkspaceMembers] = useState(null);
  const [participantsLoading, setParticipantsLoading] = useState(false);
  const [participantsError, setParticipantsError] = useState(null);
  const [participantsBusyUserId, setParticipantsBusyUserId] = useState(null);
  // 팀 대화 하단 힌트("○○님 외 N명이 열람·이어서 질문할 수 있습니다")에 쓸 실제
  // 참여자 목록 — chat_session_participants는 대화(session)마다 다를 수 있어
  // team pane에서 보고 있는 대화가 바뀔 때마다 다시 불러옵니다.
  const [currentTeamParticipants, setCurrentTeamParticipants] = useState(null);

  // 참여자 모달을 열면 참여자 목록 + 워크스페이스 멤버 전체 목록을 같이 불러옵니다.
  useEffect(() => {
    if (participantsSessionId === null) return;
    let alive = true;
    setParticipantsLoading(true);
    setParticipantsError(null);
    Promise.all([listParticipants(participantsSessionId), listWorkspaceMembers()])
      .then(([p, m]) => {
        if (!alive) return;
        setParticipants(p);
        setWorkspaceMembers(m);
      })
      .catch((e) => alive && setParticipantsError(e.message || '참여자 정보를 불러오지 못했습니다.'))
      .finally(() => alive && setParticipantsLoading(false));
    return () => { alive = false; };
  }, [participantsSessionId]);

  // 드롭다운이 열려 있는 동안, 그 바깥을 클릭하면 닫습니다.
  useEffect(() => {
    if (openMenuId === null) return;
    function handleOutsideClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [openMenuId]);

  const authorName = profile?.user_metadata?.full_name || profile?.email || '나';
  const authorInitial = authorName.charAt(0).toUpperCase();

  // 최초 진입 시 대화 목록을 불러옵니다.
  useEffect(() => {
    let alive = true;
    fetchAgentPanes()
      .then((data) => {
        if (!alive) return;
        setPanes(data);
        setCurrentIds({
          team: data.team.conversations[0]?.id ?? null,
          mine: data.mine.conversations[0]?.id ?? null,
        });
      })
      .catch((e) => alive && setError(e.message || '대화 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, []);

  const pane = panes?.[activePane];
  const current =
    pane?.conversations.find((c) => c.id === currentIds[activePane]) ||
    pane?.conversations[0] ||
    null;

  // 대화방을 바꿀 때 아직 메시지를 안 불러왔으면 여기서 채웁니다.
  useEffect(() => {
    if (!current || current._loaded === undefined || current._loaded) return;
    let alive = true;
    fetchConversation(current.id, activePane)
      .then(({ messages, evidence }) => {
        if (!alive) return;
        updateConversation(activePane, current.id, (c) => ({ ...c, messages, evidence, _loaded: true }));
      })
      .catch((e) => alive && setError(e.message || '대화를 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [current?.id]);

  // team pane에서 보고 있는 대화의 실제 참여자를 불러옵니다(하단 힌트용).
  // mine pane이거나 대화가 없으면 비웁니다.
  useEffect(() => {
    if (activePane !== 'team' || !current) {
      setCurrentTeamParticipants(null);
      return;
    }
    let alive = true;
    setCurrentTeamParticipants(null);
    listParticipants(current.id)
      .then((p) => alive && setCurrentTeamParticipants(p))
      .catch(() => alive && setCurrentTeamParticipants([]));
    return () => { alive = false; };
  }, [activePane, current?.id]);

  // "○○님, △△님 외 N명이 열람·이어서 질문할 수 있습니다" — chat_session_participants
  // 조회 결과 기준으로 인원수·이름을 만든다. 목업(mockWiki.js)의 "Team 5 멤버 4명"은
  // 모든 대화에서 항상 똑같이 뜨는 하드코딩이라 대화별 실제 참여자로 대체한다.
  function participantsHint(loginUserId, participants) {
    if (participants === null) return '참여자 정보를 불러오는 중입니다';
    if (participants.length === 0) return '아직 참여자가 없습니다';
    const names = participants.map((p) =>
      p.user_id === loginUserId ? '나' : (p.display_name || '이름 없음')
    );
    const shown = names.slice(0, 3).join(', ');
    const rest = names.length > 3 ? ` 외 ${names.length - 3}명` : '';
    return `${shown}${rest} · 총 ${names.length}명이 열람·이어서 질문할 수 있습니다`;
  }

  // 특정 pane의 대화 하나만 바꾸는 공용 헬퍼. pane을 인자로 받아서, 방금 전환한
  // team pane처럼 activePane과 다른 pane도 갱신할 수 있게 합니다(공유 직후 등).
  function updateConversation(paneKey, id, fn) {
    setPanes((prev) => ({
      ...prev,
      [paneKey]: {
        ...prev[paneKey],
        conversations: prev[paneKey].conversations.map((c) => (c.id !== id ? c : fn(c))),
      },
    }));
  }

  async function handleSend(text) {
    if (!current || sending) return;
    setSending(true);
    setError(null);

    // 보낸 질문을 먼저 화면에 올려 응답을 기다리는 동안 비어 보이지 않게 합니다.
    const optimistic = {
      role: 'me',
      text,
      ...(activePane === 'team' ? { author: { initial: authorInitial, name: authorName } } : {}),
    };
    updateConversation(activePane, current.id, (c) => ({ ...c, messages: [...c.messages, optimistic] }));

    try {
      const { aiMessage, evidence } = await askAgent(current.id, text, activePane);
      updateConversation(activePane, current.id, (c) => ({
        ...c,
        messages: [...c.messages, aiMessage],
        evidence: mergeEvidenceLists(c.evidence, evidence),
      }));
    } catch (e) {
      setError(e.message || '답변을 가져오지 못했습니다.');
      // 실패한 질문은 되돌립니다.
      updateConversation(activePane, current.id, (c) => ({ ...c, messages: c.messages.slice(0, -1) }));
    } finally {
      setSending(false);
    }
  }

  async function handleNewConversation() {
    const n = pane.conversations.length + 1;
    try {
      const conv = await createConversation(`새 대화 ${n}`, PANE_VISIBILITY[activePane]);
      setPanes((prev) => ({
        ...prev,
        [activePane]: {
          ...prev[activePane],
          conversations: [...prev[activePane].conversations, { ...conv, _loaded: true }],
        },
      }));
      setCurrentIds((prev) => ({ ...prev, [activePane]: conv.id }));
    } catch (e) {
      setError(e.message || '새 대화를 만들지 못했습니다.');
    }
  }

  function setMessageAction(messageId, kind, state) {
    setActionState((prev) => ({
      ...prev,
      [messageId]: { ...prev[messageId], [kind]: state },
    }));
  }

  async function handleSaveToWiki(message) {
    const messageId = message._id;
    if (!messageId || !current) return;
    setMessageAction(messageId, 'wiki', { status: 'loading' });
    try {
      await saveToWiki(current.id, messageId);
      setMessageAction(messageId, 'wiki', { status: 'done' });
    } catch (e) {
      const errMessage = e.status === 400 ? '근거가 없어 저장할 수 없습니다' : (e.message || '저장하지 못했습니다.');
      setMessageAction(messageId, 'wiki', { status: 'error', message: errMessage });
    }
  }

  // "팀에 공유" 클릭 — 바로 공유하지 않고 모달을 열어 대상 팀 세션을 고르게 합니다.
  function handleOpenShareModal(message) {
    setShareTarget(message);
  }

  async function handleShareSelect(targetSessionId) {
    const message = shareTarget;
    const messageId = message?._id;
    if (!messageId || !current) return;
    setSharing(true);
    setMessageAction(messageId, 'team', { status: 'loading' });
    try {
      const result = await shareToTeam(current.id, messageId, targetSessionId);
      setMessageAction(messageId, 'team', { status: 'done' });
      setShareTarget(null);

      // 팀 pane 목록을 새로고침해서 방금 공유된(혹은 새로 만들어진) 대화가 보이게 하고,
      // 그 세션으로 바로 전환해서 공유한 내용을 확인할 수 있게 합니다.
      const fresh = await fetchAgentPanes();
      setPanes((prev) => ({ ...prev, team: fresh.team }));
      setActivePane('team');
      setCurrentIds((prev) => ({ ...prev, team: result.targetSessionId }));
    } catch (e) {
      setMessageAction(messageId, 'team', { status: 'error', message: e.message || '공유하지 못했습니다.' });
    } finally {
      setSharing(false);
    }
  }

  async function handleRenameConversation(conversationId) {
    setOpenMenuId(null);
    const target = pane?.conversations.find((c) => c.id === conversationId);
    const next = window.prompt('새 대화 제목을 입력하세요.', target?.title || '');
    if (next === null) return; // 취소
    const trimmed = next.trim();
    if (!trimmed || trimmed === target?.title) return;

    try {
      const title = await renameConversation(conversationId, trimmed);
      updateConversation(activePane, conversationId, (c) => ({ ...c, title }));
    } catch (e) {
      setError(e.message || '제목을 바꾸지 못했습니다.');
    }
  }

  async function handleArchiveToggle(conversationId) {
    setOpenMenuId(null);
    try {
      const archivedAt = await toggleArchive(conversationId);
      updateConversation(activePane, conversationId, (c) => ({ ...c, archivedAt }));
    } catch (e) {
      setError(e.message || '보관 상태를 바꾸지 못했습니다.');
    }
  }

  async function handleDeleteConversation(conversationId) {
    setOpenMenuId(null);
    const target = pane?.conversations.find((c) => c.id === conversationId);
    const label = target?.title || '이 대화';
    if (!window.confirm(`"${label}"를 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return;

    try {
      await deleteConversation(conversationId);
      // 삭제된 항목을 목록에서 지운다 — 이게 currentIds가 가리키던 항목이었다면,
      // current 계산의 기존 fallback(conversations[0])이 알아서 다음 대화로 넘어간다.
      setPanes((prev) => ({
        ...prev,
        [activePane]: {
          ...prev[activePane],
          conversations: prev[activePane].conversations.filter((c) => c.id !== conversationId),
        },
      }));
    } catch (e) {
      setError(e.message || '삭제하지 못했습니다.');
    }
  }

  function handleOpenParticipants(conversationId) {
    setOpenMenuId(null);
    setParticipants(null);
    setWorkspaceMembers(null);
    setParticipantsSessionId(conversationId);
  }

  function closeParticipantsModal() {
    setParticipantsSessionId(null);
  }

  async function handleAddParticipant(userId) {
    if (!participantsSessionId) return;
    setParticipantsBusyUserId(userId);
    setParticipantsError(null);
    try {
      const added = await addParticipant(participantsSessionId, userId);
      setParticipants((prev) => [...(prev ?? []), added]);
    } catch (e) {
      setParticipantsError(e.message || '참여자를 추가하지 못했습니다.');
    } finally {
      setParticipantsBusyUserId(null);
    }
  }

  async function handleRemoveParticipant(userId) {
    if (!participantsSessionId) return;
    setParticipantsBusyUserId(userId);
    setParticipantsError(null);
    try {
      await removeParticipant(participantsSessionId, userId);
      setParticipants((prev) => (prev ?? []).filter((p) => p.user_id !== userId));

      // 본인을 뺀 거면(자진 탈퇴) 백엔드에서 이 세션은 이제 조회조차 안 된다 —
      // 팀 목록에서 통째로 지워서 프론트도 바로 접근 불가 상태로 맞춘다.
      if (userId === profile?.id) {
        const wasViewing = participantsSessionId === current?.id;
        const removedId = participantsSessionId;
        setPanes((prev) => ({
          ...prev,
          team: {
            ...prev.team,
            conversations: prev.team.conversations.filter((c) => c.id !== removedId),
          },
        }));
        setParticipantsSessionId(null);
        if (wasViewing) {
          setError('더 이상 이 대화에 참여하고 있지 않아 접근할 수 없습니다.');
        }
      }
    } catch (e) {
      setParticipantsError(e.message || '참여자를 빼지 못했습니다.');
    } finally {
      setParticipantsBusyUserId(null);
    }
  }

  // message.paragraphs는 [[문자열|각주번호, ...], ...] 형태다 — 숫자(각주)는 빼고
  // 문장만 이어 붙인다.
  function messageText(message) {
    return (message.paragraphs || [])
      .map((parts) => parts.filter((p) => typeof p === 'string').join(''))
      .join('\n');
  }

  async function handleCopy(message) {
    const messageId = message._id;
    if (!messageId) return;
    setMessageAction(messageId, 'copy', { status: 'loading' });
    try {
      await navigator.clipboard.writeText(messageText(message));
      setMessageAction(messageId, 'copy', { status: 'done' });
      setTimeout(() => setMessageAction(messageId, 'copy', { status: 'idle' }), 1500);
    } catch (e) {
      setMessageAction(messageId, 'copy', { status: 'error', message: '복사하지 못했습니다.' });
    }
  }

  // "다시 생성" — 백엔드가 같은 질문으로 Agent를 다시 불러 이 답변 행을 그 자리에서
  // 교체한다(질문 자체는 백엔드가 get_preceding_user_message로 찾으므로 프론트는
  // messageId만 넘기면 된다). 근거 부족("답을 찾지 못했습니다") 카드도 대상이 될 수 있다.
  async function handleRegenerate(message) {
    const messageId = message._id;
    if (!messageId || !current) return;
    setMessageAction(messageId, 'regen', { status: 'loading' });
    try {
      const { message: updated, evidence } = await regenerateMessage(current.id, messageId, activePane);
      updateConversation(activePane, current.id, (c) => ({
        ...c,
        messages: c.messages.map((m) => (m._id === messageId ? updated : m)),
        evidence: mergeEvidenceLists(c.evidence, evidence),
      }));
      setMessageAction(messageId, 'regen', { status: 'done' });
      setTimeout(() => setMessageAction(messageId, 'regen', { status: 'idle' }), 1500);
    } catch (e) {
      setMessageAction(messageId, 'regen', { status: 'error', message: e.message || '다시 생성하지 못했습니다.' });
    }
  }

  // "삭제" — 정상 답변/근거 부족 답변 모두 대상으로, 이 답변과 바로 앞 질문을
  // 화면·DB에서 함께 지운다(하드 삭제, 되돌릴 수 없음).
  async function handleDeleteMessage(message) {
    const messageId = message._id;
    if (!messageId || !current) return;
    if (!window.confirm('이 질문과 답변을 완전히 삭제할까요? 이 작업은 되돌릴 수 없습니다.')) return;

    setMessageAction(messageId, 'del', { status: 'loading' });
    try {
      await deleteMessage(current.id, messageId);
      const idx = current.messages.findIndex((m) => m._id === messageId);
      let questionId = null;
      for (let i = idx - 1; i >= 0; i -= 1) {
        if (current.messages[i].role === 'me') {
          questionId = current.messages[i]._id;
          break;
        }
      }
      updateConversation(activePane, current.id, (c) => ({
        ...c,
        messages: c.messages.filter((m) => m._id !== messageId && m._id !== questionId),
      }));
    } catch (e) {
      setMessageAction(messageId, 'del', { status: 'error', message: e.message || '삭제하지 못했습니다.' });
    }
  }

  // "관련 문서 찾아보기" — 백엔드 API 없이, 이 답변 바로 앞 질문 텍스트로 구글
  // 검색 결과를 새 탭으로 연다(근거 부족 카드에서만 노출되는 액션).
  function handleSearchRelatedDocs(message) {
    const messageId = message._id;
    if (!messageId || !current) return;
    const idx = current.messages.findIndex((m) => m._id === messageId);
    let question = null;
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (current.messages[i].role === 'me') {
        question = current.messages[i].text;
        break;
      }
    }
    if (!question) return;
    window.open(`https://www.google.com/search?q=${encodeURIComponent(question)}`, '_blank', 'noopener,noreferrer');
  }

  function handleMessageAction(label, message) {
    if (label === '위키에 저장') handleSaveToWiki(message);
    if (label === '팀에 공유') handleOpenShareModal(message);
    if (label === '복사') handleCopy(message);
    if (label === '다시 생성') handleRegenerate(message);
    if (label === '삭제') handleDeleteMessage(message);
    if (label === '관련 문서 찾아보기') handleSearchRelatedDocs(message);
  }

  if (error && !panes) {
    return (
      <section className="view on" id="v-agent">
        <div className="empty-conv">{error}</div>
      </section>
    );
  }

  if (!panes) {
    return (
      <section className="view on" id="v-agent">
        <div className="empty-conv">불러오는 중…</div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-agent">
      <div className="ph">
        <h2>에이전트</h2>
        <span className="dt">축적된 위키 문서만 근거로 사용</span>
        <span className="st">참조 범위 <b>위키 124문서</b></span>
      </div>

      <div className="sp-seg ag-seg" role="tablist" aria-label="에이전트 구분">
        {PANE_KEYS.map((key) => (
          <button
            key={key}
            className={activePane === key ? 'on' : ''}
            role="tab"
            aria-selected={activePane === key}
            onClick={() => setActivePane(key)}
          >
            {panes[key].label}<span className="c">{panes[key].conversations.length}</span>
          </button>
        ))}
      </div>

      <div className={`chat ag-pane ${pane.key} on`}>
        <div>
          {/* 컨텍스트 배너 — 팀은 참여 멤버, 개인은 "비공개" 배지.
              "내 에이전트" 제목은 MOCK_AGENT_PANES.mine.ctx.title(하드코딩된 이름)
              대신 로그인한 실제 사용자 이름(authorName)을 쓴다 — fetchAgentPanes()가
              conversations만 실데이터로 바꾸고 ctx는 목업을 그대로 넘겨서 생긴 문제였다. */}
          <div className={`ag-ctx ${pane.key}`}>
            <span className="ic">{pane.ctx.badge}</span>
            <div className="tx">
              <b>{pane.key === 'mine' ? `${authorName} · 개인 에이전트` : pane.ctx.title}</b>
              <span>{pane.ctx.desc}</span>
            </div>
            {pane.ctx.avatars ? (
              <span className="avs" aria-label="참여 멤버">
                {pane.ctx.avatars.map((a) => <i key={a}>{a}</i>)}
                {pane.ctx.more && <i className="more">{pane.ctx.more}</i>}
              </span>
            ) : (
              <span className="priv">{pane.ctx.priv}</span>
            )}
          </div>

          {/* 대화 목록 */}
          <div className="ag-list">
            <span className="lb">{pane.listLabel}</span>
            {pane.conversations.map((c) => (
              <div
                className="ag-conv-row"
                key={c.id}
                ref={c.id === openMenuId ? menuRef : null}
              >
                <button
                  className={`ag-conv${c.id === current?.id ? ' on' : ''}`}
                  onClick={() => setCurrentIds((prev) => ({ ...prev, [activePane]: c.id }))}
                >
                  {c.title}{c.archivedAt && <span className="d"> · 보관됨</span>}<span className="d">{c.meta}</span>
                </button>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={`${c.title} 옵션`}
                  aria-haspopup="true"
                  aria-expanded={c.id === openMenuId}
                  className={`ag-conv-menu-btn${c.id === openMenuId ? ' open' : ''}`}
                  onClick={(e) => { e.stopPropagation(); setOpenMenuId((prev) => (prev === c.id ? null : c.id)); }}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter') return;
                    e.stopPropagation();
                    setOpenMenuId((prev) => (prev === c.id ? null : c.id));
                  }}
                >
                  ⋯
                </span>
                {c.id === openMenuId && (
                  <div className="ag-conv-menu" role="menu">
                    <span
                      role="menuitem"
                      tabIndex={0}
                      className="ag-conv-menu-item"
                      onClick={() => handleRenameConversation(c.id)}
                      onKeyDown={(e) => e.key === 'Enter' && handleRenameConversation(c.id)}
                    >
                      이름 변경
                    </span>
                    <span
                      role="menuitem"
                      tabIndex={0}
                      className="ag-conv-menu-item"
                      onClick={() => handleArchiveToggle(c.id)}
                      onKeyDown={(e) => e.key === 'Enter' && handleArchiveToggle(c.id)}
                    >
                      {c.archivedAt ? '보관 해제' : '보관'}
                    </span>
                    {activePane === 'team' && (
                      <span
                        role="menuitem"
                        tabIndex={0}
                        className="ag-conv-menu-item"
                        onClick={() => handleOpenParticipants(c.id)}
                        onKeyDown={(e) => e.key === 'Enter' && handleOpenParticipants(c.id)}
                      >
                        참여자 관리
                      </span>
                    )}
                    <span
                      role="menuitem"
                      tabIndex={0}
                      className="ag-conv-menu-item danger"
                      onClick={() => handleDeleteConversation(c.id)}
                      onKeyDown={(e) => e.key === 'Enter' && handleDeleteConversation(c.id)}
                    >
                      삭제
                    </span>
                  </div>
                )}
              </div>
            ))}
            <button className="ag-conv new" onClick={handleNewConversation}>
              {pane.newLabel}
            </button>
          </div>

          {/* 스레드 — 이 pane에 대화가 하나도 없을 수 있습니다(특히 아직 아무도 공유
              안 한 워크스페이스의 team pane). current가 없으면 빈 상태를 보여줍니다. */}
          {!current ? (
            <div className="empty-conv">
              아직 대화가 없습니다. "{pane.newLabel}"를 눌러 시작하세요.
            </div>
          ) : (
            <div className="thread">
              {current.messages.length === 0 ? (
                <div className="empty-conv">
                  「{current.title}」 대화입니다. 아래 입력창에 질문을 입력하면 위키에 축적된 문서만 근거로 답변합니다.
                </div>
              ) : (
                current.messages.map((m, i) => (
                  <ChatMessage
                    key={m._id ?? i}
                    message={m}
                    flag={pane.flag}
                    flagPriv={pane.flagPriv}
                    onAction={handleMessageAction}
                    actionState={m._id ? actionState[m._id] : undefined}
                  />
                ))
              )}
              {sending && <div className="empty-conv">근거를 확인하는 중…</div>}
            </div>
          )}

          {error && <div className="empty-conv">{error}</div>}

          {current && (
            <ChatComposer
              placeholder={pane.placeholder}
              ariaLabel={pane.inputLabel}
              onSend={handleSend}
            />
          )}

          <div className="hint">
            {(pane.key === 'team'
              ? [pane.hints[0], participantsHint(profile?.id, currentTeamParticipants)]
              : pane.hints
            ).map((h, i) => <span key={i}>{h}</span>)}
          </div>
        </div>

        {/* 근거 원문 */}
        <div className="col">
          <h5>근거 원문<span className="c">{current?.evidence.length ?? 0}</span></h5>

          {(current?.evidence ?? []).length === 0 && <MascotFloat />}

          {(current?.evidence ?? []).map((e) => {
            // e.sourceName이 null일 수 있습니다(문서에 매체 정보가 연결 안 된 경우).
            const sourceName = e.sourceName || '출처 확인 중';
            const isDoc = sourceName.includes('공시') || sourceName.includes('IR');
            return (
              <div className="ev" key={e.no}>
                <div className="t">
                  <span className="no">{e.no}</span>
                  <span className={`src${isDoc ? ' doc' : ''}`}>{sourceName}</span>
                </div>
                <h6>{e.title}</h6>
                <div className="x">{e.excerpt}</div>
                <div className="f">{e.foot}</div>
                {e.url && (
                  <a className="lk" href={e.url} target="_blank" rel="noopener">
                    {isDoc ? 'DART 원문 열기 ↗' : '원문 열기 ↗'}
                  </a>
                )}
              </div>
            );
          })}

          {(current?.evidence ?? []).length > 0 && <MascotFloat />}
        </div>
      </div>

      <ShareToTeamModal
        open={shareTarget !== null}
        teamConversations={panes.team.conversations}
        sharing={sharing}
        onSelect={handleShareSelect}
        onClose={() => setShareTarget(null)}
      />

      <ParticipantsModal
        open={participantsSessionId !== null}
        participants={participants ?? []}
        workspaceMembers={workspaceMembers ?? []}
        loading={participantsLoading}
        error={participantsError}
        busyUserId={participantsBusyUserId}
        onAdd={handleAddParticipant}
        onRemove={handleRemoveParticipant}
        onClose={closeParticipantsModal}
      />
    </section>
  );
}
