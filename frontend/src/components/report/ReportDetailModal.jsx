// 전체 리포트 상세 모달 (수정사항 5-1)
//
// 어디서 뜨는가:
//  · 오늘 리포트 큰 카드 클릭
//  · 리포트 히스토리 카드 클릭
//  두 곳 모두 같은 컴포넌트를 씁니다.
//
// ⚠ 카드형 목록이 아니라 그냥 이어지는 본문 + 출처만 보여줍니다.
//   (히스토리 카드·이슈 카드처럼 테두리 친 박스를 또 넣으면 "카드 안에 카드" 꼴이라
//   총평 문단 뒤에 이슈 문단들이 이어지는 읽는 글 형태로 뒀습니다. 강조도 박스가 아니라
//   문단 안 제목 색만 바꿉니다.)
//
// ⚠ 추가: 각 이슈 문단 아래에 다운로드 버튼(Word/PDF/PPT)을 붙였습니다.
//   백엔드가 아직 이슈 단위 파일 분리를 지원하지 않아, 실제로는 그 날짜 리포트 전체가
//   요청됩니다(토스트 라벨에만 어떤 이슈에서 눌렀는지 남습니다).
//   reportApi.downloadReport가 이슈 id를 받게 되면 onDownload만 바꾸면 됩니다.
//
// 모달 틀(.mw-scrim / .mw-modal / .mw-hd / .mw-body)은 카테고리 뉴스·위키 키워드 모달과 같은
// 시안 클래스를 그대로 재사용합니다. 리포트 전용 요소만 .rdm-* 클래스로 globals.css 끝에 추가했습니다.
//
// 하단 "출처" 목록은 별도 데이터가 아니라 issues[]의 sourceUrl을 중복 제거해서 만듭니다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { DownloadBadge } from './ReportSection';

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };

function collectSources(issues) {
  const seen = new Map();
  issues.forEach((issue) => {
    if (!issue.sourceUrl || seen.has(issue.sourceUrl)) return;
    seen.set(issue.sourceUrl, {
      url: issue.sourceUrl,
      label: issue.sourceLabel,
      title: issue.sourceTitle,
      isDoc: issue.sourceIsDoc,
    });
  });
  return [...seen.values()];
}

export default function ReportDetailModal({
  detail,
  loading = false,
  highlightId = null,
  formats = [],
  onDownload,
  onSelectWiki,
  onClose,
}) {
  // 이 컴포넌트는 열려 있을 때만 마운트되므로(부모가 {open && ...}로 감쌉니다)
  // 여기서는 로딩 / 없음 / 본문 세 가지만 구분하면 됩니다.
  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    // 모달이 떠 있는 동안 배경 스크롤을 잠가서 뒤 화면이 같이 움직이지 않게 한다
    // (.view/.main 조상에 걸린 애니메이션·필터가 fixed 모달의 containing block이
    //  돼버리는 문제의 근본 해결은 아래 createPortal이 하지만, 스크롤 잠금도 같이 걸어야
    //  모달이 열려 있는 동안 뒤 페이지가 안 움직인다는 기대에 맞는다). 이 컴포넌트는
    // 열려 있을 때만 마운트되므로 open 게이트 없이 마운트/언마운트에 걸면 된다.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const issues = detail?.issues ?? [];
  const sources = collectSources(issues);
  const canDownload = formats.length > 0 && typeof onDownload === 'function';

  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open rdm" role="dialog" aria-modal="true" aria-label="전체 리포트">
        <div className="mw-hd">
          <div>
            <div className="eb">
              REPORT · {detail ? `${detail.label}${detail.day ? ` (${detail.day})` : ''}` : '불러오는 중'}
            </div>
            <h3>{detail ? detail.title : '전체 리포트'}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {loading ? (
            <div className="rdm-empty">리포트를 불러오는 중…</div>
          ) : !detail ? (
            <div className="rdm-empty">해당 날짜의 리포트를 찾지 못했습니다.</div>
          ) : (
            <>
              <div className="rdm-meta">
                <span>이슈 {detail.issueCount}건</span>
                <span>위키 갱신 {detail.wikiCount}</span>
                <span>신뢰도 : {LEVEL_LABEL[detail.level]}</span>
              </div>

              {/* 리포트 전체 다운로드 */}
              {canDownload && (
                <div className="rdm-dl whole">
                  <span className="lb">리포트 전체</span>
                  {formats.map((f) => (
                    <button
                      className="dlbtn"
                      key={f.key}
                      onClick={() => onDownload(null, f)}
                    >
                      <DownloadBadge formatKey={f.key} />
                      {f.label} <span className="ext">{f.ext}</span>
                    </button>
                  ))}
                </div>
              )}

              <p className="rdm-overview">{detail.overview}</p>

              {issues.length === 0 ? (
                <div className="rdm-empty">이 날짜의 이슈 본문이 아직 준비되지 않았습니다.</div>
              ) : (
                <div className="rdm-body">
                  {issues.map((issue) => (
                    <div className="rdm-item" key={issue.id}>
                      <p className={`rdm-p${highlightId === issue.id ? ' on' : ''}`}>
                        <span className="ct">{issue.category} · 신뢰도 : {LEVEL_LABEL[issue.level]}</span>
                        <b className="rdm-title">{issue.title}</b>{issue.summary}
                        {' '}
                        <a
                          className={`s${issue.sourceIsDoc ? ' doc' : ''}`}
                          href={issue.sourceUrl}
                          target="_blank"
                          rel="noopener"
                          title={issue.sourceTitle}
                        >
                          {issue.sourceLabel}
                        </a>
                        {issue.wikiTitle && (
                          <a
                            className="w"
                            href="#"
                            onClick={(e) => {
                              e.preventDefault();
                              onSelectWiki?.(issue.wikiId ?? issue.wikiTitle);
                              onClose?.();
                            }}
                          >
                            {issue.wikiTitle}
                          </a>
                        )}
                      </p>

                      {canDownload && (
                        <div className="rdm-dl">
                          {formats.map((f) => (
                            <button
                              className="dlbtn"
                              key={f.key}
                              onClick={() => onDownload(issue, f)}
                            >
                              <DownloadBadge formatKey={f.key} />
                              {f.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <div className="mw-lb">출처 원문 {sources.length}건</div>
              {sources.length === 0 ? (
                <div className="rdm-empty">연결된 출처가 없습니다.</div>
              ) : (
                <div className="kwm-list">
                  {sources.map((s) => (
                    <a
                      className={`kwm-item${s.isDoc ? ' doc' : ''}`}
                      key={s.url}
                      href={s.url}
                      target="_blank"
                      rel="noopener"
                    >
                      <span className="ic" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M7 17 17 7M9 7h8v8" />
                        </svg>
                      </span>
                      <span className="tx">
                        <b>{s.label}</b>
                        <span className="s">{s.title}</span>
                      </span>
                    </a>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}

// 데이터는 services/reportApi.js의 fetchReportDetail(date) → data/mockReport.js의 MOCK_REPORT_DETAILS 입니다.
