// CDP driver: the "hands and eyes" of Auto Record. Attaches chrome.debugger to the
// recorded tab and executes the agent's actions with TRUSTED input events (real
// apps ignore synthetic dispatchEvent clicks). `observe()` returns a compact,
// ref-addressable summary of the page + a screenshot for the model.

function send(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params || {}, (res) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(res);
    });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function attach(tabId) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", async () => {
      const err = chrome.runtime.lastError;
      if (err) return reject(new Error(err.message));
      try {
        await send(tabId, "Page.enable");
        await send(tabId, "Runtime.enable");
        resolve();
      } catch (e) {
        reject(e);
      }
    });
  });
}

export function detach(tabId) {
  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      void chrome.runtime.lastError; // ignore "not attached"
      resolve();
    });
  });
}

// Runs in the page: collects visible, interactable elements addressable by `ref`.
// Ports the manual capture's selectorFor/labelFor so Auto Record selectors match.
const EXTRACTOR = `(() => {
  function selectorFor(el){
    if(!el || el.nodeType!==1) return null;
    if(el.id) return '#'+CSS.escape(el.id);
    const t = el.getAttribute('data-testid'); if(t) return '[data-testid="'+t+'"]';
    const parts=[]; let n=el, d=0;
    while(n && n.nodeType===1 && d<4){
      let p=n.tagName.toLowerCase(); const par=n.parentElement;
      if(par){ const sibs=Array.from(par.children).filter(c=>c.tagName===n.tagName);
        if(sibs.length>1) p+=':nth-of-type('+(sibs.indexOf(n)+1)+')'; }
      parts.unshift(p); n=n.parentElement; d++;
    }
    return parts.join(' > ');
  }
  function labelFor(el){
    const a = el.getAttribute && el.getAttribute('aria-label'); if(a) return a.slice(0,120);
    const ph = el.getAttribute && el.getAttribute('placeholder'); if(ph) return ph.slice(0,120);
    const tx = (el.textContent||'').trim().replace(/\\s+/g,' '); return tx? tx.slice(0,120):null;
  }
  const sel='a,button,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=combobox],[onclick],[contenteditable=""],[contenteditable=true]';
  const vw=window.innerWidth, vh=window.innerHeight, els=[]; let ref=0;
  for(const el of document.querySelectorAll(sel)){
    const r=el.getBoundingClientRect();
    if(r.width<1||r.height<1) continue;
    if(r.bottom<0||r.top>vh||r.right<0||r.left>vw) continue;
    const st=getComputedStyle(el);
    if(st.visibility==='hidden'||st.display==='none'||st.opacity==='0') continue;
    const tag=el.tagName.toLowerCase();
    const pw = tag==='input' && el.type==='password';
    els.push({
      ref:'e'+(ref++), tag,
      role: el.getAttribute('role')||null,
      text: labelFor(el),
      value: (tag==='input'||tag==='textarea') ? (pw?null:String(el.value||'').slice(0,60)) : null,
      selector: selectorFor(el),
      bbox: [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
      disabled: !!el.disabled, password: pw,
    });
    if(els.length>=150) break;
  }
  const doc=document.documentElement;
  return { url:location.href, title:document.title, scroll_y:window.scrollY,
    scroll_max:Math.max(0,(doc.scrollHeight||0)-vh), elements:els };
})()`;

export async function observe(tabId) {
  let data = { url: null, title: null, elements: [] };
  try {
    const res = await send(tabId, "Runtime.evaluate", { expression: EXTRACTOR, returnByValue: true });
    if (res && res.result && res.result.value) data = res.result.value;
  } catch (e) {
    data = { url: null, title: null, elements: [], _error: String(e) };
  }
  data.screenshot_b64 = await screenshot(tabId);
  return data;
}

export async function screenshot(tabId) {
  try {
    const s = await send(tabId, "Page.captureScreenshot", { format: "jpeg", quality: 60 });
    return (s && s.data) || null;
  } catch {
    return null; // works even when the tab is unfocused; null only on hard failures
  }
}

function ghostCursor(x, y, click) {
  return `(() => {
    let d=document.getElementById('__refract_cursor__');
    if(!d){ d=document.createElement('div'); d.id='__refract_cursor__';
      d.style.cssText='position:fixed;z-index:2147483647;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:rgba(239,68,68,.65);box-shadow:0 0 0 3px rgba(239,68,68,.25);pointer-events:none;transition:left .35s ease,top .35s ease,transform .12s ease;left:0;top:0';
      (document.body||document.documentElement).appendChild(d);
    }
    d.style.left='${x}px'; d.style.top='${y}px';
    ${click ? "d.style.transform='scale(.55)'; setTimeout(()=>{try{d.style.transform='scale(1)'}catch(e){}},140);" : ""}
  })()`;
}

async function mouseClick(tabId, x, y) {
  await send(tabId, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await send(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await send(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}

const KEYS = {
  Enter: { key: "Enter", code: "Enter", keyCode: 13, windowsVirtualKeyCode: 13, text: "\r" },
  Tab: { key: "Tab", code: "Tab", keyCode: 9, windowsVirtualKeyCode: 9 },
  Escape: { key: "Escape", code: "Escape", keyCode: 27, windowsVirtualKeyCode: 27 },
  Delete: { key: "Delete", code: "Delete", keyCode: 46, windowsVirtualKeyCode: 46 },
};

async function dispatchKey(tabId, name) {
  const k = KEYS[name];
  if (!k) return;
  await send(tabId, "Input.dispatchKeyEvent", { type: "rawKeyDown", ...k });
  if (k.text) await send(tabId, "Input.dispatchKeyEvent", { type: "char", ...k });
  await send(tabId, "Input.dispatchKeyEvent", { type: "keyUp", ...k });
}

async function selectAll(tabId) {
  const b = { key: "a", code: "KeyA", keyCode: 65, windowsVirtualKeyCode: 65, modifiers: 2 };
  await send(tabId, "Input.dispatchKeyEvent", { type: "rawKeyDown", ...b });
  await send(tabId, "Input.dispatchKeyEvent", { type: "keyUp", ...b });
}

async function typeText(tabId, text) {
  const chunks = String(text).match(/[\s\S]{1,3}/g) || [];
  for (const c of chunks) {
    await send(tabId, "Input.insertText", { text: c });
    await sleep(55); // human-paced typing so it reads well on the recording
  }
}

async function waitForLoad(tabId, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await send(tabId, "Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
      if (r && r.result && r.result.value === "complete") return;
    } catch {
      /* mid-navigation evaluate can throw; keep polling */
    }
    await sleep(300);
  }
}

// Execute one action. Returns { ok, error, event } where `event` (or null) is the
// telemetry CaptureEvent to log. t_ms is measured from the recording clock.
export async function execute(tabId, action, elements, startTs) {
  const t = () => Math.max(0, Date.now() - startTs);
  const find = (ref) => (elements || []).find((e) => e.ref === ref);
  const a = action || {};
  try {
    if (a.action === "wait") {
      await sleep(Math.min(5000, Math.max(300, a.wait_ms || 1000)));
      return { ok: true, event: null };
    }
    if (a.action === "navigate") {
      await send(tabId, "Page.navigate", { url: a.url });
      await waitForLoad(tabId, 15000);
      await sleep(1200);
      let title = null;
      try {
        const r = await send(tabId, "Runtime.evaluate", { expression: "document.title", returnByValue: true });
        title = (r && r.result && r.result.value) || null;
      } catch {
        /* ignore */
      }
      return { ok: true, event: { type: "navigation", t_ms: t(), selector: a.url, text: title, bbox: null } };
    }
    if (a.action === "scroll") {
      const dist = 600 * (a.scroll_to === "up" ? -1 : 1);
      await send(tabId, "Input.synthesizeScrollGesture", { x: 400, y: 300, yDistance: dist, speed: 800 });
      await sleep(500);
      return { ok: true, event: { type: "scroll", t_ms: t(), selector: null, text: a.scroll_to || "down", bbox: null } };
    }
    if (a.action === "keydown") {
      await dispatchKey(tabId, a.key);
      await sleep(200);
      return { ok: true, event: { type: "keydown", t_ms: t(), selector: null, text: a.key || null, bbox: null } };
    }
    if (a.action === "click" || a.action === "input") {
      const el = find(a.ref);
      if (!el) return { ok: false, error: "element not found: " + (a.ref || "?"), event: null };
      const [x, y, w, h] = el.bbox;
      const cx = x + w / 2, cy = y + h / 2;
      await send(tabId, "Runtime.evaluate", { expression: ghostCursor(cx, cy, true) });
      await sleep(380);
      await mouseClick(tabId, cx, cy);
      if (a.action === "click") {
        await sleep(300);
        return { ok: true, event: { type: "click", t_ms: t(), selector: el.selector, text: el.text || null, bbox: el.bbox } };
      }
      if (el.password) return { ok: false, error: "refusing to type into a password field", event: null };
      if (a.clear) {
        await selectAll(tabId);
        await dispatchKey(tabId, "Delete");
      }
      await typeText(tabId, a.text || "");
      if (a.press_enter) await dispatchKey(tabId, "Enter");
      await sleep(250);
      return {
        ok: true,
        event: {
          type: "input", t_ms: t(), selector: el.selector, text: el.text || null,
          bbox: el.bbox, value_redacted: String(a.text || "").slice(0, 200),
        },
      };
    }
    return { ok: true, event: null }; // done / fail — no telemetry
  } catch (e) {
    return { ok: false, error: String(e), event: null };
  }
}
