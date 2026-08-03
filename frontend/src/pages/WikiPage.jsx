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

import { useEffect, useState } from 'react';
import { MOCK_WIKI_TREE, MOCK_WIKI_DOCS, DEFAULT_WIKI_DOC, WIKI_KEYWORD_LINKS } from '../data/mockWiki';
import { getWikiDoc, getSource, resolveWikiId } from '../services/wikiApi';
import WikiCard from '../components/wiki/WikiCard';
import WikiKeywordModal from '../components/wiki/WikiKeywordModal';

export default function WikiPage({ docId }) {
  const [current, setCurrent] = useState(() => resolveWikiId(docId || DEFAULT_WIKI_DOC));
  const [keyword, setKeyword] = useState(null);

  // 대시보드·리포트의 "관련 위키" 링크로 진입했을 때 해당 문서를 엽니다.
  useEffect(() => {
    if (docId) setCurrent(resolveWikiId(docId));
  }, [docId]);

  const doc = getWikiDoc(current);

  return (
    <section className="view on" id="v-wiki">
      <div className="ph">
        <h2>{doc.title}</h2>
        <span className="dt">{doc.category}</span>
        <span className="st">최종 갱신 <b>{doc.updated}</b></span>
      </div>

      <div className="wiki">
        <div className="tree">
          {MOCK_WIKI_TREE.map((section) => (
            <div key={section.group}>
              <div className="g">{section.group}</div>
              {section.items.map((id) => (
                <a
                  key={id}
                  className={current === id ? 'on' : ''}
                  onClick={() => setCurrent(id)}
                >
                  {MOCK_WIKI_DOCS[id].title}
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
              const src = getSource(s.key);
              return (
                <a
                  className="it"
                  key={`${s.key}-${i}`}
                  href={src.url}
                  target="_blank"
                  rel="noopener"
                  title={src.title}
                >
                  <span className="no">{i + 1}</span>{src.name} · {s.date}
                </a>
              );
            })}
          </div>

          <div className="col">
            <h5>연결된 문서<span className="c">{doc.links.length}</span></h5>
            {doc.links.map((l) => (
              <button className="it lnk" key={l.id} onClick={() => setCurrent(l.id)}>
                <b>{l.title}</b>{l.desc}
              </button>
            ))}
          </div>
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
