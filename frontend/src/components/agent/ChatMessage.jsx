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

import CitationTag from '../wiki/CitationTag';

const ACT_LABEL = {
  wiki: { idle: '위키에 저장', loading: '저장 중…', done: '위키에 저장됨' },
  team: { idle: '팀에 공유', loading: '공유 중…', done: '팀에 공유됨' },
  copy: { idle: '복사', loading: '복사 중…', done: '복사됨' },
  regen: { idle: '다시 생성', loading: '생성 중…', done: '다시 생성됨' },
  del: { idle: '삭제', loading: '삭제 중…', done: '삭제됨' },
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

        {message.none ? (
          <div className="none">
            <h6>{message.none.title}</h6>
            <p>{message.none.desc}</p>
          </div>
        ) : (
          (message.paragraphs || []).map((parts, pi) => (
            <p key={pi}>
              {parts.map((part, i) =>
                typeof part === 'number'
                  ? <CitationTag key={i} no={part} sourceKey={(message.cites || []).find((c) => c.no === part)?.key} />
                  : <span key={i}>{part}</span>
              )}
            </p>
          ))
        )}

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
              if (a === '삭제') {
                return (
                  <ActSpan key={a} kind="del" state={actionState?.del} onClick={() => onAction?.(a, message)}>
                    {actLabel('del', actionState?.del)}
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
