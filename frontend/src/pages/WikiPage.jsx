// 위키 페이지 — PC/모바일 공용 (#v-wiki)
//
// 동작 세 가지:
//  1) 좌측 문서 목록(.tree)의 문서를 누르면 해당 문서로 전환됩니다.
//     목록은 분류별 3개만 노출하고 나머지는 접습니다(WikiSideNav).
//     연동 키워드는 문서 상단 줄(WikiKeywordBar)에만 둡니다 — 누르면 그 키워드로
//     태깅된 문서 목록이 뜹니다(WikiKeywordDocsModal). 칩 자체는 본문 등장 단어
//     기준(linkWords 포함)이고 모달 목록은 백엔드 태깅 기준이라 서로 다를 수 있습니다.
//     [LIVE] 카탈로그(GET /wiki/keywords)와 문서 목록(GET /wiki/pages?keyword=)
//     둘 다 실제 백엔드 연결 완료 — services/wikiApi.js의
//     fetchWikiKeywordCatalog()/fetchDocsWithKeyword() 참고.
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
import Spinner from '../components/common/Spinner';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { WIKI_KEYWORD_LINKS } from '../data/mockWiki';
import { getKeywordCategory } from '../data/wikiKeywords';
import {
  fetchWikiTree, fetchWikiDoc, resolveWikiId,
  fetchWikiKeywordCatalog, fetchDocsWithKeyword, getKeywordLinkWords,
} from '../services/wikiApi';
import WikiSideNav from '../components/wiki/WikiSideNav';
import WikiCard from '../components/wiki/WikiCard';
import WikiKeywordDocsModal from '../components/wiki/WikiKeywordDocsModal';
import WikiKeywordModal from '../components/wiki/WikiKeywordModal';
import mascotWikiImg from '../assets/mascot-wiki.png';

// 목업 모드에서만 값이 있음(실제 모드는 빈 배열) — services/wikiApi.js 참고.
// 렌더마다 새 배열이 생기지 않게 컴포넌트 밖에서 한 번만 계산한다.
const KEYWORD_LINK_WORDS = getKeywordLinkWords();

export default function WikiPage() {
  const { docId } = useParams();
  const [tree, setTree] = useState(null);
  const [current, setCurrent] = useState(null);
  const [doc, setDoc] = useState(null);
  const [keyword, setKeyword] = useState(null);   // 본문 키워드 → 원문·뉴스 모달
  const [docKeyword, setDocKeyword] = useState(null); // 상단 키워드 칩 → 문서 목록 모달
  // docKeyword 조회 결과 — null: 조회 전/중, []: 조회 끝났고 결과 없음, 배열: 결과 있음.
  const [docKeywordResults, setDocKeywordResults] = useState(null);
  const [docKeywordError, setDocKeywordError] = useState(false);
  const [catalog, setCatalog] = useState([]); // 연동 키워드 카탈로그(분류별)
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

  // 연동 키워드 카탈로그 — 페이지 본문 로딩과 무관하게 한 번만 불러옵니다.
  // 실패해도 화면 전체를 막지 않고(키워드 바가 빈 채로 남을 뿐) 콘솔에만 남깁니다.
  useEffect(() => {
    let alive = true;
    fetchWikiKeywordCatalog()
      .then((data) => alive && setCatalog(data))
      .catch((e) => console.warn('위키 키워드 카탈로그 로딩 실패', e));
    return () => { alive = false; };
  }, []);

  // 상단 키워드 칩을 눌러 "이 키워드로 태깅된 문서" 모달을 열 때 실제 목록을 불러옵니다.
  // 결과를 null로 리셋해서(빈 배열이 아니라) 조회 중과 "결과 없음"을 구분합니다 —
  // 안 그러면 로딩 중에 모달이 "찾지 못했습니다"를 잘못 보여줍니다.
  useEffect(() => {
    setDocKeywordError(false);
    setDocKeywordResults(null);
    if (!docKeyword) return;
    let alive = true;
    fetchDocsWithKeyword(docKeyword, tree)
      .then((data) => alive && setDocKeywordResults(data))
      .catch(() => {
        if (!alive) return;
        setDocKeywordResults([]);
        setDocKeywordError(true);
      });
    return () => { alive = false; };
  }, [docKeyword, tree]);

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
        <Spinner />
        <p>아직 게시된 위키 문서가 없습니다.</p>
      </section>
    );
  }

  if (!tree || !doc) {
    return (
      <section className="view on" id="v-wiki">
        <Spinner />
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
        <WikiSideNav tree={tree} current={current} onSelect={setCurrent} />

        <WikiCard
          doc={doc} onKeyword={setKeyword} onKeywordDocs={setDocKeyword}
          catalog={catalog} linkWords={KEYWORD_LINK_WORDS}
        />

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
            <div className="mascot-float">
              <img src={mascotWikiImg} alt="마이위키 마스코트" />
            </div>
          </div>
        </div>
      </div>

      <WikiKeywordModal
        word={keyword}
        entry={keyword ? WIKI_KEYWORD_LINKS[keyword] : null}
        onClose={() => setKeyword(null)}
      />

      <WikiKeywordDocsModal
        word={docKeyword}
        docs={docKeywordResults}
        error={docKeywordError}
        category={docKeyword ? getKeywordCategory(docKeyword, catalog) : null}
        onSelect={setCurrent}
        onClose={() => setDocKeyword(null)}
      />
    </section>
  );
}
