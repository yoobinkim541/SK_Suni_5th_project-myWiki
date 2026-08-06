import { useMemo, useState } from "react";
import {
  WIKI_KEYWORD_CATALOG,
  getDocCoreKeywords,
  getKeywordTotal
} from "../../data/wikiKeywords";
import "../../styles/wiki-sidenav.css";
const VISIBLE_DOCS = 3;
const TOP_KEYWORDS = 7;
function Chevron() {
  return /* @__PURE__ */ React.createElement(
    "svg",
    {
      className: "chev",
      viewBox: "0 0 24 24",
      width: "12",
      height: "12",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round",
      "aria-hidden": "true"
    },
    /* @__PURE__ */ React.createElement("path", { d: "M6 9l6 6 6-6" })
  );
}
function KeywordChip({ word, count, hot, onKeyword }) {
  return /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: `kw${hot ? " hot" : ""}`,
      title: `${word} \xB7 \uC774 \uD0A4\uC6CC\uB4DC\uAC00 \uB4E4\uC5B4\uAC04 \uBB38\uC11C \uBCF4\uAE30`,
      onClick: () => onKeyword?.(word)
    },
    word,
    count > 1 && /* @__PURE__ */ React.createElement("i", null, count)
  );
}
export default function WikiSideNav({ tree, doc, current, onSelect, onKeyword }) {
  const [kwOpen, setKwOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState({});
  const coreKeywords = useMemo(() => getDocCoreKeywords(doc), [doc]);
  const topKeywords = coreKeywords.slice(0, TOP_KEYWORDS);
  const topWords = topKeywords.map((k) => k.word);
  const keywordTotal = getKeywordTotal();
  const groups = useMemo(() => {
    const list = [...WIKI_KEYWORD_CATALOG];
    const i = list.findIndex((g) => g.cat === doc?.category);
    if (i > 0) list.unshift(list.splice(i, 1)[0]);
    return list;
  }, [doc]);
  const toggleGroup = (group) => setOpenGroups((prev) => ({ ...prev, [group]: !prev[group] }));
  return /* @__PURE__ */ React.createElement("div", { className: "tree" }, /* @__PURE__ */ React.createElement("div", { className: `kwbox${kwOpen ? " open" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "kwhd" }, /* @__PURE__ */ React.createElement("span", { className: "t" }, "\uC5F0\uB3D9 \uD0A4\uC6CC\uB4DC"), /* @__PURE__ */ React.createElement("span", { className: "c" }, keywordTotal)), !kwOpen && (topKeywords.length > 0 ? /* @__PURE__ */ React.createElement("div", { className: "kwtop" }, topKeywords.map((k) => /* @__PURE__ */ React.createElement(KeywordChip, { key: k.word, word: k.word, count: k.count, hot: true, onKeyword }))) : (
    // 본문에서 이 분류의 카탈로그 키워드를 찾지 못한 문서 — 임의로 채우지 않습니다.
    /* @__PURE__ */ React.createElement("p", { className: "kwnone" }, "\uC774 \uBB38\uC11C\uC5D0\uC11C \uCD94\uCD9C\uB41C \uBD84\uB958 \uD0A4\uC6CC\uB4DC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.")
  )), kwOpen && /* @__PURE__ */ React.createElement("div", { className: "kwall" }, groups.map((g) => /* @__PURE__ */ React.createElement("div", { key: g.cat }, /* @__PURE__ */ React.createElement("div", { className: `kwg${g.cat === doc?.category ? " cur" : ""}` }, g.cat, /* @__PURE__ */ React.createElement("span", null, g.words.length)), /* @__PURE__ */ React.createElement("div", { className: "kwl" }, g.words.map((w) => /* @__PURE__ */ React.createElement(
    KeywordChip,
    {
      key: w,
      word: w,
      count: 0,
      hot: topWords.includes(w),
      onKeyword
    }
  )))))), /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "kwtg",
      "aria-expanded": kwOpen,
      onClick: () => setKwOpen((v) => !v)
    },
    /* @__PURE__ */ React.createElement(Chevron, null),
    /* @__PURE__ */ React.createElement("span", { className: "lb" }, kwOpen ? "\uC811\uAE30" : "\uC804\uCCB4 \uD0A4\uC6CC\uB4DC \uD3BC\uCE58\uAE30")
  )), tree.map((section) => {
    const hiddenCount = Math.max(section.items.length - VISIBLE_DOCS, 0);
    const hasCurrentHidden = section.items.slice(VISIBLE_DOCS).some((item) => item.id === current);
    const open = openGroups[section.group] ?? hasCurrentHidden;
    const items = open ? section.items : section.items.slice(0, VISIBLE_DOCS);
    return /* @__PURE__ */ React.createElement("div", { className: `tg${open ? " open" : ""}`, key: section.group }, /* @__PURE__ */ React.createElement("div", { className: "g" }, section.group, /* @__PURE__ */ React.createElement("span", { className: "n" }, section.items.length)), items.map((item) => /* @__PURE__ */ React.createElement(
      "a",
      {
        key: item.id,
        className: current === item.id ? "on" : "",
        onClick: () => onSelect(item.id)
      },
      item.title
    )), hiddenCount > 0 && /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "treemore",
        "aria-expanded": open,
        onClick: () => toggleGroup(section.group)
      },
      /* @__PURE__ */ React.createElement(Chevron, null),
      /* @__PURE__ */ React.createElement("span", { className: "lb" }, open ? "\uC811\uAE30" : `+${hiddenCount}\uAC1C \uB354 \uBCF4\uAE30`)
    ));
  }));
}
