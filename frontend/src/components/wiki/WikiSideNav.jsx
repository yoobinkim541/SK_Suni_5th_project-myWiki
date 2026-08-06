// 위키 좌측 문서 목록(.tree)
//
// 분류별 3개만 노출하고 나머지는 "+N개 더 보기"로 접습니다.
// 현재 열려 있는 문서가 접힌 자리에 있으면 그 분류는 처음부터 펼쳐 둡니다
// (선택된 문서가 화면에서 사라지지 않게).
//
// 연동 키워드는 여기 있지 않습니다 — 문서 상단 줄(WikiKeywordBar)이 담당합니다.

import { useState } from 'react';
import '../../styles/wiki-sidenav.css';

const VISIBLE_DOCS = 3; // 분류별 기본 노출 문서 수

function Chevron() {
  return (
    <svg
      className="chev" viewBox="0 0 24 24" width="12" height="12" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export default function WikiSideNav({ tree, current, onSelect }) {
  const [openGroups, setOpenGroups] = useState({});

  const toggleGroup = (group) =>
    setOpenGroups((prev) => ({ ...prev, [group]: !prev[group] }));

  return (
    <div className="tree">
      {tree.map((section) => {
        const hiddenCount = Math.max(section.items.length - VISIBLE_DOCS, 0);
        const hasCurrentHidden = section.items
          .slice(VISIBLE_DOCS)
          .some((item) => item.id === current);
        const open = openGroups[section.group] ?? hasCurrentHidden;
        const items = open ? section.items : section.items.slice(0, VISIBLE_DOCS);

        return (
          <div className={`tg${open ? ' open' : ''}`} key={section.group}>
            <div className="g">{section.group}<span className="n">{section.items.length}</span></div>
            {items.map((item) => (
              <a
                key={item.id}
                className={current === item.id ? 'on' : ''}
                onClick={() => onSelect(item.id)}
              >
                {item.title}
              </a>
            ))}
            {hiddenCount > 0 && (
              <button
                type="button" className="treemore"
                aria-expanded={open}
                onClick={() => toggleGroup(section.group)}
              >
                <Chevron />
                <span className="lb">{open ? '접기' : `+${hiddenCount}개 더 보기`}</span>
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
