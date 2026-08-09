// 에이전트 전용 — 대화 한 턴(.turn)
// 사용자 메시지(.turn.me)와 에이전트 답변(.turn.ai)을 같은 컴포넌트에서 처리합니다.
//
// 팀 공유 대화에서는 사용자 메시지 위에 작성자(.au)가, 답변 헤더에는
// "팀 공유 / 개인" 배지(.who .fl)가 붙습니다 — 시안과 동일합니다.
// 답변 문장의 근거 번호와 하단 근거 칩은 CitationTag가 그립니다.
//
// acts는 모두 onAction(label, message)를 그대로 호출하고(실제 처리는 AgentPage.jsx가 함),
// actionState(AgentPage.jsx가 메시지별로 들고 있는 진행 상태)에 맞춰 라벨을 바꿉니다.
// "복사"는 백엔드 없이 프론트에서만 처리되고, "다시 생성"은 기존 askAgent를 재호출합니다.
//
// 실제 백엔드 답변은 paragraphs가 항상 [[문자열]] 하나(agentApi.js toViewMessage 참고)라
// 그 경우만 react-markdown으로 렌더링해서 **bold**/목록 같은 마크다운이 그대로 텍스트로
// 보이지 않게 합니다(WikiCard.jsx의 .md 렌더링과 같은 방식). mock 데이터의 문장 중간
// 각주 번호(paragraphs 안에 숫자가 섞인 형태)는 기존처럼 CitationTag로 그대로 둡니다.
//
// 실제 답변 본문 안의 "...조치입니다[1]." 같은 [N] 각주는 linkifyCitationNodes가
// react-markdown의 p/li 렌더러를 대체해서 message.cites[].url로 링크로 바꿉니다 —
// WikiCard.jsx가 위키 본문에서 하는 것과 같은 방식이지만, 여기는 doc.sources가 아니라
// message.cites(citationOrder 대신 no)를 기준으로 찾아서 별도로 구현했습니다.

import { Children, cloneElement, isValidElement } from 'react';
import ReactMarkdown from 'react-markdown';
import CitationTag from '../wiki/CitationTag';

const CITATION_RE = /\[(\d+)\]/g;

function linkifyCitationText(text, cites, keyPrefix) {
  const parts = text.split(CITATION_RE);
  return parts.map((part, i) => {
    if (i % 2 === 0) return part;
    const no = Number(part);
    const cite = cites.find((c) => c.no === no);
    // 매칭되는 근거가 없거나 url이 없으면(백엔드가 아직 원문을 못 찾은 경우 등)
    // 링크를 지어내지 않고 원문 그대로 둡니다.
    if (!cite?.url) return `[${part}]`;
    // documentVersionId가 없으면 위키/원문(DB 문서)이 아니라 실시간 웹 검색 근거다 —
    // 툴팁으로 구분한다(우측 "근거 원문" 카드의 .web 배지와 같은 판별 기준).
    const isWeb = cite.documentVersionId == null;
    return (
      <a
        className="fn"
        key={`${keyPrefix}-cite-${i}`}
        href={cite.url}
        target="_blank"
        rel="noopener"
        title={isWeb ? `웹 검색 근거 ${no}` : `근거 ${no}`}
      >
        {no}
      </a>
    );
  });
}

function linkifyCitationNodes(children, cites, keyPrefix = 'c') {
  return Children.map(children, (child, i) => {
    if (typeof child === 'string') return linkifyCitationText(child, cites, `${keyPrefix}-${i}`);
    if (isValidElement(child) && child.props?.children) {
      return cloneElement(child, {
        children: linkifyCitationNodes(child.props.children, cites, `${keyPrefix}-${i}`),
      });
    }
    return child;
  });
}

function citationComponents(cites) {
  return {
    p: ({ children }) => <p>{linkifyCitationNodes(children, cites)}</p>,
    li: ({ children }) => <li>{linkifyCitationNodes(children, cites)}</li>,
  };
}

const ACT_LABEL = {
  wiki: { idle: '위키에 저장', loading: '저장 중…', done: '위키에 저장됨' },
  team: { idle: '팀에 공유', loading: '공유 중…', done: '팀에 공유됨' },
  copy: { idle: '복사', loading: '복사 중…', done: '복사됨' },
  regen: { idle: '다시 생성', loading: '생성 중…', done: '다시 생성됨' },
  del: { idle: '삭제', loading: '삭제 중…', done: '삭제됨' },
  // 근거 부족(.none) 카드 전용 — 위키·원문에 이어 실시간 웹 검색까지 시도한다.
  websearch: { idle: '웹에서 찾아줘', loading: '웹 검색 중…', done: '검색 완료' },
};

function actLabel(kind, state) {
  const status = state?.status ?? 'idle';
  if (status === 'error') return state.message || ACT_LABEL[kind].idle;
  return ACT_LABEL[kind][status] ?? ACT_LABEL[kind].idle;
}

function ActSpan({ kind, state, onClick, children }) {
  const status = state?.status ?? 'idle';
  const disabled = status === 'loading' || status === 'done';
  return (
    <span
      role="button"
      tabIndex={0}
      style={{
        cursor: disabled ? 'default' : 'pointer',
        opacity: status === 'loading' ? 0.6 : 1,
        color: status === 'error' ? 'var(--red, #c0392b)' : undefined,
      }}
      onClick={() => !disabled && onClick()}
      onKeyDown={(e) => e.key === 'Enter' && !disabled && onClick()}
    >
      {children}
    </span>
  );
}

export default function ChatMessage({ message, flag, flagPriv = false, onAction, actionState }) {
  if (message.role === 'me') {
    return (
      <div className="turn me">
        {message.author && (
          <div className="au"><i>{message.author.initial}</i>{message.author.name}</div>
        )}
        <div className="msg">{message.text}</div>
      </div>
    );
  }

  return (
    <div className="turn ai">
      <div className="mark"></div>
      <div>
        <div className="who">
          MYWIKI{flag && <span className={`fl${flagPriv ? ' priv' : ''}`}>{flag}</span>}
        </div>

        {/* 위키 근거를 못 찾아 일반 지식으로 답한 경우 — 근거 태그·출처 정보 대신
            이 표시만 보여준다. 절대 위키 출처처럼 보이면 안 되므로 본문 위, 가장
            먼저 눈에 띄는 자리에 둔다. .none(근거 부족 카드)과 같은 왼쪽 세로선
            표시 언어를 그대로 써서 이 화면 안에서 낯설지 않게 한다. */}
        {message.llmFallback && (
          <div className="llm-note">
            {/* webSearchExhausted는 백엔드가 안 주는 값이라(AgentResult엔 이 라운드에서
                웹 검색을 실제로 시도했는지 구분하는 필드가 없음) 지속되지 않는다 — "웹에서
                찾아줘"를 누른 그 응답에서만 AgentPage.jsx가 즉석에서 표시해 준다. 대화를
                새로고침하면 이 문구 없이 일반 "LLM 답변" 배지로 보인다. */}
            {message.webSearchExhausted
              ? 'LLM 답변 · 웹 검색에서도 근거를 찾지 못함'
              : 'LLM 답변 · 위키 근거 아님'}
          </div>
        )}

        {message.none ? (
          <div className="none">
            <h6>{message.none.title}</h6>
            <p>{message.none.desc}</p>
          </div>
        ) : (
          (message.paragraphs || []).map((parts, pi) =>
            parts.length === 1 && typeof parts[0] === 'string' ? (
              <div className="md" key={pi}>
                <ReactMarkdown components={citationComponents(message.cites || [])}>{parts[0]}</ReactMarkdown>
              </div>
            ) : (
              <p key={pi}>
                {parts.map((part, i) =>
                  typeof part === 'number'
                    ? <CitationTag key={i} no={part} sourceKey={(message.cites || []).find((c) => c.no === part)?.key} />
                    : <span key={i}>{part}</span>
                )}
              </p>
            )
          ))}

        {message.cites && message.cites.length > 0 && (
          <div className="cites">
            {message.cites.map((c) => (
              <CitationTag key={c.no} no={c.no} sourceKey={c.key} chip />
            ))}
          </div>
        )}

        {message.acts && message.acts.length > 0 && (
          <div className="acts">
            {message.acts.map((a) => {
              if (a === '위키에 저장') {
                return (
                  <ActSpan key={a} kind="wiki" state={actionState?.wiki} onClick={() => onAction?.(a, message)}>
                    {actLabel('wiki', actionState?.wiki)}
                  </ActSpan>
                );
              }
              if (a === '팀에 공유') {
                return (
                  <ActSpan key={a} kind="team" state={actionState?.team} onClick={() => onAction?.(a, message)}>
                    {actLabel('team', actionState?.team)}
                  </ActSpan>
                );
              }
              if (a === '복사') {
                return (
                  <ActSpan key={a} kind="copy" state={actionState?.copy} onClick={() => onAction?.(a, message)}>
                    {actLabel('copy', actionState?.copy)}
                  </ActSpan>
                );
              }
              if (a === '다시 생성') {
                return (
                  <ActSpan key={a} kind="regen" state={actionState?.regen} onClick={() => onAction?.(a, message)}>
                    {actLabel('regen', actionState?.regen)}
                  </ActSpan>
                );
              }
              if (a === '웹에서 찾아줘') {
                return (
                  <ActSpan key={a} kind="websearch" state={actionState?.websearch} onClick={() => onAction?.(a, message)}>
                    {actLabel('websearch', actionState?.websearch)}
                  </ActSpan>
                );
              }
              if (a === '삭제') {
                return (
                  <ActSpan key={a} kind="del" state={actionState?.del} onClick={() => onAction?.(a, message)}>
                    {actLabel('del', actionState?.del)}
                  </ActSpan>
                );
              }
              if (a === '관련 문서 찾아보기') {
                // 백엔드 호출 없이 새 탭을 여는 즉시 동작이라 로딩/완료 상태가 없다.
                return (
                  <ActSpan key={a} kind="search" onClick={() => onAction?.(a, message)}>
                    {a}
                  </ActSpan>
                );
              }
              return <span key={a}>{a}</span>;
            })}
          </div>
        )}
      </div>
    </div>
  );
}
