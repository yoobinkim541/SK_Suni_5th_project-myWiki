// 일일 리포트 페이지 — PC/모바일 공용 (#v-report)
//
// data/mockReport.js를 직접 보지 않고 services/reportApi.js를 거칩니다.
//
// ⚠ 이번 개편: "주요 이슈" 섹션(IssueList 4건)을 없애면서 fetchReportIssues 호출도 뺐습니다.
//   화면 구성:
//   (1) 오늘 리포트 큰 카드     ← ReportSection (누르면 전체 리포트 모달)
//   (2) 분류 + 오늘의 키워드   ← ReportSummary (오늘 리포트 아래로 이동)
//   (3) 리포트 히스토리 2열     ← ReportSection (페이지 넘김)
import Spinner from '../components/common/Spinner';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchReportSummary,
  fetchReportArchive,
  fetchTodayReport,
} from '../services/reportApi';
import ReportSection from '../components/report/ReportSection';

export default function ReportPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [summary, setSummary] = useState(null);
  const [archive, setArchive] = useState([]);
  const [today, setToday] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    setHistoryError('');

    Promise.all([
      fetchReportSummary(),
      fetchTodayReport(),
      fetchReportArchive().then(
        (items) => ({ ok: true, items }),
        (err) => ({ ok: false, err }),
      ),
    ])
      .then(([s, t, historyResult]) => {
        if (!alive) return;
        setSummary(s);
        setToday(t);
        if (historyResult.ok) {
          setArchive(historyResult.items);
        } else {
          setArchive([]);
          setHistoryError(historyResult.err?.message || '\uB9AC\uD3EC\uD2B8 \uD788\uC2A4\uD1A0\uB9AC\uB97C \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.');
        }
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message || '리포트를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });

    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <section className="view on" id="v-report">
        <div className="ph"><h2>일일 동향 보고서</h2></div>
        <Spinner />
      </section>
    );
  }


  if (error || !summary || !today) {
    return (
      <section className="view on" id="v-report">
        <div className="ph"><h2>일일 동향 보고서</h2></div>
        <div className="loading">{error || '리포트를 불러오지 못했습니다.'}</div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-report">
      <div className="ph">
        <h2>일일 동향 보고서</h2>
        <span className="dt">{summary.date}</span>
        <span className="st">{summary.statusLabel || <>수집 파이프라인 <b>정상</b></>}</span>
      </div>

      {/* ⚠ 분류·오늘의 키워드(ReportSummary)는 오늘 리포트 카드 아래에 오도록
          ReportSection 안에서 렌더링합니다 — 순서: 오늘 리포트 → 분류/키워드 → 히스토리 */}
      <ReportSection
        archive={archive}
        today={today}
        summary={summary}
        historyError={historyError}
        onSelectWiki={(wikiId) => navigate(`/wiki/${wikiId}`)}
      />
    </section>
  );
}
