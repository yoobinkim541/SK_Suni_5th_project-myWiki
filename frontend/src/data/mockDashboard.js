// 메인 대시보드 목업 데이터 모음
// 백엔드 연동 전까지 DashboardPage와 그 하위 컴포넌트(IssueList/TrendChart/CategoryPreview)가
// 전부 이 파일 하나에서 데이터를 가져다 씁니다. 실제 API가 생기면 이 파일 대신
// fetch 결과를 같은 모양(shape)으로 만들어서 넘겨주면 컴포넌트 쪽은 손댈 필요가 없습니다.

// ---------- 최신 뉴스 (news-feed) ----------
// isDoc: 공시·IR 등 원문 문서 링크인지 여부 (true면 카드 상단 링크가 "공시 원문"+아래화살표 아이콘으로 표시)
export const MOCK_NEWS = [
  { category: '제품·기술', title: 'HBM4 양산 일정 전망 재조정 가능성', quote: '차세대 HBM4 초기 양산 시점이 당초 계획보다 한 분기가량 늦춰질 수 있다는 관측이 나온다.', tags: ['HBM4', '양산일정', '패키징'], isDoc: false, sourceLabel: '전자신문', sourceUrl: 'https://www.etnews.com', time: '12분 전' },
  { category: '고객·수요산업', title: '엔비디아 분기 실적 공식 발표', quote: '데이터센터 부문 매출이 전년 동기 대비 크게 늘며 AI 서버향 메모리 수요 확대 전망에 힘이 실렸다.', tags: ['실적발표', '데이터센터'], isDoc: false, sourceLabel: '로이터', sourceUrl: 'https://www.reuters.com', time: '38분 전' },
  { category: '공급망·생산', title: '청주 M15X 신규 설비 투자 공시 접수', quote: '청주 M15X 라인 신규 설비 증설을 위한 투자 계획이 전자공시시스템에 정식 접수됐다.', tags: ['설비투자', '청주M15X'], isDoc: true, sourceLabel: '전자공시', sourceUrl: 'https://dart.fss.or.kr', time: '1시간 전' },
  { category: '경쟁사', title: '삼성전자 파운드리 수율 개선 발표', quote: '신규 공정 라인 수율이 목표치를 넘어서며 파운드리 경쟁 구도에 변수로 작용할 전망이다.', tags: ['파운드리', '수율'], isDoc: false, sourceLabel: '비즈니스워치', sourceUrl: 'https://news.bizwatch.co.kr', time: '1시간 전' },
  { category: '정책·규제', title: '대중 반도체 장비 수출 통제 추가 논의', quote: '첨단 노드 공정 장비 일부 품목을 수출 통제 대상에 추가하는 방안이 관계 부처 간 논의되고 있다.', tags: ['수출통제', '대중정책'], isDoc: false, sourceLabel: '연합뉴스', sourceUrl: 'https://www.yna.co.kr', time: '2시간 전' },
  { category: '시장·경영', title: '메모리 업체 3분기 실적 전망 상향', quote: '현물가 상승세가 이어지며 주요 증권사가 메모리 3사의 영업이익 전망치를 일제히 높여 잡았다.', tags: ['실적전망', '현물가'], isDoc: false, sourceLabel: '한국경제', sourceUrl: 'https://www.hankyung.com', time: '2시간 전' },
  { category: '제품·기술', title: 'TSMC N2 공정 시험 생산 개시', quote: '2나노 공정 기반 시험 생산 라인이 가동을 시작하며 파운드리 업계의 차세대 공정 경쟁이 본격화되는 모습이다.', tags: ['2나노', '시험생산'], isDoc: false, sourceLabel: '디일렉', sourceUrl: 'https://www.thelec.kr', time: '3시간 전' },
  { category: '고객·수요산업', title: 'AI 서버향 메모리 수요 재조정', quote: '일부 하이퍼스케일러의 데이터센터 증설 일정이 조정되며 관련 메모리 발주 물량 변동 가능성이 제기됐다.', tags: ['서버메모리', '발주'], isDoc: false, sourceLabel: '디지털투데이', sourceUrl: 'https://www.digitaltoday.co.kr', time: '3시간 전' },
  { category: '공급망·생산', title: '후공정 패키징 라인 증설 검토', quote: 'HBM 수요 대응을 위한 후공정 패키징 설비 증설이 내부적으로 검토 단계에 있는 것으로 확인됐다.', tags: ['후공정', '패키징'], isDoc: false, sourceLabel: '전자신문', sourceUrl: 'https://www.etnews.com', time: '4시간 전' },
  { category: '경쟁사', title: '마이크론 신규 D램 라인 가동', quote: '마이크론이 신규 D램 생산 라인 가동을 시작하며 메모리 공급 지형에 변화가 예상된다.', tags: ['마이크론', 'D램'], isDoc: false, sourceLabel: '로이터', sourceUrl: 'https://www.reuters.com', time: '5시간 전' },
  { category: '정책·규제', title: '반도체 보조금 법안 실행령 발표', quote: '반도체 보조금 지급 기준을 구체화한 시행령이 공식 발표되며 관련 기업의 신청 절차가 본격화될 전망이다.', tags: ['보조금', '시행령'], isDoc: false, sourceLabel: '연합뉴스', sourceUrl: 'https://www.yna.co.kr', time: '5시간 전' },
  { category: '시장·경영', title: '메모리 현물가 3주 연속 상승', quote: 'D램·낸드 현물 가격이 3주 연속 상승세를 이어가며 업턴 국면 진입 여부에 관심이 쏠린다.', tags: ['현물가', '업턴'], isDoc: false, sourceLabel: '한국경제', sourceUrl: 'https://www.hankyung.com', time: '6시간 전' },
  { category: '제품·기술', title: '차세대 GAA 공정 로드맵 공개', quote: '차세대 GAA 트랜지스터 공정 로드맵이 공개되며 미세공정 경쟁의 다음 단계가 윤곽을 드러냈다.', tags: ['GAA', '로드맵'], isDoc: false, sourceLabel: '디일렉', sourceUrl: 'https://www.thelec.kr', time: '7시간 전' },
  { category: '고객·수요산업', title: '데이터센터향 신규 수주 확대', quote: '글로벌 데이터센터 사업자로부터의 신규 수주가 확대되며 관련 부품 공급망에 훈풍이 불고 있다.', tags: ['데이터센터', '수주'], isDoc: false, sourceLabel: '비즈니스워치', sourceUrl: 'https://news.bizwatch.co.kr', time: '8시간 전' },
  { category: '공급망·생산', title: '원재료 수급 안정화 전망', quote: '주요 원재료 수급 계약이 갱신되며 하반기 생산 안정성이 한층 높아질 것이라는 전망이 나온다.', tags: ['원재료', '수급'], isDoc: true, sourceLabel: '전자공시', sourceUrl: 'https://dart.fss.or.kr', time: '9시간 전' },
  { category: '시장·경영', title: '업계 4분기 가이던스 상향 조정', quote: '주요 업체들이 4분기 실적 가이던스를 상향 조정하며 업황 회복 기대감이 커지고 있다.', tags: ['가이던스', '업황'], isDoc: false, sourceLabel: '한국경제', sourceUrl: 'https://www.hankyung.com', time: '10시간 전' },
];

// ---------- 최근 산업 이슈 (IssueList) ----------
export const MOCK_ISSUES = [
  {
    id: 1,
    level: 'high',
    category: '공급망·생산',
    title: '청주 M15X 신규 설비 투자 공시 접수',
    summary: '신규 설비 투자 관련 공시가 금융감독원에 접수됐다. 투자 규모와 완공 일정은 원문에 명시돼 있다.',
    sourceIsDoc: true,
    sourceLabel: '공시 원문',
    sourceUrl: 'https://dart.fss.or.kr',
    sourceTitle: '전자공시시스템(DART) 원문 열기',
    wikiId: 'm15x-fab',
    wikiTitle: '청주 M15X 팹 현황',
  },
  {
    id: 2,
    level: 'high',
    category: '고객·수요산업',
    title: '엔비디아 분기 실적 공식 발표',
    summary: '데이터센터 부문 매출 비중이 확대됐다고 공식 자료에서 밝혔다. AI 가속기 수요 흐름과 직접 연결된다.',
    sourceIsDoc: true,
    sourceLabel: 'IR 원문',
    sourceUrl: 'https://investor.nvidia.com/financial-info/quarterly-results/',
    sourceTitle: 'NVIDIA IR 원문 열기',
    wikiId: 'nvidia-earnings',
    wikiTitle: '엔비디아 실적 트래커',
  },
  {
    id: 3,
    level: 'mid',
    category: '제품·기술',
    title: 'HBM4 양산 일정 전망 재조정 가능성',
    summary: '주요 메모리 업체의 HBM4 양산 일정이 당초 계획 대비 조정될 수 있다는 업계 전망이 복수 매체에서 나왔다.',
    sourceIsDoc: false,
    sourceLabel: '뉴스 5건',
    sourceUrl: 'https://www.etnews.com',
    sourceTitle: '전자신문 외 4개 매체 · 대표 기사 열기',
    wikiId: 'hbm-roadmap',
    wikiTitle: 'HBM 기술 로드맵',
  },
];

// ---------- 산업 동향 분석 (TrendChart) — 최근 7일 ----------
export const MOCK_TREND = [
  { date: '07.18', collected: 274, adopted: 79 },
  { date: '07.19', collected: 281, adopted: 84 },
  { date: '07.20', collected: 265, adopted: 71 },
  { date: '07.21', collected: 288, adopted: 91 },
  { date: '07.22', collected: 276, adopted: 83 },
  { date: '07.23', collected: 283, adopted: 88 },
  { date: '07.24', collected: 312, adopted: 86 },
];

// ---------- 카테고리 현황 미리보기 (CategoryPreview, 대시보드 하단 좌측) ----------
export const MOCK_CATEGORY_PREVIEW = [
  { id: 'product-tech', name: '제품·기술', issueTitle: 'HBM4 양산 일정 조정 가능성', count: 5, level: 'mid' },
  { id: 'customer-demand', name: '고객·수요산업', issueTitle: '엔비디아 분기 실적 공식 발표', count: 3, level: 'high' },
  { id: 'competitor', name: '경쟁사', issueTitle: '삼성전자 파운드리 수율 개선 발표', count: 2, level: 'high' },
  { id: 'supply-chain', name: '공급망·생산', issueTitle: '청주 M15X 신규 설비 투자 공시 접수', count: 2, level: 'high' },
  { id: 'policy', name: '정책·규제', issueTitle: '대중 반도체 장비 수출 통제 추가 논의', count: 1, level: 'low' },
  { id: 'market', name: '시장·경영', issueTitle: '메모리 업체 3분기 실적 전망 상향', count: 1, level: 'mid' },
];

// ---------- 오늘의 키워드 ----------
export const MOCK_KEYWORDS = [
  { word: 'HBM4', count: 9 },
  { word: '엔비디아', count: 6 },
  { word: '수출통제', count: 4 },
  { word: 'M15X', count: 3 },
  { word: 'TSMC N2', count: 3 },
  { word: 'AI 가속기', count: 2 },
];

// ---------- 최근 현황 (KpiCard 4개) ----------
// ⚠ 원래 DashboardPage.jsx에 숫자가 그대로 박혀 있던 걸(312, 18, 124, 보통) 데이터로 뺐습니다.
//   그래야 services/dashboardApi.js를 거쳐서 실제 API 값으로 교체할 수 있습니다.
export const MOCK_KPI_SUMMARY = {
  collectedDocs: { value: '312', desc: { text: '오늘', highlight: '+48' } },
  generatedReports: { value: '18', desc: '자동 생성' },
  wikiDocs: { value: '124', desc: { text: '신규', highlight: '+6' } },
  // 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값 그대로 사용)
  avgConfidence: { value: '보통', desc: '체크리스트 기준' },
};

