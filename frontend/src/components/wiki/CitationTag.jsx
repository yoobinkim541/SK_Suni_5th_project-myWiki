// 위키/에이전트 공용 — 근거 표시 태그
//
// 두 가지 모양을 한 파일에서 담당합니다. 마크업은 시안 그대로입니다.
//  · <CitationTag no={1} sourceKey="dart" />        → 본문 각주 <a class="fn">1</a>
//  · <CitationTag no={1} sourceKey="dart" chip />   → 답변 하단 칩 <a class="cite">1 공시 원문 ↗</a>
//
// 두 경우 모두 클릭하면 새 탭으로 출처 원문(Source Router)이 열립니다.

import { getSource } from '../../services/wikiApi';

export default function CitationTag({ no, sourceKey, chip = false }) {
  const src = getSource(sourceKey);
  if (!src) return null;

  if (!chip) {
    return (
      <a
        className="fn"
        href={src.url}
        target="_blank"
        rel="noopener"
        title={`근거 ${no} · ${src.title}`}
      >
        {no}
      </a>
    );
  }

  // "공시 원문"처럼 정형 데이터 출처는 .cite.doc 로 강조합니다(시안과 동일).
  const isDoc = src.name.includes('공시') || src.name.includes('IR');
  return (
    <a
      className={`cite${isDoc ? ' doc' : ''}`}
      href={src.url}
      target="_blank"
      rel="noopener"
      title={src.title}
    >
      <span className="n">{no}</span>{src.name}<span className="ex">↗</span>
    </a>
  );
}
