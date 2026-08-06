// 개인정보 처리방침 — footer의 "개인정보 처리방침" 링크가 여는 최소 페이지.
// 법무 검토를 거친 실제 약관이 아니라 자리만 잡아둔 플레이스홀더입니다. 실제 문구가
// 나오면 이 파일의 본문만 교체하면 됩니다.

export default function PrivacyPage({ onBack }) {
  return (
    <section className="view on">
      <div className="ph">
        <h2>개인정보 처리방침</h2>
        {onBack && (
          <button type="button" className="ob-linklike" onClick={onBack} style={{ marginLeft: 'auto' }}>
            ← 돌아가기
          </button>
        )}
      </div>
      <div className="sec">
        <p style={{ fontSize: 13, lineHeight: 1.8, color: 'var(--ink-2)', maxWidth: 640 }}>
          myWiki는 서비스 제공을 위해 최소한의 개인정보(계정 이메일, 로그인 제공자 정보,
          선호 키워드)만 수집합니다. 수집한 정보는 로그인 유지와 맞춤 콘텐츠 추천 목적에만
          사용하며, 이용자 동의 없이 제3자에게 제공하지 않습니다. 이 페이지는 정식 약관이
          확정되기 전 자리만 잡아둔 안내문입니다.
        </p>
      </div>
    </section>
  );
}
