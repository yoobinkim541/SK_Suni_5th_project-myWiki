// 위키 페이지 목업 데이터 모음
// WikiPage → WikiCard / CitationTag 로 내려갑니다.
//
// 문서 하나의 모양(shape):
//   id / title / category / updated
//   meta[]   : 상단 .dmeta 에 들어가는 요약 지표
//   zones[]  : { title, paragraphs: [ [텍스트, 근거번호, 텍스트, ...] ] }
//              숫자는 sources 배열의 1-based 인덱스(각주 번호)입니다. 0이면 각주 없음.
//   timeline[]: 변경 이력
//   sourceCount / sources[] : 우측 "근거 출처"
//   links[]  : 우측 "연결된 문서" (클릭하면 해당 문서로 이동)

// 출처 원문(Source Router) 정의 — 각주와 근거 출처 목록이 같은 정의를 공유합니다.
export const WIKI_SOURCES = {
  dart:     { name: '공시 원문',   url: 'https://dart.fss.or.kr', title: '전자공시시스템(DART) 원문 열기' },
  etnews:   { name: '전자신문',    url: 'https://www.etnews.com', title: '전자신문 원문 열기' },
  zdnet:    { name: 'ZDNet Korea', url: 'https://zdnet.co.kr', title: 'ZDNet Korea 원문 열기' },
  reuters:  { name: '로이터',      url: 'https://www.reuters.com', title: '로이터 원문 열기' },
  thelec:   { name: '디일렉',      url: 'https://www.thelec.kr', title: '디일렉 원문 열기' },
  nvidiaIr: { name: 'IR 원문',     url: 'https://investor.nvidia.com/financial-info/quarterly-results/', title: 'NVIDIA IR 원문 열기' },
  hankyung: { name: '한국경제',    url: 'https://www.hankyung.com', title: '한국경제 원문 열기' },
};

// 좌측 문서 목록(트리) — 분류별 그룹
export const MOCK_WIKI_TREE = [
  { group: '제품·기술', items: ['hbm4', 'dram', 'pkg'] },
  { group: '경쟁사', items: ['micron', 'samsung'] },
  { group: '고객·수요산업', items: ['nvidia'] },
  { group: '공급망·생산', items: ['m15x'] },
];

export const MOCK_WIKI_DOCS = {
  hbm4: {
    id: 'hbm4', title: 'HBM4', category: '제품·기술', updated: '2026.07.24',
    meta: ['근거 문서 12건', '연결 문서 3개', '문서 생성 2026.07.20', '평균 신뢰도 보통'],
    zones: [
      { title: '개요', paragraphs: [[
        'HBM4는 고대역폭 메모리의 차세대 규격으로, AI 가속기의 메모리 병목을 완화하는 것을 목표로 논의되고 있다.', 1,
        ' 국내 메모리 제조사와 주요 고객사 사이의 공급 협의가 진행 중인 것으로 보도됐다.', 2,
      ]] },
      { title: '쟁점', paragraphs: [[
        '양산 시점에 대해서는 매체별 서술이 엇갈린다. 공시로 확인된 사항이 아니므로 이 문단은 신뢰도 보통으로 분류했다.', 3,
        ' 관련 설비 투자 안건은 별도 공시로 접수돼 있어, 투자 규모 자체는 원문 검증이 가능하다.', 4,
      ]] },
    ],
    timeline: [
      { date: '07.24', text: '쟁점 문단 갱신', desc: '양산 시점 관련 신규 보도 3건 반영. 기존 서술은 삭제하지 않고 이력에 보존', isNew: true },
      { date: '07.22', text: '연결 추가', desc: '엔비디아 문서와 상호 링크. 근거 2건 추가' },
      { date: '07.20', text: '문서 생성', desc: '초기 근거 5건으로 개요 작성' },
    ],
    sourceCount: 12,
    sources: [
      { key: 'dart', date: '07.21' }, { key: 'etnews', date: '07.24' },
      { key: 'zdnet', date: '07.24' }, { key: 'dart', date: '07.23' },
    ],
    links: [
      { id: 'nvidia', title: '엔비디아', desc: '고객·수요산업 · 상호 링크' },
      { id: 'm15x', title: '청주 M15X 팹 현황', desc: '공급망·생산 · 인용 2' },
      { id: 'micron', title: '마이크론', desc: '경쟁사 · 인용 1' },
    ],
  },

  dram: {
    id: 'dram', title: 'DRAM 공정', category: '제품·기술', updated: '2026.07.23',
    meta: ['근거 문서 8건', '연결 문서 2개', '문서 생성 2026.07.11', '평균 신뢰도 높음'],
    zones: [
      { title: '개요', paragraphs: [['미세공정 전환과 함께 D램 웨이퍼 투입량 대비 생산성 지표가 지속 개선되고 있다는 분석이 나온다.', 1]] },
      { title: '쟁점', paragraphs: [['차세대 노드 전환 시점은 업체별로 다르게 서술되고 있어 교차 검증 대상으로 분류했다.', 2]] },
    ],
    timeline: [
      { date: '07.23', text: '개요 갱신', desc: '공정 전환 관련 보도 2건 반영', isNew: true },
      { date: '07.11', text: '문서 생성', desc: '초기 근거 4건으로 개요 작성' },
    ],
    sourceCount: 8,
    sources: [{ key: 'thelec', date: '07.23' }, { key: 'etnews', date: '07.20' }],
    links: [
      { id: 'hbm4', title: 'HBM4', desc: '제품·기술 · 인용 3' },
      { id: 'samsung', title: '삼성전자', desc: '경쟁사 · 인용 1' },
    ],
  },

  pkg: {
    id: 'pkg', title: '차세대 패키징', category: '제품·기술', updated: '2026.07.22',
    meta: ['근거 문서 6건', '연결 문서 2개', '문서 생성 2026.07.14', '평균 신뢰도 보통'],
    zones: [
      { title: '개요', paragraphs: [['HBM 수요 확대에 따라 후공정 패키징 설비 증설 논의가 이어지고 있다.', 1]] },
      { title: '쟁점', paragraphs: [['증설 규모와 시점은 아직 공시로 확인되지 않아 보도 기반 서술로만 남겨 두었다.', 2]] },
    ],
    timeline: [
      { date: '07.22', text: '쟁점 문단 추가', desc: '증설 검토 보도 반영', isNew: true },
      { date: '07.14', text: '문서 생성', desc: '초기 근거 3건으로 개요 작성' },
    ],
    sourceCount: 6,
    sources: [{ key: 'etnews', date: '07.22' }, { key: 'thelec', date: '07.19' }],
    links: [
      { id: 'hbm4', title: 'HBM4', desc: '제품·기술 · 상호 링크' },
      { id: 'm15x', title: '청주 M15X 팹 현황', desc: '공급망·생산 · 인용 1' },
    ],
  },

  micron: {
    id: 'micron', title: '마이크론', category: '경쟁사', updated: '2026.07.24',
    meta: ['근거 문서 7건', '연결 문서 2개', '문서 생성 2026.07.09', '평균 신뢰도 보통'],
    zones: [
      { title: '개요', paragraphs: [['신규 D램 생산 라인 가동을 시작하며 메모리 공급 지형에 변화가 예상된다는 보도가 나왔다.', 1]] },
      { title: '쟁점', paragraphs: [['가동 규모와 양산 시점은 매체별 서술 차이가 있어 확정 정보로 보기 어렵다.', 2]] },
    ],
    timeline: [
      { date: '07.24', text: '개요 갱신', desc: '신규 라인 가동 보도 반영', isNew: true },
      { date: '07.09', text: '문서 생성', desc: '초기 근거 3건으로 개요 작성' },
    ],
    sourceCount: 7,
    sources: [{ key: 'reuters', date: '07.24' }, { key: 'zdnet', date: '07.21' }],
    links: [
      { id: 'hbm4', title: 'HBM4', desc: '제품·기술 · 인용 1' },
      { id: 'samsung', title: '삼성전자', desc: '경쟁사 · 상호 링크' },
    ],
  },

  samsung: {
    id: 'samsung', title: '삼성전자', category: '경쟁사', updated: '2026.07.24',
    meta: ['근거 문서 9건', '연결 문서 2개', '문서 생성 2026.07.08', '평균 신뢰도 높음'],
    zones: [
      { title: '개요', paragraphs: [['신규 공정 라인 수율이 목표치를 넘어섰다고 발표하며 파운드리 경쟁 구도에 변수로 작용할 전망이다.', 1]] },
      { title: '쟁점', paragraphs: [['수율 수치 자체는 공식 발표 기준이나, 세부 지표는 공개되지 않아 비교 검증에는 한계가 있다.', 2]] },
    ],
    timeline: [
      { date: '07.24', text: '개요 갱신', desc: '수율 개선 발표 반영', isNew: true },
      { date: '07.08', text: '문서 생성', desc: '초기 근거 4건으로 개요 작성' },
    ],
    sourceCount: 9,
    sources: [{ key: 'hankyung', date: '07.24' }, { key: 'thelec', date: '07.22' }],
    links: [
      { id: 'micron', title: '마이크론', desc: '경쟁사 · 상호 링크' },
      { id: 'dram', title: 'DRAM 공정', desc: '제품·기술 · 인용 1' },
    ],
  },

  nvidia: {
    id: 'nvidia', title: '엔비디아 실적 트래커', category: '고객·수요산업', updated: '2026.07.24',
    meta: ['근거 문서 10건', '연결 문서 2개', '문서 생성 2026.07.05', '평균 신뢰도 높음'],
    zones: [
      { title: '개요', paragraphs: [[
        '분기 실적 공식 발표에서 데이터센터 부문 매출 비중이 확대됐다고 밝혔다.', 1,
        ' AI 가속기 수요 흐름과 직접 연결되는 항목이다.',
      ]] },
      { title: '쟁점', paragraphs: [['차기 분기 가이던스에 대한 해석은 매체별로 엇갈려 별도 문단으로 분리했다.', 2]] },
    ],
    timeline: [
      { date: '07.24', text: '개요 갱신', desc: '분기 실적 IR 원문 반영', isNew: true },
      { date: '07.22', text: '연결 추가', desc: 'HBM4 문서와 상호 링크' },
      { date: '07.05', text: '문서 생성', desc: '초기 근거 5건으로 개요 작성' },
    ],
    sourceCount: 10,
    sources: [{ key: 'nvidiaIr', date: '07.24' }, { key: 'reuters', date: '07.24' }],
    links: [
      { id: 'hbm4', title: 'HBM4', desc: '제품·기술 · 상호 링크' },
      { id: 'dram', title: 'DRAM 공정', desc: '제품·기술 · 인용 1' },
    ],
  },

  m15x: {
    id: 'm15x', title: '청주 M15X 팹 현황', category: '공급망·생산', updated: '2026.07.23',
    meta: ['근거 문서 11건', '연결 문서 2개', '문서 생성 2026.06.28', '평균 신뢰도 높음'],
    zones: [
      { title: '개요', paragraphs: [['신규 설비 투자 관련 공시가 금융감독원에 접수됐다. 투자 규모와 완공 일정은 원문에 명시돼 있다.', 1]] },
      { title: '쟁점', paragraphs: [['같은 건을 다룬 보도는 라인 증설 시점을 다르게 서술하고 있어 본문에는 반영하지 않았다.', 2]] },
    ],
    timeline: [
      { date: '07.23', text: '개요 갱신', desc: '신규 설비 투자 공시 반영', isNew: true },
      { date: '07.15', text: '연결 추가', desc: 'HBM4 문서와 상호 링크' },
      { date: '06.28', text: '문서 생성', desc: '초기 근거 6건으로 개요 작성' },
    ],
    sourceCount: 11,
    sources: [{ key: 'dart', date: '07.21' }, { key: 'etnews', date: '07.22' }],
    links: [
      { id: 'hbm4', title: 'HBM4', desc: '제품·기술 · 인용 2' },
      { id: 'pkg', title: '차세대 패키징', desc: '제품·기술 · 인용 1' },
    ],
  },
};

// 대시보드·리포트의 "관련 위키" 링크 이름 → 문서 id
// (아직 문서가 없는 이름은 가장 가까운 문서로 보냅니다)
export const WIKI_ALIAS = {
  HBM4: 'hbm4',
  'HBM 기술 로드맵': 'hbm4',
  '미국 수출통제 동향': 'hbm4',
  'DRAM 공정': 'dram',
  '차세대 패키징': 'pkg',
  마이크론: 'micron',
  삼성전자: 'samsung',
  엔비디아: 'nvidia',
  '엔비디아 실적 트래커': 'nvidia',
  '청주 M15X 팹 현황': 'm15x',
};

export const DEFAULT_WIKI_DOC = 'hbm4';

// ---------- 에이전트 페이지 목업 (위키 문서만 근거로 사용) ----------
// 시안과 동일하게 "팀 공유 에이전트 / 내 에이전트" 두 갈래로 나눠 둡니다.
// paragraphs 안의 숫자는 그 답변의 cites 배열에 있는 근거 번호입니다.

export const MOCK_AGENT_PANES = {
  team: {
    key: 'team',
    label: '팀 공유 에이전트',
    ctx: {
      badge: 'TEAM',
      title: 'Team 5 · 반도체 공유 에이전트',
      desc: '워크스페이스 멤버 4명이 같은 대화와 근거를 함께 봅니다',
      avatars: ['J', 'S', 'H'],
      more: '+1',
    },
    listLabel: '공유 대화',
    newLabel: '+ 새 공유 대화',
    placeholder: '팀 공유 대화로 질문하기 · 멤버 전원에게 보입니다',
    inputLabel: '팀 공유 대화 입력',
    flag: '팀 공유',
    hints: ['위키 124문서만 참조합니다', 'Team 5 멤버 4명이 열람·이어서 질문할 수 있습니다'],
    conversations: [
      {
        id: 'team-hbm4',
        title: 'HBM4 주간 정리',
        meta: '오늘 · 김주현',
        messages: [
          { role: 'me', author: { initial: 'J', name: '김주현' }, text: 'HBM4 관련해서 이번 주에 정리된 내용 알려줘' },
          {
            role: 'ai',
            paragraphs: [
              ['이번 주 HBM4 문서는 두 차례 갱신됐습니다. 공급 협의가 진행 중이라는 내용이 보도로 확인됐고', 1, ', 관련 설비 투자 안건이 공시로 접수됐습니다.', 2],
              ['다만 양산 시점은 매체마다 서술이 달라 확정 정보로 보기 어렵습니다.', 3, ' 공시로 확인된 사항이 아니므로 해당 문단은 신뢰도 보통으로 표시했습니다.'],
            ],
            cites: [{ no: 1, key: 'etnews' }, { no: 2, key: 'dart' }, { no: 3, key: 'zdnet' }],
            acts: ['위키에 저장', '주간 보고서 초안', '복사', '다시 생성'],
          },
          { role: 'me', author: { initial: 'S', name: '이서준' }, text: '내년 HBM4 시장 점유율은 몇 %가 될까?' },
          {
            role: 'ai',
            none: {
              title: '축적된 근거에서 답을 찾지 못했습니다',
              desc: '위키에 해당 수치를 담은 문서가 없어 답변을 생성하지 않았습니다. 시장 전망 자료를 수집 소스에 추가하거나, 확인된 사실 범위로 질문을 좁혀 보세요.',
            },
            acts: ['수집 소스 추가', '관련 문서 찾아보기'],
          },
        ],
        evidence: [
          { no: 1, key: 'etnews', title: 'HBM4 공급 협의 관련 보도', excerpt: '해당 문단 원문 발췌 영역. 인용은 짧게 유지하고 원문 링크로 연결한다.', foot: '2026.07.24 · 신뢰도 보통' },
          { no: 2, key: 'dart', title: '신규 시설투자 관련 공시', excerpt: '정형 데이터라 수치를 그대로 인용할 수 있는 항목.', foot: '2026.07.21 · 신뢰도 높음' },
          { no: 3, key: 'zdnet', title: '양산 일정 관련 보도', excerpt: '매체 간 서술 차이가 있어 교차 검증 대상으로 분류.', foot: '2026.07.24 · 신뢰도 보통' },
        ],
      },
      { id: 'team-export', title: '수출통제 영향 점검', meta: '07.23 · 이서준', messages: [], evidence: [] },
      { id: 'team-nvidia', title: '엔비디아 실적 Q&A', meta: '07.22 · 박하늘', messages: [], evidence: [] },
    ],
  },

  mine: {
    key: 'mine',
    label: '내 에이전트',
    ctx: {
      badge: 'ME',
      title: '김주현 · 개인 에이전트',
      desc: '나만 열람할 수 있습니다. 답변마다 개별 선택으로 팀에 공유합니다.',
      priv: '비공개',
    },
    listLabel: '내 대화',
    newLabel: '+ 새 대화',
    placeholder: '개인 대화로 질문하기 · 나만 볼 수 있습니다',
    inputLabel: '개인 대화 입력',
    flag: '개인',
    flagPriv: true,
    hints: ['위키 124문서만 참조합니다', '공유 전까지 팀에 노출되지 않습니다'],
    conversations: [
      {
        id: 'mine-m15x',
        title: '청주 M15X 공시 확인',
        meta: '오늘',
        messages: [
          { role: 'me', text: '청주 M15X 투자 공시 핵심만 정리해줘' },
          {
            role: 'ai',
            paragraphs: [
              ['신규 설비 투자 공시가 07월 21일 금융감독원에 접수됐습니다.', 1, ' 투자 규모와 완공 일정은 공시 원문에 수치로 명시돼 있어 그대로 인용할 수 있습니다.'],
              ['같은 건을 다룬 보도는 라인 증설 시점을 다르게 서술하고 있어, 해당 문장은 위키에 반영하지 않았습니다.', 2],
            ],
            cites: [{ no: 1, key: 'dart' }, { no: 2, key: 'etnews' }],
            acts: ['팀에 공유', '위키에 저장', '복사', '다시 생성'],
          },
          { role: 'me', text: '이 내용으로 주간 보고서 초안 만들어줘' },
          {
            role: 'ai',
            paragraphs: [
              ['공시로 확인된 항목만 본문에 넣고, 보도 기반 문장은 참고 항목으로 분리한 초안을 만들었습니다. 공급망·생산 분류의 주간 변동 수치도 함께 넣었습니다.', 1],
            ],
            cites: [{ no: 1, key: 'dart' }],
            acts: ['팀에 공유', 'Word로 내보내기', '복사'],
          },
        ],
        evidence: [
          { no: 1, key: 'dart', title: '신규 시설투자 관련 공시', excerpt: '투자 규모·완공 일정이 정형 데이터로 기재된 항목.', foot: '2026.07.21 · 신뢰도 높음' },
          { no: 2, key: 'etnews', title: '청주 라인 증설 관련 보도', excerpt: '증설 시점 서술이 공시와 달라 교차 검증 대상으로 분류.', foot: '2026.07.22 · 신뢰도 보통' },
        ],
      },
      { id: 'mine-tsmc', title: 'TSMC N2 메모', meta: '07.20', messages: [], evidence: [] },
    ],
  },
};

// 입력창으로 질문했을 때 돌려줄 고정 응답(백엔드 연동 전까지)
export const MOCK_AGENT_REPLY = {
  paragraphs: [['위키에 축적된 근거 범위에서 확인한 내용입니다. 공시로 검증된 항목만 본문에 두고, 보도 기반 서술은 신뢰도 보통으로 분리했습니다.', 1]],
  cites: [{ no: 1, key: 'dart' }],
  acts: ['위키에 저장', '복사', '다시 생성'],
};

// ---------- 위키 본문 키워드 → 공시 원문 / 뉴스기사 연동 ----------
// 수정사항 4) "위키 공시 원문 및 뉴스기사 연동 링크 (특정 키워드 누르면 연동)"
//
// 위키 본문에 등장하는 아래 키워드는 자동으로 클릭 가능한 링크(.wiki-kw)가 되고,
// 누르면 그 키워드의 근거가 된 ① 공시·IR 원문과 ② 관련 뉴스기사 목록이 모달로 뜹니다.
// (본문 각주 ①②③ 는 "이 문장의 근거 1건"을 가리키고, 키워드 링크는
//  "이 단어와 엮인 원문·기사 전체"를 모아 보여주는 용도로 역할이 다릅니다.)
//
// ⚠ 실제 API 연동 시: GET /api/wiki/keywords/{word} 가
//    { word, docs: [...], news: [...] } 모양으로 내려주면 이 상수만 교체하면 됩니다.
//    지금은 키가 곧 화면에 찍히는 단어라서, 긴 단어를 먼저 매칭하도록
//    getWikiKeywordList()가 길이 내림차순으로 정렬해 돌려줍니다.
export const WIKI_KEYWORD_LINKS = {
  HBM4: {
    desc: '차세대 고대역폭 메모리 규격. 양산 시점·공급 협의가 주요 쟁점입니다.',
    docs: [
      { label: '공시 원문 · 시설투자 결정', source: '전자공시(DART)', url: 'https://dart.fss.or.kr', date: '2026.07.21' },
    ],
    news: [
      { title: 'HBM4 양산 일정 전망 재조정 가능성', source: '전자신문', url: 'https://www.etnews.com', time: '12분 전' },
      { title: 'HBM 수요 대응 후공정 패키징 라인 증설 검토', source: '전자신문', url: 'https://www.etnews.com', time: '4시간 전' },
      { title: 'HBM4 공급 협의 관련 업계 관측 정리', source: 'ZDNet Korea', url: 'https://zdnet.co.kr', time: '7시간 전' },
    ],
  },
  '청주 M15X': {
    desc: '청주 신규 팹 라인. 설비 투자 규모·완공 일정이 공시로 확인 가능한 항목입니다.',
    docs: [
      { label: '공시 원문 · 신규 시설투자 공시', source: '전자공시(DART)', url: 'https://dart.fss.or.kr', date: '2026.07.21' },
      { label: '공시 원문 · 원재료 수급 계약 갱신', source: '전자공시(DART)', url: 'https://dart.fss.or.kr', date: '2026.07.23' },
    ],
    news: [
      { title: '청주 M15X 신규 설비 투자 공시 접수', source: '전자신문', url: 'https://www.etnews.com', time: '1시간 전' },
    ],
  },
  엔비디아: {
    desc: 'AI 가속기 최대 수요처. 분기 실적의 데이터센터 매출 비중이 메모리 수요와 직결됩니다.',
    docs: [
      { label: 'IR 원문 · 분기 실적 자료', source: 'NVIDIA Investor Relations', url: 'https://investor.nvidia.com/financial-info/quarterly-results/', date: '2026.07.23' },
    ],
    news: [
      { title: '엔비디아 분기 실적 공식 발표', source: '로이터', url: 'https://www.reuters.com', time: '38분 전' },
      { title: 'AI 서버향 메모리 수요 재조정', source: '디지털투데이', url: 'https://www.digitaltoday.co.kr', time: '3시간 전' },
    ],
  },
  수출통제: {
    desc: '대중 반도체 장비 수출 통제. 공식 확인 전 단계라 교차 검증 대상으로 분류돼 있습니다.',
    docs: [],
    news: [
      { title: '대중 반도체 장비 수출 통제 추가 논의', source: '연합뉴스', url: 'https://www.yna.co.kr', time: '2시간 전' },
      { title: '통제 품목 확대 논의 관련 보도', source: 'ZDNet Korea', url: 'https://zdnet.co.kr', time: '6시간 전' },
    ],
  },
  '차세대 패키징': {
    desc: 'HBM 수요 확대에 따른 후공정 패키징 증설 논의.',
    docs: [],
    news: [
      { title: '후공정 패키징 라인 증설 검토', source: '전자신문', url: 'https://www.etnews.com', time: '4시간 전' },
    ],
  },
  마이크론: {
    desc: '경쟁 메모리 업체. 신규 D램 라인 가동이 공급 지형 변수로 언급됩니다.',
    docs: [],
    news: [
      { title: '마이크론 신규 D램 라인 가동', source: '로이터', url: 'https://www.reuters.com', time: '5시간 전' },
    ],
  },
  삼성전자: {
    desc: '경쟁사. 파운드리 수율 개선 발표가 경쟁 구도 변수로 거론됩니다.',
    docs: [],
    news: [
      { title: '삼성전자 파운드리 수율 개선 발표', source: '비즈니스워치', url: 'https://news.bizwatch.co.kr', time: '1시간 전' },
    ],
  },
  'TSMC N2': {
    desc: '2나노 공정. 시험 생산 개시 보도가 나왔으나 공식 확인은 되지 않았습니다.',
    docs: [],
    news: [
      { title: 'TSMC N2 공정 시험 생산 개시', source: '디일렉', url: 'https://www.thelec.kr', time: '3시간 전' },
      { title: '차세대 GAA 공정 로드맵 공개', source: '디일렉', url: 'https://www.thelec.kr', time: '7시간 전' },
    ],
  },
  현물가: {
    desc: 'D램·낸드 현물 가격. 업턴 진입 판단의 선행 지표로 쓰입니다.',
    docs: [],
    news: [
      { title: '메모리 현물가 3주 연속 상승', source: '한국경제', url: 'https://www.hankyung.com', time: '6시간 전' },
      { title: '메모리 업체 3분기 실적 전망 상향', source: '한국경제', url: 'https://www.hankyung.com', time: '2시간 전' },
    ],
  },
  'AI 가속기': {
    desc: 'HBM 수요의 최종 견인차. 데이터센터 발주 흐름과 함께 움직입니다.',
    docs: [
      { label: 'IR 원문 · 데이터센터 부문 매출', source: 'NVIDIA Investor Relations', url: 'https://investor.nvidia.com/financial-info/quarterly-results/', date: '2026.07.23' },
    ],
    news: [
      { title: 'AI 서버향 메모리 수요 재조정', source: '디지털투데이', url: 'https://www.digitaltoday.co.kr', time: '3시간 전' },
      { title: '데이터센터향 신규 수주 확대', source: '비즈니스워치', url: 'https://news.bizwatch.co.kr', time: '8시간 전' },
    ],
  },
  '고대역폭 메모리': {
    desc: 'HBM 계열 규격 전반. 세대별 대역폭·적층 수가 주요 비교 지표입니다.',
    docs: [],
    news: [
      { title: 'HBM4 양산 일정 전망 재조정 가능성', source: '전자신문', url: 'https://www.etnews.com', time: '12분 전' },
    ],
  },
  '설비 투자': {
    desc: '신규 라인 증설 안건. 규모·완공 일정이 공시로 확인 가능한 대표 항목입니다.',
    docs: [
      { label: '공시 원문 · 신규 시설투자 결정', source: '전자공시(DART)', url: 'https://dart.fss.or.kr', date: '2026.07.21' },
    ],
    news: [
      { title: '청주 M15X 신규 설비 투자 공시 접수', source: '전자신문', url: 'https://www.etnews.com', time: '1시간 전' },
    ],
  },
  '후공정 패키징': {
    desc: 'HBM 수요 확대에 따른 후공정 증설 논의. 아직 공시 확인 전 단계입니다.',
    docs: [],
    news: [
      { title: '후공정 패키징 라인 증설 검토', source: '전자신문', url: 'https://www.etnews.com', time: '4시간 전' },
    ],
  },
  'D램': {
    desc: '메모리 본류. 미세공정 전환과 현물가 흐름이 함께 묶여 다뤄집니다.',
    docs: [],
    news: [
      { title: '마이크론 신규 D램 라인 가동', source: '로이터', url: 'https://www.reuters.com', time: '5시간 전' },
      { title: '메모리 현물가 3주 연속 상승', source: '한국경제', url: 'https://www.hankyung.com', time: '6시간 전' },
    ],
  },
  파운드리: {
    desc: '위탁생산 경쟁 축. 수율·미세공정 로드맵이 비교 지표입니다.',
    docs: [],
    news: [
      { title: '삼성전자 파운드리 수율 개선 발표', source: '비즈니스워치', url: 'https://news.bizwatch.co.kr', time: '1시간 전' },
      { title: 'TSMC N2 공정 시험 생산 개시', source: '디일렉', url: 'https://www.thelec.kr', time: '3시간 전' },
    ],
  },
  데이터센터: {
    desc: 'AI 서버 수요의 최종 수요처. 증설 일정 변동이 메모리 발주에 직접 반영됩니다.',
    docs: [],
    news: [
      { title: '데이터센터향 신규 수주 확대', source: '비즈니스워치', url: 'https://news.bizwatch.co.kr', time: '8시간 전' },
      { title: '엔비디아 분기 실적 공식 발표', source: '로이터', url: 'https://www.reuters.com', time: '38분 전' },
    ],
  },
  '양산 시점': {
    desc: '매체별 서술이 가장 자주 엇갈리는 항목이라 교차 검증 대상으로 관리합니다.',
    docs: [],
    news: [
      { title: 'HBM4 양산 일정 전망 재조정 가능성', source: '전자신문', url: 'https://www.etnews.com', time: '12분 전' },
      { title: '마이크론 신규 D램 라인 가동', source: '로이터', url: 'https://www.reuters.com', time: '5시간 전' },
    ],
  },
};

// 본문에서 긴 키워드를 먼저 매칭해야 "청주 M15X"가 "M15X"로 잘리지 않습니다.
export function getWikiKeywordList() {
  return Object.keys(WIKI_KEYWORD_LINKS).sort((a, b) => b.length - a.length);
}
