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
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  function toggle(word) {
    setSelected((prev) => (prev.includes(word) ? prev.filter((w) => w !== word) : [...prev, word]));
  }

  function handleSave() {
    onSave?.(selected);
    onClose?.();
  }

  return (
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
    </>
  );
}
