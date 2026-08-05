/** @type {import('tailwindcss').Config} */
export default {
  // globals.css의 기존 시안 클래스와 부딪히지 않도록 프리플라이트(리셋)는 끕니다.
  // 팀원이 점진적으로 컴포넌트 단위로 Tailwind를 도입할 수 있도록, 기존 CSS는 그대로 두고
  // Tailwind 유틸리티 클래스만 추가로 쓸 수 있게 하는 구성입니다.
  content: ['./index.html', './src/**/*.{js,jsx}'],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {},
  },
  plugins: [],
};
