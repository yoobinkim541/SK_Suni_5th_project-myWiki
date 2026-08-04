// 일일 리포트 전용 — 오늘 리포트 카드 + 리포트 히스토리
//
// ⚠ 이번 개편 내용:
//  1) "주요 이슈" 섹션(IssueList 4건)을 없앴습니다.
//     → 리포트를 여는 목적은 "오늘 리포트를 통째로 보는 것"이라, 이슈를 미리 4건만
//       흩뿌려 보여주는 대신 오늘 리포트 카드 하나로 진입점을 모았습니다.
//  2) 오늘 리포트를 큰 카드 하나로 띄웁니다. 카드를 누르면 전체 리포트 모달이 뜨고,
//     카드 우측 다운로드 버튼(Word/PDF/PPT)은 카드 클릭과 분리돼 있습니다.
//  3) 분류·오늘의 키워드(ReportSummary)를 '오늘 리포트' 제목과 큰 카드 사이에 넣었습니다.
//  4) 리포트 히스토리는 큰 카드 절반 크기로 2열 배치하고, 아래에 페이지 넘김을 붙였습니다.
//     → 기존 "30일 이전 리포트 보기" 토글(archive의 old 플래그)을 대체합니다.
//       일자가 계속 쌓이면 토글로는 감당이 안 되기 때문입니다.
//
// 모달은 기존 ReportDetailModal을 그대로 씁니다 — 오늘 카드와 히스토리 카드가 공유합니다.

import { useEffect, useMemo, useState } from 'react';
import ReportDetailModal from './ReportDetailModal';
import ReportSummary from './ReportSummary';
import { downloadReport, fetchReportDetail } from '../../services/reportApi';

const FORMATS = [
  { key: 'word', label: 'Word', ext: '.docx' },
  { key: 'pdf', label: 'PDF', ext: '.pdf' },
  { key: 'ppt', label: 'PPT', ext: '.pptx' },
];

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: '', mid: 'mid', low: 'low' };

// 히스토리 한 페이지에 보여줄 개수 (2열 × 3줄). 숫자만 바꾸면 됩니다.
const PAGE_SIZE = 6;

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"></path>
      <path d="M14 3v5h5"></path>
      <path d="M12 12v6M9 15l3 3 3-3"></path>
    </svg>
  );
}

export default function ReportSection({ archive, today, summary, onSelectWiki }) {
  const [notice, setNotice] = useState('');
  const [page, setPage] = useState(1);

  // ── 전체 리포트 모달 상태 ──
  // open : { date, highlightId } — 어떤 날짜 리포트를, 어떤 이슈를 강조한 채로 열지
  // detail : fetchReportDetail 결과. undefined = 불러오는 중, null = 그 날짜 리포트 없음.
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(undefined);

  // 오늘 리포트는 히스토리에서 빼고 위쪽 큰 카드로만 보여줍니다(중복 방지).
  const history = useMemo(
    () => archive.filter((r) => r.date !== today?.date),
    [archive, today]
  );

  const todayCard = useMemo(
    () => archive.find((r) => r.date === today?.date) ?? null,
    [archive, today]
  );

  const totalPages = Math.max(1, Math.ceil(history.length / PAGE_SIZE));
  const pageItems = history.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // 목록이 줄어 현재 페이지가 사라지면 마지막 페이지로 되돌립니다.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setDetail(undefined);
    fetchReportDetail(open.date).then((d) => {
      if (alive) setDetail(d ?? null);
    });
    return () => { alive = false; };
  }, [open]);

  function openReport(date, highlightId = null) {
    setOpen({ date, highlightId });
  }

  // 모달 안 다운로드 — issue가 null이면 리포트 전체입니다.
  // 백엔드가 아직 이슈 단위 파일 분리를 지원하지 않아 실제 요청은 날짜+포맷으로만 나가고,
  // 토스트 라벨에만 어떤 이슈에서 눌렀는지 남깁니다.
  function handleModalDownload(issue, format) {
    if (!open) return;
    const label = issue
      ? `${issue.title} · ${format.label}${format.ext}`
      : `전체 ${format.label}${format.ext}`;
    handleDownload(open.date, format.key, label);
  }

  // 실제 파일 생성은 백엔드 몫이라, 지금은 요청이 나갔다는 것만 화면에 알려줍니다.
  // API 클라이언트가 붙으면 services/reportApi.js의 downloadReport만 교체하면 됩니다.
  async function handleDownload(date, format, label) {
    const res = await downloadReport(date, format);
    setNotice(
      res?.ok
        ? `${label} 다운로드를 시작했습니다.`
        : `${date} · ${label} 요청됨 — 파일 생성은 백엔드 연동 후 동작합니다.`
    );
    window.clearTimeout(handleDownload._t);
    handleDownload._t = window.setTimeout(() => setNotice(''), 3200);
  }

  return (
    <>
      {/* ── 오늘 리포트 (큰 카드) ── */}
      <section className="sec">
        <div className="sh big">
          <span className="t">오늘 리포트</span>
          <span className="s">카드를 누르면 전체 리포트와 출처를 볼 수 있습니다</span>
        </div>

        {/* ── 분류 · 오늘의 키워드 ── 오늘 리포트 제목과 큰 카드 사이 */}
        {summary && <ReportSummary summary={summary} />}

        <article
          className="ritem today"
          role="button"
          tabIndex={0}
          onClick={() => openReport(today.date)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              openReport(today.date);
            }
          }}
        >
          <div className="rhd">
            <span className="rd">{todayCard?.label ?? today.label}</span>
            {todayCard?.day && <span className="rk">{todayCard.day}</span>}
          </div>

          {todayCard && (
            <>
              <h4 className="rt">{todayCard.title}</h4>
              <p className="rsum">{todayCard.summary}</p>
              <div className="rmeta">
                이슈 {todayCard.issues}건 · 위키 갱신 {todayCard.wiki}
                <span className={`cf ${LEVEL_CLASS[todayCard.level]}`.trim()}>
                  <i></i>신뢰도 : {LEVEL_LABEL[todayCard.level]}
                </span>
              </div>
            </>
          )}

          {/* 카드 클릭(모달 열기)과 분리 — 버튼을 눌러도 모달이 뜨지 않습니다. */}
          <div className="rdl wide" onClick={(e) => e.stopPropagation()}>
            {FORMATS.map((f) => (
              <button
                className="dlbtn"
                key={f.key}
                onClick={() => handleDownload(today.date, f.key, `전체 ${f.label}${f.ext}`)}
              >
                <DownloadIcon />
                {f.label} <span className="ext">{f.ext}</span>
              </button>
            ))}
          </div>
        </article>
      </section>

      {/* ── 리포트 히스토리 (2열 · 페이지 넘김) ── */}
      <section className="sec">
        <div className="sh big">
          <span className="t">리포트 히스토리</span>
          <span className="c">{history.length}건</span>
          <span className="s">날짜를 누르면 그 날짜 리포트가 열립니다</span>
        </div>

        <div className="arch">
          <div className="rlist show-old">
            {pageItems.map((r) => (
              <article
                className="ritem"
                key={r.date}
                role="button"
                tabIndex={0}
                onClick={() => openReport(r.date)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openReport(r.date);
                  }
                }}
              >
                <div className="rhd">
                  <span className="rd">{r.label}</span>
                  <span className="rk">{r.day}</span>
                </div>
                <h4 className="rt">{r.title}</h4>
                <p className="rsum">{r.summary}</p>
                <div className="rmeta">
                  이슈 {r.issues}건 · 위키 갱신 {r.wiki}
                  <span className={`cf ${LEVEL_CLASS[r.level]}`.trim()}>
                    <i></i>신뢰도 : {LEVEL_LABEL[r.level]}
                  </span>
                </div>
                <div className="rdl" onClick={(e) => e.stopPropagation()}>
                  {FORMATS.map((f) => (
                    <button
                      className="dlbtn"
                      key={f.key}
                      onClick={() => handleDownload(r.date, f.key, `${r.label} ${f.label}${f.ext}`)}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </div>

          {history.length === 0 && (
            <div className="rlist-empty">이전 리포트가 아직 없습니다.</div>
          )}

          {totalPages > 1 && (
            <nav className="rpage" aria-label="리포트 히스토리 페이지">
              <button
                className="rpage-btn"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                aria-label="이전 페이지"
              >
                ‹
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                <button
                  className={`rpage-btn${n === page ? ' on' : ''}`}
                  key={n}
                  onClick={() => setPage(n)}
                  aria-current={n === page ? 'page' : undefined}
                >
                  {n}
                </button>
              ))}
              <button
                className="rpage-btn"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                aria-label="다음 페이지"
              >
                ›
              </button>
            </nav>
          )}
        </div>
      </section>

      {/* 전체 리포트 모달 — 오늘 카드 · 히스토리 카드가 공유합니다 */}
      {open && (
        <ReportDetailModal
          detail={detail ?? null}
          loading={detail === undefined}
          highlightId={open.highlightId}
          formats={FORMATS}
          onDownload={handleModalDownload}
          onSelectWiki={onSelectWiki}
          onClose={() => setOpen(null)}
        />
      )}

      {notice && <div className="dl-toast" role="status">{notice}</div>}
    </>
  );
}
