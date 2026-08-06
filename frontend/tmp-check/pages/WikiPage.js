import { useEffect, useState } from "react";
import { WIKI_KEYWORD_LINKS } from "../data/mockWiki";
import { findDocsWithKeyword, getKeywordCategory } from "../data/wikiKeywords";
import { fetchWikiTree, fetchWikiDoc, resolveWikiId } from "../services/wikiApi";
import WikiSideNav from "../components/wiki/WikiSideNav";
import WikiCard from "../components/wiki/WikiCard";
import WikiKeywordDocsModal from "../components/wiki/WikiKeywordDocsModal";
import WikiKeywordModal from "../components/wiki/WikiKeywordModal";
export default function WikiPage({ docId }) {
  const [tree, setTree] = useState(null);
  const [current, setCurrent] = useState(null);
  const [doc, setDoc] = useState(null);
  const [keyword, setKeyword] = useState(null);
  const [docKeyword, setDocKeyword] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    fetchWikiTree().then((data) => {
      if (!alive) return;
      setTree(data);
      const resolved = resolveWikiId(docId) || data[0]?.items[0]?.id || null;
      setCurrent(resolved);
    }).catch((e) => alive && setError(e.message || "\uC704\uD0A4 \uBAA9\uB85D\uC744 \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4."));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (docId) setCurrent(resolveWikiId(docId));
  }, [docId]);
  useEffect(() => {
    if (!current) return;
    let alive = true;
    setDoc(null);
    fetchWikiDoc(current).then((data) => alive && setDoc(data)).catch((e) => alive && setError(e.message || "\uC704\uD0A4 \uBB38\uC11C\uB97C \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4."));
    return () => {
      alive = false;
    };
  }, [current]);
  if (error) {
    return /* @__PURE__ */ React.createElement("section", { className: "view on", id: "v-wiki" }, /* @__PURE__ */ React.createElement("div", { className: "ph" }, /* @__PURE__ */ React.createElement("h2", null, "\uC704\uD0A4\uB97C \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4")), /* @__PURE__ */ React.createElement("p", null, error));
  }
  if (tree && tree.every((group) => group.items.length === 0)) {
    return /* @__PURE__ */ React.createElement("section", { className: "view on", id: "v-wiki" }, /* @__PURE__ */ React.createElement("div", { className: "ph" }, /* @__PURE__ */ React.createElement("h2", null, "\uC704\uD0A4")), /* @__PURE__ */ React.createElement("p", null, "\uC544\uC9C1 \uAC8C\uC2DC\uB41C \uC704\uD0A4 \uBB38\uC11C\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4."));
  }
  if (!tree || !doc) {
    return /* @__PURE__ */ React.createElement("section", { className: "view on", id: "v-wiki" }, /* @__PURE__ */ React.createElement("div", { className: "ph" }, /* @__PURE__ */ React.createElement("h2", null, "\uBD88\uB7EC\uC624\uB294 \uC911\u2026")));
  }
  return /* @__PURE__ */ React.createElement("section", { className: "view on", id: "v-wiki" }, /* @__PURE__ */ React.createElement("div", { className: "ph" }, /* @__PURE__ */ React.createElement("h2", null, doc.title), /* @__PURE__ */ React.createElement("span", { className: "dt" }, doc.category), /* @__PURE__ */ React.createElement("span", { className: "st" }, "\uCD5C\uC885 \uAC31\uC2E0 ", /* @__PURE__ */ React.createElement("b", null, doc.updated))), /* @__PURE__ */ React.createElement("div", { className: "wiki" }, /* @__PURE__ */ React.createElement(
    WikiSideNav,
    {
      tree,
      doc,
      current,
      onSelect: setCurrent,
      onKeyword: setDocKeyword
    }
  ), /* @__PURE__ */ React.createElement(WikiCard, { doc, onKeyword: setKeyword }), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "col" }, /* @__PURE__ */ React.createElement("h5", null, "\uADFC\uAC70 \uCD9C\uCC98", /* @__PURE__ */ React.createElement("span", { className: "c" }, doc.sourceCount)), doc.sources.map((s, i) => /* @__PURE__ */ React.createElement(
    "a",
    {
      className: "it",
      key: `${s.citationOrder}-${i}`,
      href: s.url || void 0,
      target: s.url ? "_blank" : void 0,
      rel: s.url ? "noopener" : void 0,
      title: s.url ? s.title : `${s.title} (\uC6D0\uBB38 \uC8FC\uC18C \uD655\uC778 \uC548 \uB428)`,
      "aria-disabled": !s.url
    },
    /* @__PURE__ */ React.createElement("span", { className: "no" }, i + 1),
    s.title,
    s.sourceName ? ` \xB7 ${s.sourceName}` : "",
    s.date ? ` \xB7 ${s.date}` : ""
  ))), /* @__PURE__ */ React.createElement("div", { className: "col" }, /* @__PURE__ */ React.createElement("h5", null, "\uC5F0\uACB0\uB41C \uBB38\uC11C", /* @__PURE__ */ React.createElement("span", { className: "c" }, doc.links.length)), doc.links.map((l) => /* @__PURE__ */ React.createElement("button", { className: "it lnk", key: l.id, onClick: () => setCurrent(l.id) }, /* @__PURE__ */ React.createElement("b", null, l.title), l.desc))))), /* @__PURE__ */ React.createElement(
    WikiKeywordModal,
    {
      word: keyword,
      entry: keyword ? WIKI_KEYWORD_LINKS[keyword] : null,
      onClose: () => setKeyword(null)
    }
  ), /* @__PURE__ */ React.createElement(
    WikiKeywordDocsModal,
    {
      word: docKeyword,
      docs: docKeyword ? findDocsWithKeyword(docKeyword, tree) : [],
      category: docKeyword ? getKeywordCategory(docKeyword) : null,
      onSelect: setCurrent,
      onClose: () => setDocKeyword(null)
    }
  ));
}
