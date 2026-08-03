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

import { useEffect, useState } from 'react';
import { getSource } from '../services/wikiApi';
import {
  fetchAgentPanes,
  fetchConversation,
  createConversation,
  askAgent,
} from '../services/agentApi';
import ChatMessage from '../components/agent/ChatMessage';
import ChatComposer from '../components/agent/ChatComposer';

const PANE_KEYS = ['team', 'mine'];

// 출처 key가 없을 때 쓰는 기본값.
// 백엔드 citations에는 document_version_id만 있고 출처 종류(공시/뉴스)가 없습니다.
// 임의로 지어내면 잘못된 근거를 표시하게 되므로, 확인 불가임을 그대로 드러냅니다.
const UNKNOWN_SOURCE = { name: '출처 확인 중', url: null, title: '출처 정보 없음' };

export default function AgentPage() {
  const [panes, setPanes] = useState(null);
  const [activePane, setActivePane] = useState('team');
  const [currentIds, setCurrentIds] = useState({ team: null, mine: null });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

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
    fetchConversation(current.id)
      .then(({ messages, evidence }) => {
        if (!alive) return;
        updateConversation(current.id, (c) => ({ ...c, messages, evidence, _loaded: true }));
      })
      .catch((e) => alive && setError(e.message || '대화를 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [current?.id]);

  // 현재 pane의 대화 하나만 바꾸는 공용 헬퍼.
  function updateConversation(id, fn) {
    setPanes((prev) => ({
      ...prev,
      [activePane]: {
        ...prev[activePane],
        conversations: prev[activePane].conversations.map((c) => (c.id !== id ? c : fn(c))),
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
      ...(activePane === 'team' ? { author: { initial: 'J', name: '김주현' } } : {}),
    };
    updateConversation(current.id, (c) => ({ ...c, messages: [...c.messages, optimistic] }));

    try {
      const { aiMessage, evidence } = await askAgent(current.id, text);
      updateConversation(current.id, (c) => ({
        ...c,
        messages: [...c.messages, aiMessage],
        evidence: evidence.length ? evidence : c.evidence,
      }));
    } catch (e) {
      setError(e.message || '답변을 가져오지 못했습니다.');
      // 실패한 질문은 되돌립니다.
      updateConversation(current.id, (c) => ({ ...c, messages: c.messages.slice(0, -1) }));
    } finally {
      setSending(false);
    }
  }

  async function handleNewConversation() {
    const n = pane.conversations.length + 1;
    try {
      const conv = await createConversation(`새 대화 ${n}`);
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

  if (error && !panes) {
    return (
      <section className="view on" id="v-agent">
        <div className="empty-conv">{error}</div>
      </section>
    );
  }

  if (!panes || !current) {
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
          {/* 컨텍스트 배너 — 팀은 참여 멤버, 개인은 "비공개" 배지 */}
          <div className={`ag-ctx ${pane.key}`}>
            <span className="ic">{pane.ctx.badge}</span>
            <div className="tx">
              <b>{pane.ctx.title}</b>
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
              <button
                key={c.id}
                className={`ag-conv${c.id === current.id ? ' on' : ''}`}
                onClick={() => setCurrentIds((prev) => ({ ...prev, [activePane]: c.id }))}
              >
                {c.title}<span className="d">{c.meta}</span>
              </button>
            ))}
            <button className="ag-conv new" onClick={handleNewConversation}>
              {pane.newLabel}
            </button>
          </div>

          {/* 스레드 */}
          <div className="thread">
            {current.messages.length === 0 ? (
              <div className="empty-conv">
                「{current.title}」 대화입니다. 아래 입력창에 질문을 입력하면 위키에 축적된 문서만 근거로 답변합니다.
              </div>
            ) : (
              current.messages.map((m, i) => (
                <ChatMessage key={m._id ?? i} message={m} flag={pane.flag} flagPriv={pane.flagPriv} />
              ))
            )}
            {sending && <div className="empty-conv">근거를 확인하는 중…</div>}
          </div>

          {error && <div className="empty-conv">{error}</div>}

          <ChatComposer
            placeholder={pane.placeholder}
            ariaLabel={pane.inputLabel}
            onSend={handleSend}
          />

          <div className="hint">
            {pane.hints.map((h) => <span key={h}>{h}</span>)}
          </div>
        </div>

        {/* 근거 원문 */}
        <div className="col">
          <h5>근거 원문<span className="c">{current.evidence.length}</span></h5>
          {current.evidence.map((e) => {
            // e.key가 null일 수 있습니다(백엔드가 출처 종류를 주지 않는 경우).
            const src = (e.key && getSource(e.key)) || UNKNOWN_SOURCE;
            const isDoc = src.name.includes('공시') || src.name.includes('IR');
            return (
              <div className="ev" key={e.no}>
                <div className="t">
                  <span className="no">{e.no}</span>
                  <span className={`src${isDoc ? ' doc' : ''}`}>{src.name}</span>
                </div>
                <h6>{e.title}</h6>
                <div className="x">{e.excerpt}</div>
                <div className="f">{e.foot}</div>
                {src.url && (
                  <a className="lk" href={src.url} target="_blank" rel="noopener">
                    {isDoc ? 'DART 원문 열기 ↗' : '원문 열기 ↗'}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}