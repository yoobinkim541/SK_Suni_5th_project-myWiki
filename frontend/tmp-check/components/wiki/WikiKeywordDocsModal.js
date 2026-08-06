import { useEffect } from "react";
export default function WikiKeywordDocsModal({ word, docs, category, onSelect, onClose }) {
  useEffect(() => {
    if (!word) return;
    function handleKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [word, onClose]);
  if (!word) return null;
  const rows = docs || [];
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "mw-scrim open", onClick: onClose }), /* @__PURE__ */ React.createElement("div", { className: "mw-modal open", role: "dialog", "aria-modal": "true", "aria-label": `${word} \uAD00\uB828 \uBB38\uC11C` }, /* @__PURE__ */ React.createElement("div", { className: "mw-hd" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "eb" }, "KEYWORD", category ? ` \xB7 ${category}` : "", " \xB7 \uBB38\uC11C ", rows.length, "\uAC74"), /* @__PURE__ */ React.createElement("h3", null, word)), /* @__PURE__ */ React.createElement("button", { className: "mw-x", onClick: onClose, "aria-label": "\uB2EB\uAE30" }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "mw-body" }, /* @__PURE__ */ React.createElement("div", { className: "mw-lb" }, "\uC774 \uD0A4\uC6CC\uB4DC\uAC00 \uB4F1\uC7A5\uD558\uB294 \uBB38\uC11C"), /* @__PURE__ */ React.createElement("div", { className: "kwm-list" }, rows.length === 0 ? (
    // 축적된 문서에서 근거를 못 찾은 경우 — 추측으로 채우지 않습니다.
    /* @__PURE__ */ React.createElement("div", { className: "kwm-empty" }, "\uC774 \uD0A4\uC6CC\uB4DC\uAC00 \uB4F1\uC7A5\uD558\uB294 \uC704\uD0A4 \uBB38\uC11C\uB97C \uCC3E\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.")
  ) : rows.map((d) => /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "kwm-item kwd-item",
      key: d.id,
      onClick: () => {
        onSelect?.(d.id);
        onClose?.();
      }
    },
    /* @__PURE__ */ React.createElement("span", { className: "ic", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ React.createElement("path", { d: "M6 3h9l4 4v14H6z" }), /* @__PURE__ */ React.createElement("path", { d: "M14 3v5h5" }))),
    /* @__PURE__ */ React.createElement("span", { className: "tx" }, /* @__PURE__ */ React.createElement("b", null, d.title), /* @__PURE__ */ React.createElement("span", { className: "s" }, d.group, " \xB7 \uBCF8\uBB38 ", d.count, "\uD68C \uB4F1\uC7A5"))
  ))))));
}
