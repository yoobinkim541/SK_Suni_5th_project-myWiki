// 위키 페이지 — PC/모바일 공용 (#v-wiki)
//
// 동작 세 가지:
//  1) 좌측 문서 목록(.tree)의 문서를 누르면 해당 문서로 전환됩니다.
//  2) 우측 "연결된 문서"를 누르면 그 문서로 이동합니다(문서 간 상호 이동).
//  3) ⚠ 수정사항 4) 본문 안의 연동 키워드(.wiki-kw) 또는 상단 키워드 칩(.kw-chip)을 누르면
//     그 키워드에 엮인 공시·IR 원문과 뉴스기사 목록이 모달로 뜹니다.
//
// 1·2번은 같은 상태(docId) 하나만 바꾸므로 동작이 갈리지 않습니다.
// 근거 출처와 본문 각주는 기존대로 출처 원문(Source Router)으로 새 탭 이동합니다.
//
// ⚠ 수정: data/mockWiki.js를 직접 import 하던 것을 services/wikiApi.js 경유로 바꿨습니다.
//   백엔드 호출은 비동기라서 getWikiDoc(동기) → fetchWikiDoc(비동기) + useEffect 구조로 전환했습니다.
//   트리 제목도 MOCK_WIKI_DOCS를 뒤지지 않고 트리 응답의 titles를 씁니다.
//
// ⚠ 백엔드에 대응 데이터가 없는 항목은 비워 둡니다(없는 값을 지어내지 않습니다):
//   · 연결된 문서(links) — 위키 간 링크 테이블 없음 → 비었으면 섹션을 숨깁니다
//   · 근거 출처의 출처명·날짜 — citations에 document_version_id만 옴 → "출처 확인 중"
//   · 키워드 모달 — 전용 엔드포인트 없음 → 당분간 목업 매핑 유지

import { useEffect, useState } from 'react';
import { WIKI_KEYWORD_LINKS, DEFAULT_WIKI_DOC } from '../data/mockWiki';
import { fetchWikiTree, fetchWikiDoc, getSource, resolveWikiId } from '../services/wikiApi';
import WikiCard from '../components/wiki/WikiCard';
import WikiKeywordModal from '../components/wiki/WikiKeywordModal';

export default function WikiPage({ docId }) {
  const [tree, setTree] = useState([]);
  const [current, setCurrent] = useState(() => resolveWikiId(docId || DEFAULT_WIKI_DOC));
  const [doc, setDoc] = useState(null);
  const [keyword, setKeyword] = useState(null);
  const [error, setError] = useState(null);

  // 좌측 문서 트리
  useEffect(() => {
    let alive = true;
    fetchWikiTree()
      .then((rows) => alive && setTree(rows))
      .catch((e) => alive && setError(e.message || '문서 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, []);

  // 대시보드·리포트의 "관련 위키" 링크로 진입했을 때 해당 문서를 엽니다.
  useEffect(() => {
    if (docId) setCurrent(resolveWikiId(docId));
  }, [docId]);

  // 현재 문서 본문
  useEffect(() => {
    let alive = true;
    setError(null);
    fetchWikiDoc(current)
      .then((d) => alive && setDoc(d))
      .catch((e) => alive && setError(e.message || '문서를 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [current]);

  // 트리에서 문서 제목을 찾습니다. titles가 없으면(목업) 현재 문서 제목으로 대체합니다.
  function titleOf(id) {
    for (const section of tree) {
      if (section.titles?.[id]) return section.titles[id];
    }
    return doc?.id === id ? doc.title : id;
  }

  if (error && !doc) {
    return (
      <section className="view on" id="v-wiki">
        <div className="empty-conv">{error}</div>
      </section>
    );
  }

  if (!doc) {
    return (
      <section className="view on" id="v-wiki">
        <div className="empty-conv">불러오는 중…</div>
      </section>
    );
  }

  const links = doc.links ?? [];

  return (
    <section className="view on" id="v-wiki">
      <div className="ph">
        <h2>{doc.title}</h2>
        <span className="dt">{doc.category}</span>
        <span className="st">최종 갱신 <b>{doc.updated}</b></span>
      </div>

      <div className="wiki">
        <div className="tree">
          {tree.map((section) => (
            <div key={section.group}>
              <div className="g">{section.group}</div>
              {section.items.map((id) => (
                <a
                  key={id}
                  className={current === id ? 'on' : ''}
                  onClick={() => setCurrent(id)}
                >
                  {titleOf(id)}
                </a>
              ))}
            </div>
          ))}
        </div>

        <WikiCard doc={doc} onKeyword={setKeyword} />

        <div>
          <div className="col">
            <h5>근거 출처<span className="c">{doc.sourceCount}</span></h5>
            {doc.sources.map((s, i) => {
              // s.key가 null일 수 있습니다(백엔드가 출처 종류를 주지 않는 경우).
              const src = getSource(s.key);
              const label = src ? `${src.name} · ${s.date}` : `근거 문서 #${s.no ?? i + 1} · 출처 확인 중`;
              if (!src) {
                return (
                  <span className="it" key={`src-${i}`}>
                    <span className="no">{i + 1}</span>{label}
                  </span>
                );
              }
              return (
                <a
                  className="it"
                  key={`${s.key}-${i}`}
                  href={src.url}
                  target="_blank"
                  rel="noopener"
                  title={src.title}
                >
                  <span className="no">{i + 1}</span>{label}
                </a>
              );
            })}
          </div>

          {/* 위키 간 링크가 백엔드에 없어서, 비어 있으면 섹션 자체를 숨깁니다. */}
          {links.length > 0 && (
            <div className="col">
              <h5>연결된 문서<span className="c">{links.length}</span></h5>
              {links.map((l) => (
                <button className="it lnk" key={l.id} onClick={() => setCurrent(l.id)}>
                  <b>{l.title}</b>{l.desc}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <WikiKeywordModal
        word={keyword}
        entry={keyword ? WIKI_KEYWORD_LINKS[keyword] : null}
        onClose={() => setKeyword(null)}
      />
    </section>
  );
}
