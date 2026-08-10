// 대시보드 전용 — "최근 산업 이슈" 목록
// 시안 마크업: article.row > (.tr 신뢰도 텍스트) + (분류/제목/설명) + (.meta 출처링크 + 연결 위키링크)
//
// 최신 시안 변경사항 반영:
//  1) 신뢰도 표시에서 막대 게이지(.bar)를 없애고 "신뢰도 : 높음" 텍스트만 표시합니다.
//  2) .meta 안의 출처/연결 위키가 더 이상 <span>이 아니라 실제로 클릭 가능한 <a>입니다.
//     - 출처(.s / .s.doc)는 실제 원문 URL로 새 탭 이동(target="_blank")
//     - 연결 위키(.w)는 앱 내부 라우팅이라 onSelectWiki 콜백으로 처리 (a 태그 + preventDefault)
//       콜백을 안 넘기면 그냥 href만 있는 링크로 동작합니다.
//  3) ⚠ 하단 "신뢰도 기준" 범례를 클릭 가능한 필터로 바꿨습니다.
//     - 예전엔 그냥 정적 텍스트(높음/보통/낮음)였는데, 이제 각각 클릭하면 켜고 끄면서
//       해당 신뢰도의 이슈만 보이게 토글됩니다. (전부 끄면 목록이 비어요 — 의도된 동작입니다)
//     - 예전엔 이 범례가 DashboardPage.jsx에 따로 있었는데, .rows랑 같이 있어야
//       필터 상태를 다루기 편해서 이 컴포넌트 안으로 옮겼습니다.
//       → DashboardPage.jsx에서는 이제 <IssueList .../>만 넣으면 범례까지 같이 나옵니다.
//
// 반응형 참고:
//  .row는 PC에서 grid-template-columns: 130px 1fr 150px (3분할),
//  1020px 이하에서는 CSS 미디어쿼리가 64px 1fr 2컬럼으로 자동 재배치하고 .meta를 2번째 컬럼 아래로 내립니다.
//  즉 이 컴포넌트가 렌더링하는 .tr → 본문 → .meta 3형제 구조를 그대로 유지해야
//  모바일에서도 CSS만으로 레이아웃이 깨지지 않습니다. (JS로 별도 분기할 필요 없음)

import { useState } from 'react';

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: '', mid: 'mid', low: 'low' };
const ALL_LEVELS = ['high', 'mid', 'low'];

// ⚠ onOpenIssue (선택): 넘기면 이슈 행 전체가 클릭 가능해집니다.
//   일일 리포트의 "주요 이슈"에서 행을 누르면 전체 리포트 모달을 띄우려고 추가한 콜백입니다.
//   대시보드는 이 prop을 안 넘기므로 예전처럼 클릭 불가 상태 그대로입니다(동작 변화 없음).
//   행 안의 출처·연결 위키 링크는 stopPropagation으로 모달을 열지 않고 원래 동작만 합니다.
//
// ⚠ downloadFormats / onDownload (선택): 함께 넘기면 각 이슈 행 .meta 안에
//   다운로드 버튼이 붙습니다(일일 리포트의 "주요 이슈"에서 이슈별로 바로 받게 하려는 용도).
//   버튼도 stopPropagation이라 눌러도 위 onOpenIssue(모달 열기)로 번지지 않습니다.
//   둘 다 안 넘기면(대시보드) 버튼 영역 자체가 렌더링되지 않습니다.
export default function IssueList({ items, onSelectWiki, onOpenIssue, downloadFormats, onDownload }) {
  const [activeLevels, setActiveLevels] = useState(new Set(ALL_LEVELS));

  function toggleLevel(level) {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  }

  const visibleItems = items.filter((issue) => activeLevels.has(issue.level));

  return (
    <>
      <div className="rows">
        {visibleItems.map((issue) => (
          <article
            className={`row${onOpenIssue ? ' clickable' : ''}`}
            key={issue.id}
            role={onOpenIssue ? 'button' : undefined}
            tabIndex={onOpenIssue ? 0 : undefined}
            onClick={onOpenIssue ? () => onOpenIssue(issue) : undefined}
            onKeyDown={
              onOpenIssue
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onOpenIssue(issue);
                    }
                  }
                : undefined
            }
          >
            <div className={`tr${LEVEL_CLASS[issue.level] ? ` ${LEVEL_CLASS[issue.level]}` : ''}`}>
              <div className="l">신뢰도 : {LEVEL_LABEL[issue.level]}</div>
            </div>
            <div>
              <div className="ct">{issue.category}</div>
              <h3>{issue.title}</h3>
              <p>{issue.summary}</p>
            </div>
            <div className="meta">
              {/* 샘플 데이터는 링크로 만들지 않는다. 목업의 sourceUrl이 개별 원문이
                  아니라 도메인 루트여서, 누르면 해당 이슈가 아니라 홈페이지로 간다.
                  백엔드가 붙으면 isSample이 사라지고 아래 <a>가 그대로 살아난다. */}
              {issue.isSample ? (
                <span
                  className={`s${issue.sourceIsDoc ? ' doc' : ''} sample`}
                  title="샘플 데이터입니다. 원문 연결은 준비 중입니다"
                >
                  {issue.sourceLabel} (샘플)
                </span>
              ) : (
                <a
                  className={`s${issue.sourceIsDoc ? ' doc' : ''}`}
                  href={issue.sourceUrl}
                  target="_blank"
                  rel="noopener"
                  title={issue.sourceTitle}
                  onClick={(e) => e.stopPropagation()}
                >
                  {issue.sourceLabel}
                </a>
              )}
              {issue.wikiTitle && !issue.isSample && (
                <a
                  className="w"
                  href={issue.wikiHref || '#'}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (onSelectWiki) {
                      e.preventDefault();
                      onSelectWiki(issue.wikiId ?? issue.wikiTitle);
                    }
                  }}
                >
                  {issue.wikiTitle}
                </a>
              )}
              {downloadFormats && downloadFormats.length > 0 && (
                <div className="idl" onClick={(e) => e.stopPropagation()}>
                  {downloadFormats.map((f) => (
                    <button
                      key={f.key}
                      className="dlbtn"
                      onClick={() => onDownload?.(issue, f)}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
      <div className="legend">
        <span>신뢰도 기준</span>
        {ALL_LEVELS.map((level) => (
          <span
            key={level}
            className={`lvl-btn${activeLevels.has(level) ? '' : ' off'}`}
            onClick={() => toggleLevel(level)}
          >
            <b>{LEVEL_LABEL[level]}</b>
          </span>
        ))}
        <span><b>가중치</b> 최신 보도 우선 반영 · 중복·구버전 기사는 자동 감쇠</span>
      </div>
    </>
  );
}

// 목업 데이터는 이 컴포넌트가 아니라 data/mockDashboard.js의 MOCK_ISSUES를 씁니다.
// (예: import { MOCK_ISSUES } from '../../data/mockDashboard';)
