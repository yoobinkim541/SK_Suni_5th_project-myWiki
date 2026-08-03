// 일일 리포트 페이지 목업 데이터 모음
// ReportPage → ReportSummary / ReportSection 으로 내려갑니다.
// 실제 API가 생기면 services/reportApi.js가 같은 모양(shape)으로 만들어서 넘겨주면 됩니다.

// ---------- 상단 처리 현황 KPI (ReportSummary) ----------
export const MOCK_REPORT_SUMMARY = {
  date: '2026.07.24 금요일',
  statusLabel: '수집 파이프라인 정상',
  kpis: [
    { label: '수집 문서', value: '312', desc: '전일 +48' },
    { label: '정제 후 채택', value: '86', desc: '중복·광고 226 제거' },
    { label: '선별 이슈', value: '14', desc: '6개 분류' },
    { label: '위키 갱신', value: '6', desc: '신규 2 · 수정 4' },
  ],
  totalLabel: '전체 14건',
  categories: [
    { name: '전체', count: 14 },
    { name: '제품·기술', count: 5 },
    { name: '경쟁사', count: 2 },
    { name: '고객·수요산업', count: 3 },
    { name: '공급망·생산', count: 2 },
    { name: '정책·규제', count: 1 },
    { name: '시장·경영', count: 1 },
  ],
  keywords: ['HBM4', '엔비디아', '수출통제', 'M15X', 'TSMC N2', 'AI 가속기'],
};

// ---------- 주요 이슈 (ReportSection → IssueList) ----------
// level 값은 대시보드 MOCK_ISSUES와 동일한 규약(high/mid/low)을 씁니다.
export const MOCK_REPORT_ISSUES = [
  {
    id: 'r1',
    level: 'mid',
    category: '제품·기술',
    title: 'HBM4 양산 일정 전망 재조정 가능성',
    summary: '주요 메모리 업체의 HBM4 양산 일정이 당초 계획 대비 조정될 수 있다는 업계 전망이 복수 매체에서 나왔다. 확정 발표는 아직 없다.',
    sourceIsDoc: false,
    sourceLabel: '뉴스 5건',
    sourceUrl: 'https://www.etnews.com',
    sourceTitle: '전자신문 외 4개 매체 · 대표 기사 열기',
    wikiId: 'hbm4',
    wikiTitle: 'HBM 기술 로드맵',
  },
  {
    id: 'r2',
    level: 'high',
    category: '공급망·생산',
    title: '청주 M15X 신규 설비 투자 공시 접수',
    summary: '신규 설비 투자 관련 공시가 금융감독원에 접수됐다. 투자 규모와 완공 일정은 원문에 명시돼 있다.',
    sourceIsDoc: true,
    sourceLabel: '공시 원문',
    sourceUrl: 'https://dart.fss.or.kr',
    sourceTitle: '전자공시시스템(DART) 원문 열기',
    wikiId: 'm15x',
    wikiTitle: '청주 M15X 팹 현황',
  },
  {
    id: 'r3',
    level: 'low',
    category: '정책·규제',
    title: '대중 반도체 장비 수출 통제 추가 논의',
    summary: '통제 품목 확대를 논의 중이라는 보도가 나왔으나 공식 확인과 시행 일정은 불명확하다. 매체 간 서술 차이가 있어 교차 검증 대상으로 표시했다.',
    sourceIsDoc: false,
    sourceLabel: '뉴스 2건',
    sourceUrl: 'https://zdnet.co.kr',
    sourceTitle: 'ZDNet Korea 외 1개 매체 · 대표 기사 열기',
    wikiId: 'hbm4',
    wikiTitle: '미국 수출통제 동향',
  },
  {
    id: 'r4',
    level: 'high',
    category: '고객·수요산업',
    title: '엔비디아 분기 실적 공식 발표',
    summary: '데이터센터 부문 매출 비중이 확대됐다고 공식 자료에서 밝혔다. AI 가속기 수요 흐름과 직접 연결되는 항목이다.',
    sourceIsDoc: true,
    sourceLabel: 'IR 원문',
    sourceUrl: 'https://investor.nvidia.com/financial-info/quarterly-results/',
    sourceTitle: 'NVIDIA IR 원문 열기',
    wikiId: 'nvidia',
    wikiTitle: '엔비디아 실적 트래커',
  },
];

// ---------- 리포트 보관 · 내보내기 (ReportSection 하단) ----------
export const MOCK_REPORT_ARCHIVE = [
  { date: '2026-07-24', label: '2026.07.24', day: '금 · 오늘', title: 'HBM4 양산 일정 재조정 가능성 외 13건', summary: 'HBM4 양산 일정 조정 전망과 청주 M15X 신규 설비 투자 공시가 같은 날 확인됐다.', issues: 14, wiki: 6, level: 'mid', old: false },
  { date: '2026-07-23', label: '2026.07.23', day: '목', title: '엔비디아 분기 실적 발표 · 수요 전망 정리', summary: '데이터센터 매출 비중 확대가 공식 자료로 확인되며 AI 가속기 수요 문서 4건이 갱신됐다.', issues: 12, wiki: 4, level: 'high', old: false },
  { date: '2026-07-21', label: '2026.07.21', day: '화', title: '청주 M15X 신규 설비 투자 공시 접수', summary: '신규 시설투자 공시가 접수돼 공급망·생산 분류 비중이 전주 대비 상승했다.', issues: 15, wiki: 5, level: 'mid', old: false },
  { date: '2026-06-24', label: '2026.06.24', day: '수', title: '메모리 현물가 반등 구간 진입', summary: 'D램·낸드 현물가가 3주 연속 상승하며 업턴 진입 여부가 쟁점으로 올라왔다.', issues: 11, wiki: 3, level: 'mid', old: true },
  { date: '2026-06-12', label: '2026.06.12', day: '금', title: 'TSMC N2 시험 생산 관련 보도 정리', summary: '2나노 시험 생산 개시 보도가 나왔으나 공식 확인은 되지 않아 교차 검증 대상으로 뒀다.', issues: 9, wiki: 2, level: 'low', old: true },
];

export const MOCK_REPORT_TODAY = {
  label: '2026.07.24 일일 동향 보고서 · 이슈 14건',
  date: '2026-07-24',
};

// ---------- 전체 리포트 상세 (ReportDetailModal) ----------
// 날짜(YYYY-MM-DD)를 키로, 그 날짜 리포트의 본문 전체를 담습니다.
// 주요 이슈 섹션의 "오늘 리포트" 카드 / 이슈 행 / 리포트 히스토리 카드가 전부 여기를 봅니다.
//  · overview  : 리포트 총평 2~3문장
//  · issues    : 그 날짜에 선별된 이슈. 대시보드 MOCK_ISSUES와 같은 shape이라 IssueList 규약을 그대로 씁니다.
//              → 모달 하단 "출처" 목록은 이 배열의 sourceUrl을 중복 제거해서 자동으로 만듭니다(별도 데이터 없음).
//  wikiId는 data/mockWiki.js에 실제로 있는 문서 id만 씁니다(hbm4 / dram / pkg / micron / samsung / nvidia / m15x).
export const MOCK_REPORT_DETAILS = {
  '2026-07-24': {
    overview:
      'HBM4 양산 일정 조정 전망과 청주 M15X 신규 설비 투자 공시가 같은 날 확인됐습니다. 공시·IR 원문으로 확인된 건은 2건이고, 나머지는 보도 기반이라 교차 검증 대상으로 표시했습니다.',
    issues: MOCK_REPORT_ISSUES,
  },
  '2026-07-23': {
    overview:
      '엔비디아 분기 실적이 IR 원문으로 공개되면서 데이터센터 수요 흐름이 수치로 확인됐습니다. 관련 위키 문서 4건이 같은 날 갱신됐습니다.',
    issues: [
      {
        id: 'd0723-1',
        level: 'high',
        category: '고객·수요산업',
        title: '엔비디아 분기 실적 — 데이터센터 매출 비중 확대',
        summary: '분기 실적 자료에서 데이터센터 부문 매출 비중이 전 분기 대비 확대됐다고 공식 확인됐다.',
        sourceIsDoc: true,
        sourceLabel: 'IR 원문',
        sourceUrl: 'https://investor.nvidia.com/financial-info/quarterly-results/',
        sourceTitle: 'NVIDIA IR 원문 열기',
        wikiId: 'nvidia',
        wikiTitle: '엔비디아 실적 트래커',
      },
      {
        id: 'd0723-2',
        level: 'mid',
        category: '제품·기술',
        title: '차세대 AI 가속기 로드맵 언급',
        summary: '실적 발표 자리에서 차세대 가속기 일정이 언급됐다는 보도가 이어졌으나 세부 사양은 공개되지 않았다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 3건',
        sourceUrl: 'https://www.etnews.com',
        sourceTitle: '전자신문 외 2개 매체 · 대표 기사 열기',
        wikiId: 'hbm4',
        wikiTitle: 'HBM4',
      },
      {
        id: 'd0723-3',
        level: 'mid',
        category: '시장·경영',
        title: '메모리 수요 전망 상향 코멘트',
        summary: '가속기 수요 확대에 맞춰 메모리 수요 전망을 올려 잡는 증권가 코멘트가 복수로 나왔다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 2건',
        sourceUrl: 'https://zdnet.co.kr',
        sourceTitle: 'ZDNet Korea 외 1개 매체 · 대표 기사 열기',
        wikiId: 'dram',
        wikiTitle: 'DRAM 공정',
      },
    ],
  },
  '2026-07-21': {
    overview:
      '청주 M15X 신규 시설투자 공시가 접수돼 공급망·생산 분류 비중이 전주 대비 올라갔습니다. 투자 규모와 완공 일정은 공시 원문에 명시돼 있습니다.',
    issues: [
      {
        id: 'd0721-1',
        level: 'high',
        category: '공급망·생산',
        title: '청주 M15X 신규 시설투자 공시 접수',
        summary: '신규 시설투자 공시가 금융감독원에 접수됐다. 투자 규모·완공 일정이 원문에 그대로 적혀 있다.',
        sourceIsDoc: true,
        sourceLabel: '공시 원문',
        sourceUrl: 'https://dart.fss.or.kr',
        sourceTitle: '전자공시시스템(DART) 원문 열기',
        wikiId: 'm15x',
        wikiTitle: '청주 M15X 팹 현황',
      },
      {
        id: 'd0721-2',
        level: 'mid',
        category: '공급망·생산',
        title: '장비 발주 일정 관련 협력사 코멘트',
        summary: '설비 발주가 순차적으로 진행될 것이라는 협력사 코멘트가 나왔으나 발주 시점은 특정되지 않았다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 2건',
        sourceUrl: 'https://www.etnews.com',
        sourceTitle: '전자신문 외 1개 매체 · 대표 기사 열기',
        wikiId: 'm15x',
        wikiTitle: '청주 M15X 팹 현황',
      },
      {
        id: 'd0721-3',
        level: 'low',
        category: '정책·규제',
        title: '팹 증설 인허가 절차 진행 보도',
        summary: '지자체 인허가 절차가 진행 중이라는 단일 매체 보도로, 공식 확인은 되지 않았다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 1건',
        sourceUrl: 'https://zdnet.co.kr',
        sourceTitle: 'ZDNet Korea · 기사 열기',
        wikiId: 'm15x',
        wikiTitle: '청주 M15X 팹 현황',
      },
    ],
  },
  '2026-06-24': {
    overview:
      'D램·낸드 현물가가 3주 연속 오르면서 업턴 진입 여부가 쟁점으로 올라왔습니다. 전부 보도·시황 기반이라 신뢰도는 보통 이하로 잡았습니다.',
    issues: [
      {
        id: 'd0624-1',
        level: 'mid',
        category: '시장·경영',
        title: 'D램 현물가 3주 연속 상승',
        summary: '주요 시황 집계에서 D램 현물가가 3주 연속 올랐다. 계약가 반영 여부는 아직 확인되지 않았다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 4건',
        sourceUrl: 'https://www.etnews.com',
        sourceTitle: '전자신문 외 3개 매체 · 대표 기사 열기',
        wikiId: 'dram',
        wikiTitle: 'DRAM 공정',
      },
      {
        id: 'd0624-2',
        level: 'mid',
        category: '제품·기술',
        title: '낸드 감산 기조 유지 관측',
        summary: '주요 업체가 감산 기조를 당분간 유지할 것이라는 관측이 나왔다. 공식 입장은 없다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 2건',
        sourceUrl: 'https://zdnet.co.kr',
        sourceTitle: 'ZDNet Korea 외 1개 매체 · 대표 기사 열기',
        wikiId: 'samsung',
        wikiTitle: '삼성전자',
      },
      {
        id: 'd0624-3',
        level: 'low',
        category: '경쟁사',
        title: '경쟁사 가동률 상향 보도',
        summary: '경쟁사가 일부 라인 가동률을 올렸다는 보도가 단일 매체에서 나왔다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 1건',
        sourceUrl: 'https://www.etnews.com',
        sourceTitle: '전자신문 · 기사 열기',
        wikiId: 'micron',
        wikiTitle: '마이크론',
      },
    ],
  },
  '2026-06-12': {
    overview:
      'TSMC 2나노 시험 생산 보도가 나왔으나 공식 확인이 되지 않아 전체를 교차 검증 대상으로 뒀습니다. 이날 리포트는 공시·IR 원문 없이 보도 기반만으로 구성됐습니다.',
    issues: [
      {
        id: 'd0612-1',
        level: 'low',
        category: '경쟁사',
        title: 'TSMC N2 시험 생산 개시 보도',
        summary: '2나노 시험 생산이 시작됐다는 보도가 나왔으나 회사 공식 확인은 없었다. 매체 간 일정 서술이 엇갈린다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 2건',
        sourceUrl: 'https://zdnet.co.kr',
        sourceTitle: 'ZDNet Korea 외 1개 매체 · 대표 기사 열기',
        wikiId: 'pkg',
        wikiTitle: '차세대 패키징',
      },
      {
        id: 'd0612-2',
        level: 'mid',
        category: '제품·기술',
        title: '2나노 공정 고객사 확보 관련 언급',
        summary: '초기 고객사 확보 상황이 업계 취재로 언급됐다. 계약 여부와 물량은 확인되지 않았다.',
        sourceIsDoc: false,
        sourceLabel: '뉴스 2건',
        sourceUrl: 'https://www.etnews.com',
        sourceTitle: '전자신문 외 1개 매체 · 대표 기사 열기',
        wikiId: 'pkg',
        wikiTitle: '차세대 패키징',
      },
    ],
  },
};
