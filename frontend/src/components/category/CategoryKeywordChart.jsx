// 카테고리 현황 전용 — "수집 키워드 분포" 섹션 (수정사항 6)
//
// 원그래프 두 개를 나란히 놓습니다.
//  · 왼쪽  : 6개 분류가 전체에서 각각 몇 %인지
//  · 오른쪽: 선택한 분류 "내부"에 우리가 걸어둔 수집 키워드가 어떻게 나뉘는지
//
// 왼쪽 조각(또는 범례)을 누르면 오른쪽 그래프가 그 분류로 바뀝니다.
// 상단 칩으로도 직접 고를 수 있게 해서, 조각이 작아 누르기 어려운 분류도 접근 가능합니다.
//
// 데이터는 전부 categories prop에서 옵니다 — 예전엔 이 파일이 data/mockCategory.js를
// 직접 import해서, 카드가 실데이터가 돼도 원그래프만 목업으로 남아 숫자가 어긋났습니다.
// 목업/실데이터 분기는 services/categoryApi.js 한 곳에만 둡니다.
//
// 두 파이는 서로 다른 것을 셉니다.
//   왼쪽  = 분류별 문서 수 (카드의 건수와 같은 값)
//   오른쪽 = 그 분류 안에서 어떤 수집 키워드가 문서를 끌어왔는지
// 백엔드가 문서 단위로 세므로 오른쪽 조각 합은 왼쪽의 해당 조각과 일치합니다.

import { useState } from 'react';
import KeywordPie from './KeywordPie';

export default function CategoryKeywordChart({ categories }) {
  const [activeId, setActiveId] = useState(categories[0]?.id);

  const totals = categories.map((c) => ({ id: c.id, word: c.name, count: c.count }));
  const grandTotal = totals.reduce((s, t) => s + t.count, 0);

  const active = categories.find((c) => c.id === activeId) || categories[0];
  const activeKeywords = active?.keywords ?? [];
  const activeTotal = activeKeywords.reduce((s, k) => s + k.count, 0);

  function selectByName(name) {
    const found = categories.find((c) => c.name === name);
    if (found) setActiveId(found.id);
  }

  return (
    <section className="sec">
      <div className="sh">
        <span className="t">수집 키워드 분포</span>
        <span className="s">분류별 비중 · 분류 내부 키워드 구성</span>
        <span className="r">최근 7일 채택 문서 기준</span>
      </div>

      <div className="pie-tabs">
        {categories.map((c) => (
          <button
            type="button"
            key={c.id}
            className={`pie-tab${c.id === activeId ? ' on' : ''}`}
            onClick={() => setActiveId(c.id)}
          >
            {c.name}
          </button>
        ))}
      </div>

      <div className="pie-grid">
        <div className="pie-box">
          <div className="pie-hd">
            <span className="t">분류별 비중</span>
            <span className="s">조각을 누르면 오른쪽이 바뀝니다</span>
          </div>
          <KeywordPie
            items={totals}
            title="전체"
            total={grandTotal}
            activeWord={active?.name}
            onSlice={selectByName}
          />
        </div>

        <div className="pie-box">
          <div className="pie-hd">
            <span className="t">{active?.name} 내부 키워드</span>
            <span className="s">우리가 걸어둔 수집 키워드 기준</span>
          </div>
          <KeywordPie items={activeKeywords} title={active?.name} total={activeTotal} />
        </div>
      </div>

      <div className="legend">
        <span>읽는 법</span>
        <span>왼쪽 = 6개 분류가 전체 수집량에서 차지하는 비중</span>
        <span><b>오른쪽</b> 선택한 분류 안에서 어떤 수집 키워드가 문서를 끌어왔는지</span>
      </div>
    </section>
  );
}
