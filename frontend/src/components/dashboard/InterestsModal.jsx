// 대시보드 "관심 키워드" 전체 보기 / 추가·삭제 모달.
//
// 로그인 직후 선호조사(OnboardingPage)에서 고르는 관심 키워드와는 별개의 진입점입니다 —
// 그건 첫 가입 때 한 번 거치는 온보딩이고, 이건 대시보드에서 언제든 다시 열어 키워드를
// 추가·삭제할 수 있는 상시 관리 화면입니다. 데이터는 같은 사전(mockOnboarding.js의
// INTEREST_KEYWORD_GROUPS)을 재사용해서 온보딩 화면과 카테고리 체계가 어긋나지 않게 합니다.
//
// 모달 틀은 WikiKeywordModal.jsx/CategoryNewsModal.jsx가 쓰는 것과 같은 .mw-modal/.mw-scrim
// 시안 클래스를 그대로 씁니다. 칩 체크는 온보딩 화면의 .ob-chip 스타일을 재사용합니다.

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { INTEREST_KEYWORD_GROUPS } from '../../data/mockOnboarding';

export default function InterestsModal({ open, initialKeywords = [], onClose, onSave }) {
  const [selected, setSelected] = useState(initialKeywords);

  // 열릴 때마다 현재 저장된 관심사로 다시 초기화(이전에 취소했던 임시 선택이 안 남게).
  useEffect(() => {
    if (open) setSelected(initialKeywords);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    // 모달이 떠 있는 동안 배경 스크롤을 잠가서 뒤 화면이 같이 움직이지 않게 한다
    // (.view/.main 조상에 걸린 애니메이션·필터가 fixed 모달의 containing block이
    //  돼버리는 문제의 근본 해결은 아래 createPortal이 하지만, 스크롤 잠금도 같이 걸어야
    //  모달이 열려 있는 동안 뒤 페이지가 안 움직인다는 기대에 맞는다).
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  function toggle(word) {
    setSelected((prev) => (prev.includes(word) ? prev.filter((w) => w !== word) : [...prev, word]));
  }

  function handleSave() {
    onSave?.(selected);
    onClose?.();
  }

  // document.body에 포털로 그린다 — .view/.main 조상에 걸린 진입 애니메이션·필터가
  // position:fixed 자식의 containing block이 되어 버려서(브라우저 스펙상 transform/filter가
  // 있는 조상은 그 자체가 기준점이 된다), 그 안에 두면 모달이 "뷰포트 중앙 고정"이 아니라
  // 그 조상 박스 기준으로 붙어 페이지를 스크롤할 때 같이 움직여 보인다. body 바로 아래로
  // 빼내면 그 문제가 원천적으로 없어진다.
  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="관심 키워드 관리">
        <div className="mw-hd">
          <div>
            <div className="eb">관심 키워드 · {selected.length}개 선택됨</div>
            <h3>관심 키워드 관리</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <p className="kwm-desc">
            선택한 키워드는 대시보드 "최신 뉴스" 필터에 바로 반영됩니다. 언제든 추가·삭제할 수
            있습니다.
          </p>
          {INTEREST_KEYWORD_GROUPS.map((group) => (
            <div key={group.category} style={{ marginBottom: 18 }}>
              <div className="mw-lb">{group.category}</div>
              <div className="ob-chips">
                {group.keywords.map((word) => (
                  <button
                    type="button"
                    key={word}
                    className={`ob-chip${selected.includes(word) ? ' sel' : ''}`}
                    onClick={() => toggle(word)}
                  >
                    {word}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="ob-actions" style={{ padding: '0 26px 22px' }}>
          <span className="ob-selnote">{selected.length}개 선택됨</span>
          <button type="button" className="ob-skip" onClick={onClose}>취소</button>
          <button type="button" className="ob-next" onClick={handleSave}>저장</button>
        </div>
      </div>
    </>,
    document.body
  );
}
