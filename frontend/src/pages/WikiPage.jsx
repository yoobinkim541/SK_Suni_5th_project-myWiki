// 위키 페이지 — PC/모바일 공용 (#v-wiki)
//
// 동작 세 가지:
//  1) 좌측 문서 목록(.tree)의 문서를 누르면 해당 문서로 전환됩니다.
//  2) 우측 "연결된 문서"를 누르면 그 문서로 이동합니다(문서 간 상호 이동).
//  3) ⚠ 수정사항 4) 본문 안의 연동 키워드(.wiki-kw) 또는 상단 키워드 칩(.kw-chip)을 누르면
//     그 키워드에 엮인 공시·IR 원문과 뉴스기사 목록이 모달로 뜹니다.
//
// 1·2번은 같은 상태(docId) 하나만 바꾸므로 동작이 갈리지 않습니다.
// 근거 출처는 백엔드가 조인해 준 문서 제목·매체명·게시일을 그대로 보여주고,
// 클릭하면 언론사 원문(canonical_url)으로 이동합니다 — 실제 원문 주소가 없는
// 근거는 클릭 불가로 남겨 둡니다(잘못된 링크를 지어내지 않음).
//
// 데이터는 services/wikiApi.js를 통해서만 가져옵니다.
// VITE_USE_MOCK=true면 목업, false면 실제 백엔드(api/wiki.js)를 호출합니다.

import { useEffect, useState } from 'react';
import { WIKI_KEYWORD_LINKS } from '../data/mockWiki';
import { fetchWikiTree, fetchWikiDoc, resolveWikiId } from '../services/wikiApi';
import WikiCard from '../components/wiki/WikiCard';
import WikiKeywordModal from '../components/wiki/WikiKeywordModal';
import mascotWikiImg from '../assets/mascot-wiki.png';

// 우측 컬럼("연결된 문서") 아래 두는 마스코트 — 에이전트 페이지의 MascotFloat와 같은
// CSS(.mascot-float)를 공유해서 위/아래로 둥둥 뜨는 애니메이션이 동일하게 적용된다.
function MascotFloat() {
  return (
    <div className="mascot-float">
      <img src={mascotWikiImg} alt="마이위키 마스코트" />
    </div>
  );
}

export default function WikiPage({ docId }) {
  const [tree, setTree] = useState(null);
  const [current, setCurrent] = useState(null);
  const [doc, setDoc] = useState(null);
  const [keyword, setKeyword] = useState(null);
  const [error, setError] = useState(null);

  // 최초 진입 시 좌측 트리를 불러오고, 대시보드·리포트에서 넘어온 docId가
  // 없으면 첫 문서를 기본으로 엽니다.
  useEffect(() => {
    let alive = true;
    fetchWikiTree()
      .then((data) => {
        if (!alive) return;
        setTree(data);
        const resolved = resolveWikiId(docId) || data[0]?.items[0]?.id || null;
        setCurrent(resolved);
      })
      .catch((e) => alive && setError(e.message || '위키 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, []);

  // 대시보드·리포트의 "관련 위키" 링크로 진입했을 때 해당 문서를 엽니다.
  useEffect(() => {
    if (docId) setCurrent(resolveWikiId(docId));
  }, [docId]);

  // 현재 선택된 문서의 본문을 불러옵니다.
  useEffect(() => {
    if (!current) return;
    let alive = true;
    setDoc(null);
    fetchWikiDoc(current)
      .then((data) => alive && setDoc(data))
      .catch((e) => alive && setError(e.message || '위키 문서를 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [current]);

  if (error) {
    return (
      <section className="view on" id="v-wiki">
        <div className="ph"><h2>위키를 불러오지 못했습니다</h2></div>
        <p>{error}</p>
      </section>
    );
  }

  // 게시된 위키 문서가 아직 하나도 없는 워크스페이스(신규 워크스페이스, 또는 생성된 문서가
  // 전부 검토 대기 중인 경우) — resolveWikiId가 돌려줄 문서 id가 없어서 current가 계속
  // null로 남고, 그 결과 아래 "불러오는 중…" 화면에서 영원히 못 벗어난다. 트리 자체는
  // 정상적으로 도착했으니 별도의 빈 상태로 구분해서 보여준다.
  if (tree && tree.every((group) => group.items.length === 0)) {
    return (
      <section className="view on" id="v-wiki">
        <div className="ph"><h2>위키</h2></div>
        <p>아직 게시된 위키 문서가 없습니다.</p>
      </section>
    );
  }

  if (!tree || !doc) {
    return (
      <section className="view on" id="v-wiki">
        <div className="ph"><h2>불러오는 중…</h2></div>
      </section>
    );
  }

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
              {section.items.map((item) => (
                <a
                  key={item.id}
                  className={current === item.id ? 'on' : ''}
                  onClick={() => setCurrent(item.id)}
                >
                  {item.title}
                </a>
              ))}
            </div>
          ))}
        </div>

        <WikiCard doc={doc} onKeyword={setKeyword} />

        <div>
          <div className="col">
            <h5>근거 출처<span className="c">{doc.sourceCount}</span></h5>
            {doc.sources.map((s, i) => (
              <a
                className="it"
                key={`${s.citationOrder}-${i}`}
                href={s.url || undefined}
                target={s.url ? '_blank' : undefined}
                rel={s.url ? 'noopener' : undefined}
                title={s.url ? s.title : `${s.title} (원문 주소 확인 안 됨)`}
                aria-disabled={!s.url}
              >
                <span className="no">{i + 1}</span>
                {s.title}{s.sourceName ? ` · ${s.sourceName}` : ''}{s.date ? ` · ${s.date}` : ''}
              </a>
            ))}
          </div>

          <div className="col">
            <h5>연결된 문서<span className="c">{doc.links.length}</span></h5>
            {doc.links.map((l) => (
              <button className="it lnk" key={l.id} onClick={() => setCurrent(l.id)}>
                <b>{l.title}</b>{l.desc}
              </button>
            ))}
          </div>

          <MascotFloat />
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
