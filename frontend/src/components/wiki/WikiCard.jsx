// 위키 페이지 전용 — 문서 본문 카드 (.doc)
// 상단 지표(.dmeta) + 구역별 본문(.zone/.p) + 변경 이력(.tl)을 그립니다.
// 본문 안의 근거 번호는 CitationTag가 그리고, 누르면 출처 원문으로 이동합니다.
//
// ⚠ 수정사항 4) 본문에 등장하는 "연동 키워드"를 자동으로 클릭 가능하게 만들었습니다.
//   data/mockWiki.js의 WIKI_KEYWORD_LINKS에 등록된 단어가 본문 문자열에 나오면
//   .wiki-kw 링크로 감싸고, 누르면 부모(WikiPage)가 연동 원문 모달을 엽니다.
//   본문 위에는 이 문서에서 연동 가능한 키워드를 칩(.kw-bar)으로 한 번 더 노출해서,
//   본문을 읽지 않고도 바로 원문으로 들어갈 수 있게 했습니다.
//
//   각주(①②③)와 역할이 다릅니다:
//     각주    = "이 문장의 근거 1건"      → 해당 출처 원문 한 곳으로 바로 이동
//     키워드  = "이 단어와 엮인 근거 전체" → 공시·IR 원문 + 뉴스기사 목록을 모달로 모아 보여줌

import ReactMarkdown from 'react-markdown';
import CitationTag from './CitationTag';
import { WIKI_KEYWORD_LINKS, getWikiKeywordList } from '../../data/mockWiki';

// 정규식 특수문자가 키워드에 섞여도 안전하게 이스케이프합니다.
function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 키워드는 길이 내림차순이라 "청주 M15X"가 "M15X"보다 먼저 매칭됩니다.
const KEYWORD_RE = new RegExp(`(${getWikiKeywordList().map(escapeRegExp).join('|')})`, 'g');

// 본문 문자열 하나를 [텍스트, 키워드링크, 텍스트, ...] 로 쪼갭니다.
function linkifyKeywords(text, onKeyword, keyPrefix) {
  const chunks = text.split(KEYWORD_RE);
  return chunks.map((chunk, i) => {
    if (WIKI_KEYWORD_LINKS[chunk]) {
      return (
        <button
          type="button"
          className="wiki-kw"
          key={`${keyPrefix}-kw-${i}`}
          title={`${chunk} · 공시 원문·뉴스기사 보기`}
          onClick={() => onKeyword?.(chunk)}
        >
          {chunk}
        </button>
      );
    }
    return <span key={`${keyPrefix}-t-${i}`}>{chunk}</span>;
  });
}

// 이 문서 본문에 실제로 등장하는 연동 키워드만 상단 칩으로 노출합니다.
function collectDocKeywords(doc) {
  const body = doc.zones
    .flatMap((z) => (z.markdown ? [z.markdown] : z.paragraphs.flat()))
    .filter((p) => typeof p === 'string')
    .join(' ');
  return getWikiKeywordList().filter((k) => body.includes(k));
}

export default function WikiCard({ doc, onKeyword }) {
  if (!doc) return null;

  const docKeywords = collectDocKeywords(doc);

  return (
    <div className="doc">
      <div className="dmeta">
        {doc.meta.map((m) => {
          // "근거 문서 12건" → 뒤쪽 수치만 <b>로 강조 (시안과 동일)
          const idx = m.lastIndexOf(' ');
          return (
            <span key={m}>
              {m.slice(0, idx + 1)}<b>{m.slice(idx + 1)}</b>
            </span>
          );
        })}
      </div>

      {docKeywords.length > 0 && (
        <div className="kw-bar">
          <span className="lb">연동 키워드</span>
          {docKeywords.map((k) => (
            <button type="button" className="kw-chip" key={k} onClick={() => onKeyword?.(k)}>
              {k}
              <span className="ex" aria-hidden="true">↗</span>
            </button>
          ))}
        </div>
      )}

      {doc.zones.map((zone) => (
        <div key={zone.title}>
          <div className="zone">{zone.title}</div>
          {zone.markdown ? (
            <div className="md">
              <ReactMarkdown>{zone.markdown}</ReactMarkdown>
            </div>
          ) : (
            zone.paragraphs.map((parts, pi) => (
              <p key={pi}>
                {parts.map((part, i) =>
                  typeof part === 'number'
                    ? <CitationTag key={i} no={part} sourceKey={doc.sources[part - 1]?.key} />
                    : linkifyKeywords(part, onKeyword, `${zone.title}-${pi}-${i}`)
                )}
              </p>
            ))
          )}
        </div>
      ))}

      <div className="zone hard">변경 이력</div>
      <div className="tl">
        {doc.timeline.map((t) => (
          <div className={`i${t.isNew ? ' new' : ''}`} key={t.date + t.text}>
            <div className="d">{t.date}</div>
            <div className="t"><b>{t.text}</b> — {t.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
