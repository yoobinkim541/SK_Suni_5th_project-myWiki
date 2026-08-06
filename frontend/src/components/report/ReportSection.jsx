// ?? ??? ?? ? ?? ??? ?? + ??? ????
//
// ? ?? ?? ??:
//  1) "?? ??" ??(IssueList 4?)? ?????.
//     ? ???? ?? ??? "?? ???? ??? ?? ?"??, ??? ?? 4??
//       ??? ???? ?? ?? ??? ?? ??? ???? ?????.
//  2) ?? ???? ? ?? ??? ????. ??? ??? ?? ??? ??? ??,
//     ?? ?? ???? ??(Word/PDF/PPT)? ?? ??? ??? ????.
//  3) ?????? ???(ReportSummary)? '?? ???' ??? ? ?? ??? ?????.
//  4) ??? ????? ? ?? ?? ??? 2? ????, ??? ??? ??? ?????.
//     ? ?? "30? ?? ??? ??" ??(archive? old ???)? ?????.
//       ??? ?? ??? ???? ??? ? ?? ?????.
//
// ??? ?? ReportDetailModal? ??? ??? ? ?? ??? ???? ??? ?????.

import { useEffect, useMemo, useState } from 'react';
import ReportDetailModal from './ReportDetailModal';
import ReportSummary from './ReportSummary';
import { downloadReport, fetchReportDetail } from '../../services/reportApi';

const FORMATS = [
  { key: 'word', label: 'Word', ext: '.docx' },
  { key: 'pdf', label: 'PDF', ext: '.pdf' },
  { key: 'ppt', label: 'PPT', ext: '.pptx' },
];

const LEVEL_LABEL = { high: '??', mid: '??', low: '??' };
const LEVEL_CLASS = { high: '', mid: 'mid', low: 'low' };

// ???? ? ???? ??? ?? (2? ? 3?). ??? ??? ???.
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

  // ?? ?? ??? ?? ?? ??
  // open : { date, highlightId } ? ?? ?? ????, ?? ??? ??? ?? ??
  // detail : fetchReportDetail ??. undefined = ???? ?, null = ? ?? ??? ??.
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(undefined);

  // ?? ???? ?????? ?? ?? ? ???? ?????(?? ??).
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

  // ??? ?? ?? ???? ???? ??? ???? ?????.
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

  function buildDownloadNotice(result, label, date) {
    if (result?.ok && result?.generated) {
      return `${date} ???? ?? ??? ? ${label} ????? ??????.`;
    }

    if (result?.ok) {
      return `${label} ????? ??????.`;
    }

    return `${date} ? ${label} ????? ??????. ${result?.reason ?? '?? ? ?? ??????.'}`;
  }

  async function handleDownload(date, format, label) {
    const res = await downloadReport(date, format);
    setNotice(buildDownloadNotice(res, label, date));
    window.clearTimeout(handleDownload._t);
    handleDownload._t = window.setTimeout(() => setNotice(''), 3200);
  }

  return (
    <>
      {/* ?? ?? ??? (? ??) ?? */}
      <section className="sec">
        <div className="sh big">
          <span className="t">?? ???</span>
          <span className="s">??? ??? ?? ???? ??? ? ? ????</span>
        </div>

        {/* ?? ?? ? ??? ??? ?? ?? ??? ??? ? ?? ?? */}
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
                ?? {todayCard.issues}? ? ?? ?? {todayCard.wiki}
                <span className={`cf ${LEVEL_CLASS[todayCard.level]}`.trim()}>
                  <i></i>??? : {LEVEL_LABEL[todayCard.level]}
                </span>
              </div>
            </>
          )}

          {/* ?? ??(?? ??)? ?? ? ??? ??? ??? ?? ????. */}
          <div className="rdl wide" onClick={(e) => e.stopPropagation()}>
            {FORMATS.map((f) => (
              <button
                className="dlbtn"
                key={f.key}
                onClick={() => handleDownload(today.date, f.key, `?? ${f.label}${f.ext}`)}
              >
                <DownloadIcon />
                {f.label} <span className="ext">{f.ext}</span>
              </button>
            ))}
          </div>
        </article>
      </section>

      {/* ?? ??? ???? (2? ? ??? ??) ?? */}
      <section className="sec">
        <div className="sh big">
          <span className="t">??? ????</span>
          <span className="c">{history.length}?</span>
          <span className="s">??? ??? ? ?? ???? ????</span>
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
                  ?? {r.issues}? ? ?? ?? {r.wiki}
                  <span className={`cf ${LEVEL_CLASS[r.level]}`.trim()}>
                    <i></i>??? : {LEVEL_LABEL[r.level]}
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
            <div className="rlist-empty">?? ???? ?? ????.</div>
          )}

          {totalPages > 1 && (
            <nav className="rpage" aria-label="??? ???? ???">
              <button
                className="rpage-btn"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                aria-label="?? ???"
              >
                ?
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
                aria-label="?? ???"
              >
                ?
              </button>
            </nav>
          )}
        </div>
      </section>

      {/* ?? ??? ?? ? ?? ?? ? ???? ??? ????? */}
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
                : `?? ${format.label}${format.ext}`,
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
