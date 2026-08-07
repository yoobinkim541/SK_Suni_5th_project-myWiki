// 위키 페이지 전용 — 문서 본문 카드 (.doc)
// 상단 지표(.dmeta) + 구역별 본문(.zone/.p) + 변경 이력(.tl)을 그립니다.
// 본문 안의 근거 번호는 클릭하면 출처 원문으로 이동합니다 — 목업 경로(zone.paragraphs)는
// CitationTag가, 실제 백엔드 markdown 경로(zone.markdown)는 buildCitationComponents가
// react-markdown의 p/li 렌더러를 대체해서 처리합니다(아래 참고).
//
// ⚠ 수정사항 4) 본문에 등장하는 "연동 키워드"를 자동으로 클릭 가능하게 만들었습니다.
//   data/mockWiki.js의 WIKI_KEYWORD_LINKS에 등록된 단어가 본문 문자열에 나오면
//   .wiki-kw 링크로 감싸고, 누르면 부모(WikiPage)가 연동 원문 모달을 엽니다.
//   본문 위 칩 줄(.kw-bar)은 WikiKeywordBar가 그립니다 — 이 문서 핵심 키워드 7개를
//   두고, 펼치면 카탈로그 전체가 분류별로 뜹니다. 칩을 누르면 그 키워드가 등장하는
//   문서 목록이 뜨고(본문 안 .wiki-kw는 그대로 원문·뉴스 모달입니다).
//
//   각주(①②③)와 역할이 다릅니다:
//     각주    = "이 문장의 근거 1건"      → 해당 출처 원문 한 곳으로 바로 이동
//     키워드  = "이 단어와 엮인 근거 전체" → 공시·IR 원문 + 뉴스기사 목록을 모달로 모아 보여줌

import { Children, cloneElement, isValidElement } from 'react';
import ReactMarkdown from 'react-markdown';
import CitationTag from './CitationTag';
import WikiKeywordBar from './WikiKeywordBar';
import { WIKI_KEYWORD_LINKS, getWikiKeywordList } from '../../data/mockWiki';

// 실제 백엔드 markdown 본문의 "...조치입니다[1]." 같은 각주 번호를 doc.sources의
// 해당 citationOrder 원문 링크로 바꿉니다. 목업 경로(zone.paragraphs)의 CitationTag와
// 하는 일은 같지만, 여기는 react-markdown이 렌더링한 문자열/엘리먼트 트리를 훑어야
// 해서 별도 구현입니다 — sourceKey 기반 목업 조회(getSource)를 안 쓰고 doc.sources를
// citationOrder로 직접 찾습니다.
const CITATION_RE = /\[(\d+)\]/g;

function linkifyCitationText(text, sources, keyPrefix) {
  const parts = text.split(CITATION_RE);
  return parts.map((part, i) => {
    if (i % 2 === 0) return part;
    const citationOrder = Number(part);
    const source = sources.find((s) => s.citationOrder === citationOrder);
    // 매칭되는 근거가 없으면(citationOrder 불일치 등) 링크를 지어내지 않고 원문 그대로 둡니다.
    if (!source?.url) return `[${part}]`;
    return (
      <a
        className="fn"
        key={`${keyPrefix}-cite-${i}`}
        href={source.url}
        target="_blank"
        rel="noopener"
        title={`근거 ${citationOrder} · ${source.title}`}
      >
        {citationOrder}
      </a>
    );
  });
}

function linkifyCitationNodes(children, sources, keyPrefix = 'c') {
  return Children.map(children, (child, i) => {
    if (typeof child === 'string') {
      return linkifyCitationText(child, sources, `${keyPrefix}-${i}`);
    }
    if (isValidElement(child) && child.props?.children) {
      return cloneElement(child, {
        children: linkifyCitationNodes(child.props.children, sources, `${keyPrefix}-${i}`),
      });
    }
    return child;
  });
}

// ReactMarkdown의 p/li 렌더러를 대체해서, 실제 본문 안의 [숫자] 각주를 클릭 가능한
// 링크로 바꿔치기합니다.
function buildCitationComponents(sources) {
  return {
    p: ({ children }) => <p>{linkifyCitationNodes(children, sources)}</p>,
    li: ({ children }) => <li>{linkifyCitationNodes(children, sources)}</li>,
  };
}

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

export default function WikiCard({ doc, onKeyword, onKeywordDocs, catalog, linkWords }) {
  if (!doc) return null;

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

      <WikiKeywordBar doc={doc} onKeyword={onKeywordDocs} catalog={catalog} linkWords={linkWords} />

      {doc.zones.map((zone) => (
        <div key={zone.title}>
          <div className="zone">{zone.title}</div>
          {zone.markdown ? (
            <div className="md">
              <ReactMarkdown components={buildCitationComponents(doc.sources)}>{zone.markdown}</ReactMarkdown>
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
