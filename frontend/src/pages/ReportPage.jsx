// 일일 리포트 페이지 — PC/모바일 공용 (#v-report)
//
// data/mockReport.js를 직접 보지 않고 services/reportApi.js를 거칩니다.
//
// ⚠ 이번 개편: "주요 이슈" 섹션(IssueList 4건)을 없애면서 fetchReportIssues 호출도 뺐습니다.
//   화면 구성:
//   (1) 오늘 리포트 큰 카드     ← ReportSection (누르면 전체 리포트 모달)
//   (2) 분류 + 오늘의 키워드   ← ReportSummary (오늘 리포트 아래로 이동)
//   (3) 리포트 히스토리 2열     ← ReportSection (페이지 넘김)

import { useState, useEffect } from 'react';
import {
  fetchReportSummary,
  fetchReportArchive,
  fetchTodayReport,
} from '../services/reportApi';
import ReportSection from '../components/report/ReportSection';

export default function ReportPage({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [archive, setArchive] = useState([]);
  const [today, setToday] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      fetchReportSummary(),
      fetchReportArchive(),
      fetchTodayReport(),
    ]).then(([s, a, t]) => {
      if (!alive) return;
      setSummary(s);
      setArchive(a);
      setToday(t);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <section className="view on" id="v-report">
        <div className="ph"><h2>일일 동향 보고서</h2></div>
        <div className="loading">불러오는 중…</div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-report">
      <div className="ph">
        <h2>일일 동향 보고서</h2>
        <span className="dt">{summary.date}</span>
        <span className="st">수집 파이프라인 <b>정상</b></span>
      </div>

      {/* ⚠ 분류·오늘의 키워드(ReportSummary)는 오늘 리포트 카드 아래에 오도록
          ReportSection 안에서 렌더링합니다 — 순서: 오늘 리포트 → 분류/키워드 → 히스토리 */}
      <ReportSection
        archive={archive}
        today={today}
        summary={summary}
        onSelectWiki={(wikiId) => onNavigate?.('wiki', wikiId)}
      />
    </section>
  );
}
