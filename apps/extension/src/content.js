// Content script: captures structured DOM events while a Refract capture is active.
// Emits the SAME event shape as the in-app recorder so Phase 2 does not care about source.
// Password fields are never captured (master §5 PII rule).

(() => {
  let recording = false;

  function selectorFor(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return `#${CSS.escape(el.id)}`;
    const testid = el.getAttribute("data-testid");
    if (testid) return `[data-testid="${testid}"]`;
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = node.parentElement;
      depth++;
    }
    return parts.join(" > ");
  }

  function labelFor(el) {
    if (!el) return null;
    const aria = el.getAttribute && el.getAttribute("aria-label");
    if (aria) return aria.slice(0, 120);
    const text = (el.textContent || "").trim().replace(/\s+/g, " ");
    return text ? text.slice(0, 120) : null;
  }

  function send(type, payload, wantShot) {
    if (!recording) return;
    chrome.runtime.sendMessage({
      kind: "event",
      event: { type, ...payload },
      wantShot: !!wantShot,
    });
  }

  document.addEventListener(
    "click",
    (e) => {
      const el = e.target;
      const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { x: e.clientX, y: e.clientY, width: 0, height: 0 };
      send(
        "click",
        {
          selector: selectorFor(el),
          text: labelFor(el),
          bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
          viewport: { w: window.innerWidth, h: window.innerHeight },
        },
        true, // meaningful step -> request a screenshot
      );
    },
    true,
  );

  document.addEventListener(
    "input",
    (e) => {
      const el = e.target;
      const isPassword = el && el.tagName === "INPUT" && el.type === "password";
      send("input", {
        selector: selectorFor(el),
        value_redacted: isPassword ? "[redacted]" : String(el.value || "").slice(0, 200),
      });
    },
    true,
  );

  function sendNav() {
    send("navigation", { text: document.title ? document.title.slice(0, 120) : null, selector: location.href });
  }
  window.addEventListener("popstate", sendNav);
  window.addEventListener("hashchange", sendNav);

  // Ask the background whether a capture is in progress, and react to start/stop.
  chrome.runtime.sendMessage({ kind: "queryState" }, (res) => {
    recording = !!(res && res.recording);
    if (recording) sendNav();
  });
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.kind === "state") {
      const was = recording;
      recording = !!msg.recording;
      if (recording && !was) sendNav();
    }
  });
})();
