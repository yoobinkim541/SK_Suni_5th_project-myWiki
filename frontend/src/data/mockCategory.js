// 카테고리 현황 페이지 목업 데이터 모음
// CategoryPage → CategoryDetail → CategoryRow → CategoryCard로 내려가는 데이터가
// 전부 이 파일 하나에서 나옵니다. 실제 API가 생기면 이 파일 대신 fetch 결과를
// 같은 모양(shape)으로 만들어서 CategoryPage에서 내려주면 됩니다.

// ---------- 분류별 상세 카드 (CategoryRow → CategoryCard) ----------
export const MOCK_CATEGORIES = [
  {
    id: 'product-tech',
    name: '제품·기술',
    count: 5,
    topIssue: 'HBM4 양산 일정 전망 재조정 가능성',
    tags: ['HBM4', 'AI 가속기', 'TSMC N2'],
    level: 'mid',
  },
  {
    id: 'customer-demand',
    name: '고객·수요산업',
    count: 3,
    topIssue: '엔비디아 분기 실적 공식 발표',
    tags: ['엔비디아', '데이터센터', 'AI 서버'],
    level: 'high',
  },
  {
    id: 'competitor',
    name: '경쟁사',
    count: 2,
    topIssue: '삼성전자 파운드리 수율 개선 발표',
    tags: ['삼성전자', '마이크론', 'TSMC'],
    level: 'high',
  },
  {
    id: 'supply-chain',
    name: '공급망·생산',
    count: 2,
    topIssue: '청주 M15X 신규 설비 투자 공시 접수',
    tags: ['M15X', '청주', '설비투자'],
    level: 'high',
  },
  {
    id: 'policy',
    name: '정책·규제',
    count: 1,
    topIssue: '대중 반도체 장비 수출 통제 추가 논의',
    tags: ['수출통제', '대중 규제'],
    level: 'low',
  },
  {
    id: 'market',
    name: '시장·경영',
    count: 1,
    topIssue: '메모리 업체 3분기 실적 전망 상향',
    tags: ['실적발표', 'DRAM 가격'],
    level: 'mid',
  },
];

// ---------- 오늘의 분류 요약 (CategoryDetail 상단 KPI 4개) ----------
export const MOCK_SUMMARY = {
  totalLabel: '전체 14건 · 6개 분류',
  topCategory: { value: '제품·기술', desc: '36% · 5건' },
  maxIncrease: { value: '+2건', desc: '제품·기술' },
  newCategory: { value: '고객·수요산업', desc: '전일 미분류 → 3건' },
  // 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값 그대로 사용)
  avgConfidence: { value: '보통', desc: '전일 대비 소폭 하락' },
};

// ---------- 카테고리별 키워드 분포 (CategoryKeywordPie, 원그래프) ----------
// 수정사항 6) "카테고리 현황 — 우리 키워드 중심으로 내부에 어떤 키워드가 있는지 원그래프로 시각화"
//
// 여기서 말하는 "우리 키워드"는 수집 파이프라인이 실제로 걸어둔 수집 키워드입니다.
// count = 최근 7일간 그 키워드로 걸려 들어온 문서 수(중복 제거 후 채택 기준).
//
// ⚠ 실제 API 연동 시에는 GET /api/categories/keyword-stats 같은 집계 엔드포인트가
//    { categoryId, keywords: [{ word, count }] } 모양으로 내려주면
//    아래 상수만 그 응답으로 교체하면 됩니다. 컴포넌트는 손댈 필요가 없습니다.
export const MOCK_CATEGORY_KEYWORDS = {
  'product-tech': [
    { word: 'HBM4', count: 9 },
    { word: '패키징', count: 5 },
    { word: 'TSMC N2', count: 4 },
    { word: 'GAA', count: 3 },
    { word: '양산일정', count: 3 },
    { word: 'D램 공정', count: 2 },
  ],
  'customer-demand': [
    { word: '엔비디아', count: 6 },
    { word: '데이터센터', count: 5 },
    { word: 'AI 서버', count: 3 },
    { word: '수주', count: 2 },
  ],
  competitor: [
    { word: '삼성전자', count: 4 },
    { word: '마이크론', count: 3 },
    { word: 'TSMC', count: 3 },
    { word: '파운드리 수율', count: 2 },
  ],
  'supply-chain': [
    { word: 'M15X', count: 5 },
    { word: '설비투자', count: 4 },
    { word: '후공정', count: 3 },
    { word: '원재료 수급', count: 2 },
  ],
  policy: [
    { word: '수출통제', count: 4 },
    { word: '보조금', count: 3 },
    { word: '대중 규제', count: 2 },
    { word: '시행령', count: 1 },
  ],
  market: [
    { word: '현물가', count: 4 },
    { word: '실적전망', count: 3 },
    { word: '가이던스', count: 2 },
    { word: '업턴', count: 2 },
  ],
};

// getCategoryTotals는 제거했습니다.
// 왼쪽 원그래프를 "카테고리별 키워드 합계"로 계산하던 함수인데, 그 값이 카드의 건수와
// 달라서 한 화면에 두 숫자가 어긋나 보였습니다(합계 89 vs 427). 이제 왼쪽 파이는
// 카드와 같은 c.count를 쓰고, 그 계산은 CategoryKeywordChart 안에 한 줄로 들어 있습니다.
