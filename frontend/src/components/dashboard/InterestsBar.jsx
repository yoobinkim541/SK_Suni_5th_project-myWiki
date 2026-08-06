// 대시보드 상단 — 관심 키워드 칩(빠른 삭제) + 추가 + 전체 보기.
//
// 로그인 시 선호조사(OnboardingPage)에서 고르는 관심 키워드와는 별개로, 대시보드에서
// 언제든 빠르게 추가·삭제할 수 있게 하는 위젯입니다. 칩의 ✕를 누르면 그 키워드만 바로
// 빠지고, "+ 추가" 또는 "전체 보기"를 누르면 전체 카테고리별 키워드 사전을 볼 수 있는
// InterestsModal이 열립니다(추가·전체 관리는 모달 하나로 통일 — 버튼 두 개가 같은 모달을
// 여는 서로 다른 진입점인 셈입니다).
//
// 저장은 App.jsx의 onUpdateInterests(App.jsx updateInterests → localStorage 'mywiki-interests')
// 로 위임합니다. 온보딩 때 저장하는 것과 같은 키를 쓰므로, 여기서 바꾼 값은 설정 화면의
// "관심사 다시 고르기"에도 그대로 반영됩니다.

import { useState } from 'react';
import InterestsModal from './InterestsModal';

export default function InterestsBar({ interests = [], onUpdateInterests }) {
  const [modalOpen, setModalOpen] = useState(false);

  function removeInterest(word) {
    onUpdateInterests?.(interests.filter((w) => w !== word));
  }

  return (
    <section className="sec">
      <div className="sh">
        <span className="t">관심 키워드</span>
        <span className="s">대시보드 최신 뉴스 필터에 바로 반영됩니다</span>
        <span className="r">
          <a onClick={() => setModalOpen(true)}>전체 보기 →</a>
        </span>
      </div>
      <div className="kwchips">
        {interests.length === 0 && (
          <span className="kwm-desc" style={{ margin: 0 }}>
            아직 고른 관심 키워드가 없습니다. "추가"를 눌러 골라보세요.
          </span>
        )}
        {interests.map((word) => (
          <span className="kwchip on" key={word}>
            {word}
            <button
              type="button"
              className="kwchip-x"
              aria-label={`${word} 관심 키워드 삭제`}
              title="삭제"
              onClick={() => removeInterest(word)}
            >
              ✕
            </button>
          </span>
        ))}
        <button type="button" className="kwchip ob-more" onClick={() => setModalOpen(true)}>
          + 추가
        </button>
      </div>

      <InterestsModal
        open={modalOpen}
        initialKeywords={interests}
        onClose={() => setModalOpen(false)}
        onSave={(next) => onUpdateInterests?.(next)}
      />
    </section>
  );
}
