// 일일 리포트 페이지 — PC/모바일 공용 (#v-report)
//
// ⚠ 이번에 고친 것: data/mockReport.js를 직접 보던 걸 services/reportApi.js를
//   거치도록 바꿨습니다(다운로드 버튼은 원래부터 reportApi를 쓰고 있었고,
//   이번에 요약·주요이슈·보관함·오늘자 정보까지 전부 서비스 계층을 거치게 맞췄습니다).
//
// 수정사항 5) 화면 구성은 그대로 유지:
//   (1) 분류 + 오늘의 키워드      ← ReportSummary  (기존 "처리 현황" KPI 섹션은 삭제)
//   (2) 주요 이슈 + 다운로드 버튼  ← ReportSection 앞부분
//   (3) 리포트 보관 · 내보내기     ← ReportSection 뒷부분 (전체 다운로드 + 보관함 유지)

import { useState, useEffect } from 'react';
import {
  fetchReportSummary,
  fetchReportIssues,
  fetchReportArchive,
  fetchTodayReport,
} from '../services/reportApi';
import ReportSummary from '../components/report/ReportSummary';
import ReportSection from '../components/report/ReportSection';

export default function ReportPage({ onNavigate }) {
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [issues, setIssues] = useState([]);
  const [archive, setArchive] = useState([]);
  const [today, setToday] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      fetchReportSummary(),
      fetchReportIssues(),
      fetchReportArchive(),
      fetchTodayReport(),
    ]).then(([s, i, a, t]) => {
      if (!alive) return;
      setSummary(s);
      setIssues(i);
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

      <ReportSummary summary={summary} />

      <ReportSection
        issues={issues}
        archive={archive}
        today={today}
        onSelectWiki={(wikiId) => onNavigate?.('wiki', wikiId)}
      />
    </section>
  );
}
