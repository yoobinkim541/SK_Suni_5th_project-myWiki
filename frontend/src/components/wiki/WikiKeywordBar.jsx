// 문서 상단 "연동 키워드" 줄 (.kw-bar)
//
// 접힘 : 이 문서의 핵심 키워드 7개 이내.
//        본문에 실제로 등장한 키워드만 올립니다 — 없는 걸 채워 7칸을 맞추지 않습니다.
// 펼침 : 이 문서 분류의 키워드 전체가 먼저 뜨고, 그 아래로 나머지 분류가 분류별로 나뉘어 뜹니다.
//
// 칩을 누르면 그 키워드로 태깅된 위키 문서 목록이 모달로 뜹니다(WikiKeywordDocsModal).
// 칩 자체는 "본문에 등장한 단어" 기준이고 모달 목록은 "백엔드가 태깅한 페이지"
// 기준이라 두 기준이 다를 수 있습니다(예: 이 문서 본문에 단어가 보여도, 그 단어가
// 이 페이지의 태그 목록 8개 안에 들지 않았으면 모달 결과에 이 문서가 안 나올 수 있음).
// 본문 안 키워드(.wiki-kw)와 역할이 다릅니다 — 본문 쪽은 공시·IR 원문/뉴스기사 모달입니다.

import { useMemo, useState } from 'react';
import { getDocCoreKeywords, getKeywordTotal } from '../../data/wikiKeywords';
import '../../styles/wiki-keyword-bar.css';

const TOP_KEYWORDS = 7; // 접힌 상태 노출 개수

function Chevron() {
  return (
    <svg
      className="chev" viewBox="0 0 24 24" width="12" height="12" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function Chip({ word, hot, onKeyword }) {
  return (
    <button
      type="button" className={`kw-chip${hot ? ' hot' : ''}`}
      title={`${word} · 이 키워드로 태깅된 문서 보기`}
      onClick={() => onKeyword?.(word)}
    >
      {word}
      <span className="ex" aria-hidden="true">↗</span>
    </button>
  );
}

// catalog가 아직 안 실려 왔으면(WikiPage의 초기 fetch 도중) 빈 배열로 둡니다 —
// 목업 값으로 슬쩍 채워 보여주지 않고, 로딩이 끝나면 실제 값으로 다시 렌더링됩니다.
// linkWords도 WikiPage가 mock/real 모드에 맞게 내려주는 값을 그대로 씁니다(실제
// 모드에서는 항상 빈 배열 — services/wikiApi.js의 getKeywordLinkWords() 참고).
export default function WikiKeywordBar({ doc, onKeyword, catalog = [], linkWords = [] }) {
  const [open, setOpen] = useState(false);

  const core = useMemo(() => getDocCoreKeywords(doc, catalog, linkWords), [doc, catalog, linkWords]);
  const top = core.slice(0, TOP_KEYWORDS);
  const topWords = top.map((k) => k.word);
  const total = getKeywordTotal(catalog);

  // 이 문서 분류를 맨 앞으로 올린 전체 카탈로그
  const groups = useMemo(() => {
    const list = [...catalog];
    const i = list.findIndex((g) => g.cat === doc?.category);
    if (i > 0) list.unshift(list.splice(i, 1)[0]);
    return list;
  }, [doc, catalog]);

  return (
    <div className={`kw-bar${open ? ' open' : ''}`}>
      <div className="kw-row">
        <span className="lb">연동 키워드</span>

        {!open && (
          top.length > 0 ? (
            top.map((k) => (
              <Chip key={k.word} word={k.word} hot onKeyword={onKeyword} />
            ))
          ) : (
            <span className="kw-none">이 문서에서 추출된 키워드가 없습니다.</span>
          )
        )}

        <button
          type="button" className="kw-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <Chevron />
          <span className="lb2">{open ? '접기' : `전체 ${total}개 펼치기`}</span>
        </button>
      </div>

      {open && (
        <div className="kw-all">
          {groups.map((g) => (
            <div className="kw-grp" key={g.cat}>
              <div className={`kw-glb${g.cat === doc?.category ? ' cur' : ''}`}>
                {g.cat}<span>{g.words.length}</span>
              </div>
              <div className="kw-list">
                {g.words.map((w) => (
                  <Chip key={w} word={w} hot={topWords.includes(w)} onKeyword={onKeyword} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
