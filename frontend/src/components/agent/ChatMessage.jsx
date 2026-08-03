// 에이전트 전용 — 대화 한 턴(.turn)
// 사용자 메시지(.turn.me)와 에이전트 답변(.turn.ai)을 같은 컴포넌트에서 처리합니다.
//
// 팀 공유 대화에서는 사용자 메시지 위에 작성자(.au)가, 답변 헤더에는
// "팀 공유 / 개인" 배지(.who .fl)가 붙습니다 — 시안과 동일합니다.
// 답변 문장의 근거 번호와 하단 근거 칩은 CitationTag가 그립니다.

import CitationTag from '../wiki/CitationTag';

export default function ChatMessage({ message, flag, flagPriv = false }) {
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
            {message.acts.map((a) => <span key={a}>{a}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}
