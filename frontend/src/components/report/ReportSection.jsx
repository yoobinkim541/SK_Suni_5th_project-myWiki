// 일일 리포트 전용 — 주요 이슈(+즉시 다운로드) + 리포트 보관 · 내보내기
//
// ⚠ 수정사항 5) 반영 내용:
//  1) "주요 이슈" 섹션이 리포트에서 사실상 첫 본문 섹션이 됐습니다.
//     (이슈 목록 위에 있던 다운로드 바는 5-1에서 이슈별 다운로드 버튼으로 대체됐습니다 — 아래 참고)
//  2) 아래 "리포트 보관 · 내보내기" 섹션은 그대로 유지합니다.
//     · 전체 다운로드(오늘 리포트 3개 포맷 + 전체 묶음)
//     · 이전 리포트 보관함(.rlist, 30일 이전은 토글로 펼침)
//
// ⚠ 수정사항 5-1) 주요 이슈 섹션 개편:
//  a) 이슈 목록 위에 있던 다운로드 바(.dlbar.tight)를 없애고, 각 이슈 행 .meta 안에
//     그 이슈 바로 아래로 다운로드 버튼(Word/PDF/PPT)을 붙였습니다 — IssueList의
//     downloadFormats/onDownload prop으로 전달합니다. (버튼은 stopPropagation이라
//     눌러도 아래 b)의 모달이 같이 열리지 않습니다)
//  b) 이슈 행을 클릭하면 리포트 히스토리 카드와 같은 전체 리포트 모달이 뜹니다.
//     카드형 목록이 아니라 총평에 이어 이슈들이 이어지는 본문 텍스트 + 출처 원문만 보여주고,
//     그 이슈 문단은 제목 색으로만 강조합니다(ReportDetailModal.jsx 참고).
//     히스토리 카드도 같은 모달을 씁니다 — "카드를 누르면 전체 리포트와 출처를 볼 수 있습니다"
//     안내문이 말만 있고 실제 핸들러가 없던 것도 이번에 같이 붙였습니다.
//
//  주요 이슈는 대시보드와 같은 IssueList를 그대로 재사용합니다
//  (신뢰도 "신뢰도 : 구간명" 표기와 하단 신뢰도 필터 범례까지 함께 따라옵니다).

import { useEffect, useState } from 'react';
import IssueList from '../dashboard/IssueList';
import ReportDetailModal from './ReportDetailModal';
import { downloadReport, fetchReportDetail } from '../../services/reportApi';

const FORMATS = [
  { key: 'word', label: 'Word', ext: '.docx' },
  { key: 'pdf', label: 'PDF', ext: '.pdf' },
  { key: 'ppt', label: 'PPT', ext: '.pptx' },
];

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: '', mid: 'mid', low: 'low' };

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"></path>
      <path d="M14 3v5h5"></path>
      <path d="M12 12v6M9 15l3 3 3-3"></path>
    </svg>
  );
}

export default function ReportSection({ issues, archive, today, onSelectWiki }) {
  const [showOld, setShowOld] = useState(false);
  const [notice, setNotice] = useState('');
  const oldCount = archive.filter((r) => r.old).length;

  // ── 전체 리포트 모달 상태 ──
  // open : { date, highlightId } — 어떤 날짜 리포트를, 어떤 이슈를 강조한 채로 열지
  // detail : fetchReportDetail 결과. 날짜가 바뀔 때마다 다시 받아옵니다.
  //          undefined = 아직 불러오는 중, null = 그 날짜 리포트가 없음.
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(undefined);

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

  // 이슈별 다운로드 버튼 — 실제 파일은 그 날짜 리포트 전체로 나가지만(백엔드 미연동이라
  // 이슈 단위 파일 분리는 아직 없음), 토스트 라벨에는 어떤 이슈에서 눌렀는지 남깁니다.
  function handleIssueDownload(issue, format) {
    handleDownload(today.date, format.key, `${issue.title} · ${format.label}${format.ext}`);
  }

  return (
    <>
      {/* ── 주요 이슈 (다운로드 버튼 동봉) ── */}
      <section className="sec">
        <div className="sh">
          <span className="t">주요 이슈</span>
          <span className="c">{issues.length}건</span>
          <span className="s">신뢰도 → 제목 → 출처 순</span>
        </div>

        <IssueList
          items={issues}
          onSelectWiki={onSelectWiki}
          onOpenIssue={(issue) => openReport(today.date, issue.id)}
          downloadFormats={FORMATS}
          onDownload={handleIssueDownload}
        />
      </section>

      {/* ── 리포트 보관 · 내보내기 (전체 다운로드 + 보관함 유지) ── */}
      <section className="sec">
        <div className="sh">
          <span className="t">리포트 보관 · 내보내기</span>
          <span className="s">최근 30일 노출 · 이전 보관함 별도 조회</span>
        </div>

        {/* 전체 다운로드 */}
        <div className="dlbar">
          <span className="lb">전체 다운로드 · {today.label}</span>
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

        {/* 30일 보관함 */}
        <div className="arch">
          <div className="arch-hd">
            <span className="t">리포트 히스토리</span>
            <span className="s">카드를 누르면 전체 리포트와 출처를 볼 수 있습니다</span>
          </div>

          <div className={`rlist${showOld ? ' show-old' : ''}`}>
            {archive.map((r) => (
              <article
                className={`ritem${r.old ? ' old' : ''}`}
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

          {oldCount > 0 && (
            <button className={`archtoggle${showOld ? ' open' : ''}`} onClick={() => setShowOld((v) => !v)}>
              {showOld ? '이전 리포트 접기' : '30일 이전 리포트 보기'}
              <span className="cnt">{oldCount}</span>
              <span className="chev">▾</span>
            </button>
          )}
        </div>
      </section>

      {/* 전체 리포트 모달 — 이슈 행 · 히스토리 카드가 공유합니다 */}
      {open && (
        <ReportDetailModal
          detail={detail ?? null}
          loading={detail === undefined}
          highlightId={open.highlightId}
          onSelectWiki={onSelectWiki}
          onClose={() => setOpen(null)}
        />
      )}

      {notice && <div className="dl-toast" role="status">{notice}</div>}
    </>
  );
}
