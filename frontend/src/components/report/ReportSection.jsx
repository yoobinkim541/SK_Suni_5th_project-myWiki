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
  { key: 'word', label: 'Word', ext: '.docx', availabilityKey: 'hasDocx' },
  { key: 'pdf', label: 'PDF', ext: '.pdf', availabilityKey: 'hasPdf' },
  { key: 'ppt', label: 'PPT', ext: '.pptx', availabilityKey: 'hasPptx' },
];

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: '', mid: 'mid', low: 'low' };

// 히스토리 한 페이지에 보여줄 개수 (2열 × 3줄). 숫자만 바꾸면 됩니다.
const PAGE_SIZE = 6;

// 아이콘 배지 — Word/PDF/PPT 각각 오피스 색상의 둥근 사각 배지에 짧은 라벨을 넣는다.
const BADGE_TEXT = { word: 'W', pdf: 'PDF', ppt: 'P' };

export function DownloadBadge({ formatKey }) {
  return (
    <span className={`dlbadge dlbadge-${formatKey}`} aria-hidden="true">
      {BADGE_TEXT[formatKey] || ''}
    </span>
  );
}

export default function ReportSection({ archive, today, summary, historyError, onSelectWiki }) {
  const [notice, setNotice] = useState('');
  const [page, setPage] = useState(1);

  // ── 전체 리포트 모달 상태 ──
  // open : { date, highlightId } — 어떤 날짜 리포트를, 어떤 이슈를 강조한 채로 열지
  // detail : fetchReportDetail 결과. undefined = 불러오는 중, null = 그 날짜 리포트 없음.
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(undefined);

  // 오늘 리포트는 히스토리에서 빼고 위쪽 큰 카드로만 보여줍니다(중복 방지).
  const safeArchive = useMemo(
    () => (Array.isArray(archive) ? archive : []),
    [archive]
  );

  const history = useMemo(
    () => safeArchive.filter((r) => r.date !== today?.date),
    [safeArchive, today]
  );

  const todayCard = useMemo(
    () => safeArchive.find((r) => r.date === today?.date) ?? today?.archiveItem ?? null,
    [safeArchive, today]
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

  // 다운로드 API가 없던 시절의 목업 버튼에서 실제 백엔드 다운로드 호출로 전환했습니다.
  function canDownload(report, format) {
    if (!report || !format.availabilityKey) return true;
    if (!Object.prototype.hasOwnProperty.call(report, format.availabilityKey)) return true;
    return Boolean(report[format.availabilityKey]);
  }

  function formatIssueCount(value) {
    const count = Number(value ?? 0);
    return Number.isFinite(count) ? count : 0;
  }

  function renderWikiCount(value) {
    const count = Number(value);
    return Number.isFinite(count) ? <> ? ?? ?? {count}</> : null;
  }

  async function handleDownload(date, format, label) {
    const res = await downloadReport(date, format);
    setNotice(
      res?.ok
        ? `${label} 다운로드를 시작했습니다.`
        : `${date} · ${label} 다운로드에 실패했습니다. 잠시 후 다시 시도해주세요.`
    );
    window.clearTimeout(handleDownload._t);
    handleDownload._t = window.setTimeout(() => setNotice(''), 3200);
  }

  return (
    <>
      {/* ── 오늘 리포트 (큰 카드) ── */}
      <section className="sec sr-2">
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
              {todayCard.summary && <p className="rsum">{todayCard.summary}</p>}
              {summary?.statusLabel !== '\uC0DD\uC131 \uB300\uAE30' && (
                <div className="rmeta">
                  ?? {formatIssueCount(todayCard.issues)}?{renderWikiCount(todayCard.wiki)}
                  {todayCard.level && (
                    <span className={`cf ${LEVEL_CLASS[todayCard.level]}`.trim()}>
                      <i></i>??? : {LEVEL_LABEL[todayCard.level]}
                    </span>
                  )}
                </div>
              )}
            </>
          )}

          {/* 카드 클릭(모달 열기)과 분리 — 버튼을 눌러도 모달이 뜨지 않습니다. */}
          <div className="rdl wide" onClick={(e) => e.stopPropagation()}>
            {FORMATS.map((f) => {
              const disabled = !canDownload(todayCard, f);
              return (
                <button
                  className="dlbtn"
                  key={f.key}
                  disabled={disabled}
                  onClick={() => {
                    if (!disabled) handleDownload(today.date, f.key, `${f.label}${f.ext}`);
                  }}
                  title={disabled ? '\uC0DD\uC131\uB41C \uD30C\uC77C\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.' : undefined}
                >
                  <DownloadBadge formatKey={f.key} />
                  {f.label} <span className="ext">{f.ext}</span>
                </button>
              );
            })}
          </div>
        </article>
      </section>

      {/* ── 리포트 히스토리 (2열 · 페이지 넘김) ── */}
      <section className="sec sr-3">
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
                {r.summary && <p className="rsum">{r.summary}</p>}
                <div className="rdl" onClick={(e) => e.stopPropagation()}>
                  {FORMATS.map((f) => {
                    const disabled = !canDownload(r, f);
                    return (
                      <button
                        className="dlbtn"
                        key={f.key}
                        disabled={disabled}
                        onClick={() => {
                          if (!disabled) handleDownload(r.date, f.key, `${r.label} ${f.label}${f.ext}`);
                        }}
                        title={disabled ? '\uC0DD\uC131\uB41C \uD30C\uC77C\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.' : undefined}
                      >
                        <DownloadBadge formatKey={f.key} />
                        {f.label}
                      </button>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>

          {history.length === 0 && (
            <div className="rlist-empty">
              {historyError || '?? ???? ?? ????.'}
            </div>
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
          onDownload={(issue, format) =>
            handleDownload(
              open.date,
              format.key,
              issue
                ? `${detail?.label ?? open.date} ${format.label}${format.ext}`
                : `전체 ${format.label}${format.ext}`,
            )
          }
          onSelectWiki={onSelectWiki}
          onClose={() => setOpen(null)}
        />
      )}

      {notice && <div className="dl-toast" role="status">{notice}</div>}
    </>
  );
}
