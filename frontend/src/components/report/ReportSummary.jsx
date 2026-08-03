// 일일 리포트 전용 — 상단 요약
//
// ⚠ 수정사항 5) "처리 현황"(수집 문서/정제 후 채택/선별 이슈/위키 갱신 KPI 4개) 섹션을 제거했습니다.
//   → 리포트를 여는 목적은 "오늘 뭐가 있었나"를 보는 것이지 파이프라인 통계를 보는 게 아니라서,
//     처리 현황은 대시보드 "최근 현황"에만 두고 리포트에서는 뺐습니다.
//     (KPI 데이터 자체는 data/mockReport.js의 summary.kpis에 그대로 남겨뒀습니다.
//      다시 살릴 일이 생기면 이 파일에서 KpiCard 섹션만 되돌리면 됩니다.)
//
// 이제 리포트 화면의 첫 섹션은 "분류"이고, 그 아래에 오늘의 키워드가 붙습니다.

export default function ReportSummary({ summary }) {
  return (
    <section className="sec">
      <div className="sh"><span className="t">분류</span><span className="s">{summary.totalLabel}</span></div>
      <div className="rep-cats">
        {summary.categories.map((c, i) => (
          <span className={i === 0 ? 'all' : ''} key={c.name}>
            {c.name} <b>{c.count}</b>
          </span>
        ))}
      </div>
      <div className="rep-kw">
        <span className="lb">오늘의 키워드</span>
        {summary.keywords.map((k) => <span key={k}>{k}</span>)}
      </div>
    </section>
  );
}
