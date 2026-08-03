// 위키 API 호출부. 지금은 data/mockWiki.js를 그대로 돌려줍니다.

import { MOCK_WIKI_DOCS, MOCK_WIKI_TREE, WIKI_SOURCES, WIKI_ALIAS, DEFAULT_WIKI_DOC, MOCK_AGENT_PANES, MOCK_AGENT_REPLY } from '../data/mockWiki';

const delay = (value) => Promise.resolve(value);

export function fetchWikiTree() {
  return delay(MOCK_WIKI_TREE);
}

export function fetchWikiDoc(id) {
  return delay(MOCK_WIKI_DOCS[id] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC]);
}

export function getWikiDoc(id) {
  return MOCK_WIKI_DOCS[id] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC];
}

// 대시보드·리포트의 "관련 위키" 링크 이름을 문서 id로 바꿉니다.
export function resolveWikiId(nameOrId) {
  if (!nameOrId) return DEFAULT_WIKI_DOC;
  if (MOCK_WIKI_DOCS[nameOrId]) return nameOrId;
  return WIKI_ALIAS[nameOrId] || DEFAULT_WIKI_DOC;
}

export function getSource(key) {
  return WIKI_SOURCES[key];
}

export function fetchAgentPanes() {
  return delay(MOCK_AGENT_PANES);
}

// 실제 연동 전까지는 고정 응답을 돌려줍니다.
export function askAgent() {
  return delay(MOCK_AGENT_REPLY);
}
