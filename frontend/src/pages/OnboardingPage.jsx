// 온보딩 — 선호 조사 화면 (첫 진입)
//
//   진행 단계 바 → "관심사를 알려 주세요" → 관심 키워드(복수, 처음 20개 + 더보기 누를 때마다 20개씩 추가) / 직무(택1)
//   → 하단 "키워드 N개 선택됨 · 건너뛰기 · myWiki 시작하기"
// 연령대 선택은 제거했습니다.
//
// "myWiki 시작하기"를 누르면 선택값이 저장되고 대시보드로 들어가며,
// 대시보드 "최신 뉴스"가 여기서 고른 관심 키워드로 필터링된 상태로 시작합니다.
// "건너뛰기"를 눌러도 곧장 대시보드로 넘어갑니다(App.jsx handleOnboardingComplete).
//
// 마크업은 globals.css에 이미 있던 온보딩 클래스(.ob-screen/.ob-card/.ob-step/.ob-chip/.ob-next …)를
// 그대로 씁니다. 새로 추가한 건 화면 가운데 정렬용 .ob-stage 하나뿐입니다.

import { useState } from 'react';
import {
  ONBOARDING_STEPS,
  INTEREST_KEYWORDS,
  ROLE_OPTIONS,
} from '../data/mockOnboarding';

// 처음엔 이 개수만 보여주고, "더보기"를 누를 때마다 이 개수만큼씩 추가로 펼칩니다
// (한 번에 전체를 펼치지 않음 — 목록이 길어지면 .ob-chips가 스크롤됩니다).
const INTEREST_KEYWORDS_PAGE_SIZE = 20;

export default function OnboardingPage({
  onComplete,
  // 아래 2개는 정적 목업 캡처용으로만 씁니다. 실제 앱에서는 넘기지 않습니다.
  initialKeywords = [],
  initialRole = null,
}) {
  const [keywords, setKeywords] = useState(initialKeywords);
  const [role, setRole] = useState(initialRole);
  const [visibleCount, setVisibleCount] = useState(INTEREST_KEYWORDS_PAGE_SIZE);

  const visibleKeywords = INTEREST_KEYWORDS.slice(0, visibleCount);
  const hasMore = visibleCount < INTEREST_KEYWORDS.length;

  function toggleKeyword(word) {
    setKeywords((prev) =>
      prev.includes(word) ? prev.filter((w) => w !== word) : [...prev, word]
    );
  }

  function finish(selectedKeywords) {
    onComplete?.({ keywords: selectedKeywords, role });
  }

  return (
    <div className="ob-stage">
      <div className="ob-screen on">
        <div className="ob-card">
          <div className="ob-steps">
            {ONBOARDING_STEPS.map((s) => (
              <span className={`ob-step${s.state ? ` ${s.state}` : ''}`} key={s.label}>
                {s.label}
              </span>
            ))}
          </div>

          <div className="ob-h">관심사를 알려 주세요</div>
          <div className="ob-sub">
            선택한 항목은 워크스페이스에 저장되어 수집 키워드·이슈 랭킹·리포트 우선순위에
            반영됩니다.
          </div>

          {/* 관심 키워드 — 복수 선택 */}
          <div className="ob-q">
            <div className="ob-q-t">
              관심 키워드
              <span className="ob-q-s">복수 선택</span>
            </div>
            <div className={`ob-chips${visibleCount > INTEREST_KEYWORDS_PAGE_SIZE ? ' scrollable' : ''}`}>
              {visibleKeywords.map((w) => (
                <button
                  type="button"
                  key={w}
                  className={`ob-chip${keywords.includes(w) ? ' sel' : ''}`}
                  onClick={() => toggleKeyword(w)}
                >
                  {w}
                </button>
              ))}
              {hasMore && (
                <button
                  type="button"
                  className="ob-chip ob-more"
                  onClick={() =>
                    setVisibleCount((c) =>
                      Math.min(c + INTEREST_KEYWORDS_PAGE_SIZE, INTEREST_KEYWORDS.length)
                    )
                  }
                >
                  더보기 +
                  {Math.min(INTEREST_KEYWORDS_PAGE_SIZE, INTEREST_KEYWORDS.length - visibleCount)}
                </button>
              )}
            </div>
          </div>

          {/* 직무 — 택 1 */}
          <div className="ob-q">
            <div className="ob-q-t">
              직무
              <span className="ob-q-s">택 1</span>
            </div>
            <div className="ob-chips">
              {ROLE_OPTIONS.map((r) => (
                <button
                  type="button"
                  key={r}
                  className={`ob-chip${role === r ? ' sel' : ''}`}
                  onClick={() => setRole((prev) => (prev === r ? null : r))}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          <div className="ob-actions">
            <span className="ob-selnote">키워드 {keywords.length}개 선택됨</span>
            <button type="button" className="ob-skip" onClick={() => finish([])}>
              건너뛰기
            </button>
            <button type="button" className="ob-next" onClick={() => finish(keywords)}>
              myWiki 시작하기
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
