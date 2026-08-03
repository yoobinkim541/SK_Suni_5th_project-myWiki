// 에이전트 페이지 — PC/모바일 공용 (#v-agent)
//
// 시안 구조 그대로 "팀 공유 에이전트 / 내 에이전트"를 세그먼트(.ag-seg)로 나눕니다.
//  · 각 탭은 컨텍스트 배너(.ag-ctx) + 대화 목록(.ag-list) + 스레드(.thread)
//    + 입력창(.composer) + 근거 원문 컬럼(.col)으로 구성됩니다.
//  · 대화방(.ag-conv)을 누르면 스레드와 우측 근거 원문이 같이 바뀝니다.
//  · "+ 새 대화"를 누르면 빈 대화가 하나 생기고 바로 그 대화로 들어갑니다.
//  · 입력창에서 보낸 질문은 그 대화에만 쌓입니다(탭을 옮겨도 유지).
//
// 답변은 아직 백엔드가 없어 services/wikiApi.js의 고정 응답(MOCK_AGENT_REPLY)을 씁니다.

import { useState } from 'react';
import { MOCK_AGENT_PANES, MOCK_AGENT_REPLY } from '../data/mockWiki';
import { getSource } from '../services/wikiApi';
import ChatMessage from '../components/agent/ChatMessage';
import ChatComposer from '../components/agent/ChatComposer';

const PANE_KEYS = ['team', 'mine'];

export default function AgentPage() {
  const [panes, setPanes] = useState(MOCK_AGENT_PANES);
  const [activePane, setActivePane] = useState('team');
  const [currentIds, setCurrentIds] = useState({
    team: MOCK_AGENT_PANES.team.conversations[0].id,
    mine: MOCK_AGENT_PANES.mine.conversations[0].id,
  });

  const pane = panes[activePane];
  const current =
    pane.conversations.find((c) => c.id === currentIds[activePane]) || pane.conversations[0];

  function handleSend(text) {
    setPanes((prev) => ({
      ...prev,
      [activePane]: {
        ...prev[activePane],
        conversations: prev[activePane].conversations.map((c) =>
          c.id !== current.id
            ? c
            : {
                ...c,
                messages: [
                  ...c.messages,
                  { role: 'me', text, ...(activePane === 'team' ? { author: { initial: 'J', name: '김주현' } } : {}) },
                  { role: 'ai', ...MOCK_AGENT_REPLY },
                ],
              }
        ),
      },
    }));
  }

  function handleNewConversation() {
    const n = pane.conversations.length + 1;
    const id = `${activePane}-new-${n}`;
    setPanes((prev) => ({
      ...prev,
      [activePane]: {
        ...prev[activePane],
        conversations: [
          ...prev[activePane].conversations,
          { id, title: `새 대화 ${n}`, meta: '방금', messages: [], evidence: [] },
        ],
      },
    }));
    setCurrentIds((prev) => ({ ...prev, [activePane]: id }));
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
                <ChatMessage key={i} message={m} flag={pane.flag} flagPriv={pane.flagPriv} />
              ))
            )}
          </div>

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
            const src = getSource(e.key);
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
                <a className="lk" href={src.url} target="_blank" rel="noopener">
                  {isDoc ? 'DART 원문 열기 ↗' : '원문 열기 ↗'}
                </a>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
