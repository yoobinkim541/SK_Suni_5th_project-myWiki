// 온보딩(선호 조사) 화면 목업 데이터
//
// 원래 시안 구성으로 되돌린 버전입니다.
//   · 진행 단계 4개 (사람 확인 → 로그인 → 선호 조사 → 대시보드)
//   · 관심 키워드 (복수 선택) / 직무 (택 1) / 연령대 (택 1)
//
// 여기에 수정사항 1) "관심사를 누르면 관련 키워드 뉴스가 뜨는" 미리보기만 얹었습니다.
// 미리보기는 관심 키워드 그룹에만 적용됩니다(직무·연령대는 뉴스와 무관).
//
// ⚠ 실제 API 연동 시: GET /api/onboarding/options 로 목록을 받고,
//    선택 결과는 POST /api/me/preferences 로 저장하면 됩니다.
//    (지금은 localStorage 'mywiki-interests' 에 저장 — App.jsx 참고)

// 랜딩 페이지(0단계) 기능 소개 카드 4개 — globals.css의 .landing-features/.lf-card 그대로 씀.
export const LANDING_FEATURES = [
  { icon: '📡', title: '자동 수집', desc: '네이버·GNews·전자공시 등 여러 소스에서 반도체 뉴스를 자동 수집합니다' },
  { icon: '✅', title: '신뢰도 검증', desc: '출처·근거를 따져 신뢰도 등급을 매기고 낮은 신뢰도는 걸러냅니다' },
  { icon: '📖', title: '위키 자동 정리', desc: '이슈·기업·기술별로 위키 문서를 자동 생성·갱신합니다' },
  { icon: '🤖', title: 'AI 에이전트', desc: '위키 근거를 바탕으로 질문에 답하고, 답변을 위키에 저장할 수 있습니다' },
];

export const ONBOARDING_STEPS = [
  { label: '1 · 사람 확인', state: 'done' },
  { label: '2 · 로그인', state: 'done' },
  { label: '3 · 선호 조사', state: 'on' },
  { label: '4 · 대시보드', state: '' },
];

// 카테고리별 관심 키워드 — SK hynix 2026 H2 전략 이니셔티브 키워드 사전.
// 화면에는 카테고리 구분 없이 이 순서 그대로 이어붙여 보여줍니다(처음 20개만 노출,
// "더보기"를 누르면 전체가 펼쳐집니다 — OnboardingPage.jsx의 INTEREST_KEYWORDS_VISIBLE_COUNT 참고).
export const INTEREST_KEYWORD_GROUPS = [
  {
    category: '제품·기술',
    keywords: [
      '반도체 제품', '공정', '성능', '연구개발', '신기술', '메모리 기술', '패키징 기술',
      'HBM', 'DRAM', 'NAND', 'DDR', 'LPDDR', '메모리', 'AI 메모리',
    ],
  },
  {
    category: '경쟁사',
    keywords: [
      '삼성전자', 'Samsung', '마이크론', 'Micron', 'TSMC', '인텔', 'Intel', '키옥시아',
      '경쟁사', '벤더 경쟁', '공급 경쟁', '점유율 경쟁', '기술 우위', '가격 경쟁',
      '경쟁사 투자', '경쟁사 실적', '경쟁사 신제품', '경쟁사 양산', '경쟁사 수율',
    ],
  },
  {
    category: '고객·수요산업',
    keywords: [
      'NVIDIA', '엔비디아', 'AMD', 'Apple', 'Microsoft', 'Google', 'Amazon', 'AWS', 'Meta', 'Oracle',
      '고객사', '빅테크', '데이터센터', 'AI 서버', 'GPU', 'AI 가속기', '생성형 AI', '클라우드',
      '스마트폰', 'PC', '자동차', '자율주행', 'HPC', '수요 증가', '수요 둔화', '발주', '채택',
      '공급 요청', '탑재량 증가',
    ],
  },
  {
    category: '공급망·생산',
    keywords: [
      '생산', '양산', '증설', '증산', '감산', '공장', '팹', '생산능력', '캐파', '라인', '장비',
      '소재', '웨이퍼', '부품', '공급망', '공급 부족', '공급 과잉', '병목', '납기', '리드타임',
      '출하', '재고', '수율', '생산 차질', '공급 계약', '운영 정상화', '공급망 재편',
    ],
  },
  {
    category: '정책·규제',
    keywords: [
      '정부 정책', '법률', '보조금', '세제', '관세', '수출 통제', '정책', '규제', '수출 규제',
      '지원 정책', '산업 정책', 'CHIPS Act', '대중국 규제', '미국 규제', '중국 규제', '투자 제한',
      '기술 통제', '제재', '인허가', '정부 지원', '반도체 지원법', '반독점', '환경 규제',
    ],
  },
  {
    category: '시장·경영',
    keywords: [
      '반도체 가격', '시장 규모', '실적', '매출', '영업이익', '수익성', '적자', '흑자', '전망',
      '업황', '가격', 'ASP', '단가', '점유율', '투자', '인수합병', '조직 개편', '경영전략',
      '사업 전략', 'CAPEX', '비용 절감', '수익 개선', '재고 부담', '산업 전망',
    ],
  },
];

// 카테고리 구분 없이 이어붙인 전체 목록. 화면·뉴스 매칭 로직은 이 순서를 그대로 씁니다.
export const INTEREST_KEYWORDS = INTEREST_KEYWORD_GROUPS.flatMap((g) => g.keywords);

export const ROLE_OPTIONS = [
  '전략·기획', '마케팅', '개발·엔지니어링',
  '영업·구매', '경영지원', '학생·취준',
];

// 화면에 찍히는 키워드 이름과 실제 기사 본문의 표기가 달라서(예: DRAM ↔ D램)
// 키워드마다 검색어 별칭을 둡니다. 하나라도 걸리면 관련 기사로 봅니다.
// → 백엔드가 붙으면 이 매핑은 수집 파이프라인의 키워드 사전으로 옮겨가는 게 맞습니다.
export const KEYWORD_ALIASES = {
  HBM: ['HBM'],
  DRAM: ['D램', 'DRAM'],
  낸드플래시: ['낸드'],
  파운드리: ['파운드리'],
  'AI 가속기': ['AI 가속기', 'AI 서버', '데이터센터'],
  설비투자: ['설비투자', '설비 투자'],
  수출규제: ['수출통제', '수출 통제'],
  '실적·IR': ['실적', '가이던스', 'IR'],
};

// 한국어 데이터라 공백·대소문자 차이가 잦아 정규화 후 부분일치로 봅니다.
function normalize(text) {
  return String(text).toLowerCase().replace(/\s+/g, '');
}

export function newsMatchesInterest(news, interest) {
  const terms = KEYWORD_ALIASES[interest] || [interest];
  const haystack = normalize(
    [news.title, news.quote, news.category, news.sourceLabel, ...(news.tags || [])].join(' ')
  );
  return terms.some((t) => haystack.includes(normalize(t)));
}

// 관심 키워드 여러 개 중 하나라도 걸리면 관련 뉴스로 봅니다(OR 조건).
// 비어 있으면 필터를 걸지 않고 전체를 돌려줍니다.
export function filterNewsByInterests(newsList, interests = []) {
  if (!interests.length) return newsList;
  return newsList.filter((n) => interests.some((it) => newsMatchesInterest(n, it)));
}
