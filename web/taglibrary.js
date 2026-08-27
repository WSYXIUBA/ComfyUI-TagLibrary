/**
 * ComfyUI-TagLibrary 节点面板扩展 v2
 *
 * v2: 现代化重设计
 *  - CSS 由 JS 注入 (ComfyUI 只自动加载 web/ 下 .js, 之前 tagpanel.css 根本没被加载)
 *  - 分类 pills + 色彩化 chips(✓选中态) + 已选区拖拽/钉选 + 分段式模式切换 + ROLL 按钮
 *  - NSFW 开关: 设置页有默认值, 节点上有快捷开关, 双向同步, 写进 selection_state
 *  - 设置页注册 (Settings 搜"标签库"): 默认模式 / NSFW 默认值 / 面板高度
 */
import { app } from "../../scripts/app.js";
import { injectPanelStyle } from "./tagpanel-css.js";

const NODE_NAME = "TagLibraryNode";
const MANAGER_URL = "/taglib?embed=1";
const SETTING_PREFIX = "TagLibrary.";

/* settings keys */
const SET_DEFAULT_MODE = SETTING_PREFIX + "default_mode";
const SET_DEFAULT_NSFW = SETTING_PREFIX + "default_nsfw";
const SET_SCALE = SETTING_PREFIX + "chip_scale";
const SET_LANG = SETTING_PREFIX + "display_lang";

let LIB_CACHE = null;
let LIB_FETCHING = null;

async function fetchLibrary() {
  if (LIB_CACHE) return LIB_CACHE;
  if (!LIB_FETCHING) {
    LIB_FETCHING = fetch("/taglib/api/library")
      .then((r) => r.json())
      .then((data) => {
        LIB_CACHE = data.library || { categories: [] };
        return LIB_CACHE;
      })
      .finally(() => { LIB_FETCHING = null; });
  }
  return LIB_FETCHING;
}

function invalidateLibraryCache() {
  LIB_CACHE = null;
}

/* ---------------------------------------------------- settings helpers */

function getSetting(id, fallback) {
  try {
    const v = app.extensionManager?.setting?.get?.(id);
    if (v !== undefined && v !== null) return v;
  } catch {}
  try {
    const raw = localStorage.getItem("taglib." + id);
    if (raw !== null) return JSON.parse(raw);
  } catch {}
  return fallback;
}

function setSetting(id, value) {
  try {
    app.extensionManager?.setting?.set?.(id, value);
    return;
  } catch {}
  try { localStorage.setItem("taglib." + id, JSON.stringify(value)); } catch {}
}

/* ---------------------------------------------------- state */

function defaultState() {
  return {
    // 面板只显示这里 —— "已添加到本节点" 的标签, 每条:
    // { en, zh?, nsfw?, enabled:bool, pinned?:true }
    tags: [],
    // 排除的类目 (分类名数组): 随机模式抽不到, 手动启用标签也不输出
    exclude_categories: [],
    category_random: {},
    avoid_conflicts: true,
    nsfw: null,
  };
}

function getState(node) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  let st = { ...defaultState(), tags: [] };
  try {
    const raw = JSON.parse(w.value || "{}");
    st = { ...st, ...raw, tags: Array.isArray(raw.tags) ? raw.tags : [] };
  } catch {}
  return st;
}

function getNsfwEffective(node) {
  // state.nsfw 显式覆盖 > 全局设置
  const st = getState(node);
  if (st.nsfw === true || st.nsfw === false) return st.nsfw;
  return !!getSetting(SET_DEFAULT_NSFW, false);
}

function setState(node, patch) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  if (!w) return;
  w.value = JSON.stringify({ ...getState(node), ...patch });
  node.setDirtyCanvas?.(true, true);
}

/* ---------------------------------------------------- panel build */

export function buildPanelWidget(node, container) {
  injectPanelStyle();
  container.classList.add("taglib-panel");

  const ui = { activeCat: null, filter: "", mode: "manual", chipsBoxHeight: null };
  // activeCat=null -> 显示全部分类的 chips; 点胶囊切换到该分类; 再点取消回全部


  container.innerHTML = `
    <div class="tl-head">
      <span class="tl-logo">🏷</span>
      <span class="tl-title">标签库</span>
      <span class="tl-head-spacer"></span>
      <label class="tl-hint" style="display:inline-flex;align-items:center;gap:5px;cursor:pointer"
             title="NSFW 标签显示与抽取">
        <span>NSFW</span><span class="tl-switch tl-nsfw-sw"></span>
      </label>
      <button class="tl-btn icon tl-lang-btn" data-act="lang" title="标签显示语言 (双语/英文/中文)">文A</button>
      <button class="tl-btn icon tl-conflict-btn" data-act="conflict" title="防冲突开关 (随机时同组互斥)">🚫</button>
      <button class="tl-btn primary" data-act="addtags" title="从标签库挑选标签添加">➕ 添加标签</button>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="🔍 过滤已添加的标签…" />
      <div class="tl-seg tl-mode-seg" title="工作模式">
        <button data-mode="manual">手动</button>
        <button data-mode="random_by_category">按类随机</button>
        <button data-mode="random_mix">组合随机</button>
      </div>
    </div>
    <div class="tl-chipzone"></div>
    <div class="tl-preview-row">
      <div class="tl-preview"></div>
      <button class="tl-roll-btn" data-act="roll">🎲 ROLL</button>
    </div>
  `;

  const $ = (cls) => container.querySelector(cls);
  const chipzoneEl = $(".tl-chipzone");
  const searchEl = $(".tl-search");
  const previewEl = $(".tl-preview");
  const modeSeg = $(".tl-mode-seg");
  const nsfwSw = $(".tl-nsfw-sw");

  /* ---------- mode ---------- */
  function syncModeWidgets() {
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) ui.mode = modeW.value;
    modeSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === ui.mode));
    chipzoneEl.style.display = ui.mode === "random_mix" ? "none" : "";
  }

  function setMode(m) {
    ui.mode = m;
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) { modeW.value = m; modeW.callback?.(m); }
    syncModeWidgets();
    renderAll();
    node.setDirtyCanvas?.(true);
  }

  /* ---------- nsfw ---------- */
  function renderNsfw() {
    const on = getNsfwEffective(node);
    nsfwSw.classList.toggle("on", on);
    container.dataset.nsfw = on ? "1" : "0";
  }

  function toggleNsfw() {
    const cur = getNsfwEffective(node);
    setState(node, { nsfw: !cur });
    renderNsfw();
  }
  nsfwSw.parentElement.addEventListener("click", toggleNsfw);

  /* ----------Added-tags view ----------
     chipzone 现在只渲染 state.tags —— 用户从 ➕窗口 添加进来的标签。
     enabled=false -> 灰色停用 (不参与输出/随机); 点击变绿色启用。
  */

  // 缩放比例: 设置页 TagLibrary. chip_scale, 默认 100%
  function getScale() {
    const v = parseFloat(getSetting(SET_SCALE, 100));
    return Number.isNaN(v) ? 1 : Math.min(2, Math.max(0.5, v / 100));
  }

  function applyScale() {
    const s = getScale();
    container.style.fontSize = `${12 * s}px`;
    const fontOverride = parseInt(getSetting(SETTING_PREFIX + "chip_font_size", 0));
    const radius = parseInt(getSetting(SETTING_PREFIX + "chip_radius", 7));
    const root = document.documentElement.style;
    root.setProperty("--taglib-chip-scale", s);
    root.setProperty("--taglib-chip-font",
      (!Number.isNaN(fontOverride) && fontOverride > 0 ? fontOverride : null) || `${12 * s}px`);
    root.setProperty("--taglib-chip-radius", (!Number.isNaN(radius) ? radius : 7) + "px");
  }

  function renderTags() {
    const st = getState(node);
    chipzoneEl.innerHTML = "";
    const q = ui.filter.trim().toLowerCase();

    let shown = 0;
    st.tags.forEach((t, idx) => {
      if (q && !(
        t.en.toLowerCase().includes(q) ||
        (t.zh || "").toLowerCase().includes(q))) return;
      shown++;
      const el = document.createElement("span");
      el.className = "tl-ttag" + (t.enabled === false ? "" : " on") + (t.nsfw ? " nsfw" : "");
      el.draggable = true;
      el.title = t.enabled === false
        ? "已停用 — 点击启用"
        : "已启用 · 拖动排序 / 📌随机必含 / ✕移除";
      el.innerHTML =
        `<span class="tl-pin${t.pinned ? " pinned" : ""}" title="随机时必含">📌</span>` +
        `<b>${chipLabel(t)}</b>` +
        (t.zh && getLang() !== "zh" ? `<i class="t-zh">${t.zh}</i>` : "") +
        `<span class="tl-x" title="移除">✕</span>`;
      el.querySelector(".tl-pin").onclick = (e) => { e.stopPropagation(); togglePinIdx(idx); };
      el.querySelector(".tl-x").onclick = (e) => { e.stopPropagation(); removeTagIdx(idx); };
      el.onclick = () => toggleEnabledIdx(idx);
      el.ondragstart = (e) => { e.dataTransfer.setData("text/plain", String(idx)); el.classList.add("dragging"); };
      el.ondragend = () => { el.classList.remove("dragging"); chipzoneEl.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target")); };
      el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop-target"); };
      el.ondragleave = () => el.classList.remove("drop-target");
      el.ondrop = (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData("text/plain"));
        if (Number.isNaN(from) || from === idx) return;
        const cur = getState(node).tags.slice();
        const [moved] = cur.splice(from, 1);
        cur.splice(idx, 0, moved);
        setState(node, { tags: cur });
        renderTags();
      };
      chipzoneEl.appendChild(el);
    });

    if (!shown) {
      chipzoneEl.innerHTML = q
        ? `<div class="tl-empty">没有匹配 “${ui.filter}” 的已添加标签</div>`
        : `<div class="tl-empty">还没有添加标签<br/>点右上「➕ 添加标签」从库中挑选</div>`;
    }
    previewEl.textContent = outputPreview(st.tags);
  }

  function outputPreview(tags) {
    const st = getState(node);
    const excl = new Set(st.exclude_categories || []);
    // 排除类目的标签: 查库拿分类归属; 库未加载时按标签名匹配 (best effort)
    const catOfTag = new Map();
    for (const c of (LIB_CACHE?.categories || [])) {
      for (const s of c.subcategories || []) {
        for (const t of s.tags || []) catOfTag.set(t.en.toLowerCase(), c.name);
      }
    }
    const parts = tags
      .filter((t) => t.enabled !== false)
      .filter((t) => !excl.has(catOfTag.get(t.en.toLowerCase())))
      .map((t) => t.en);
    return parts.length ? "→ " + parts.join(", ") : "(无启用标签)";
  }

  function toggleEnabledIdx(idx) {
    const st = getState(node);
    if (!st.tags[idx]) return;
    st.tags[idx].enabled = st.tags[idx].enabled === false;
    setState(node, { tags: st.tags });
    renderTags();
  }

  function removeTagIdx(idx) {
    const st = getState(node);
    st.tags.splice(idx, 1);
    setState(node, { tags: st.tags });
    renderTags();
  }

  function togglePinIdx(idx) {
    const st = getState(node);
    if (!st.tags[idx]) return;
    st.tags[idx].pinned = !st.tags[idx].pinned;
    setState(node, { tags: st.tags });
    renderTags();
  }

  /* ---------- misc ---------- */
  function rollSeed() {
    const seedW = node.widgets?.find((x) => x.name === "seed");
    if (seedW) {
      seedW.value = Math.floor(Math.random() * 4294967295);
      seedW.callback?.(seedW.value);
      node.setDirtyCanvas?.(true);
    }
  }

  /* ---------- 语言显示 ---------- */
  function getLang() { return getSetting(SET_LANG, "bilingual"); }

  function cycleLang() {
    const order = ["bilingual", "en", "zh"];
    const cur = getLang();
    const next = order[(order.indexOf(cur) + 1) % order.length];
    setSetting(SET_LANG, next);
    container.querySelector(".tl-lang-btn").textContent =
      next === "bilingual" ? "文A" : next === "en" ? "EN" : "中";
    renderChips();
    renderSelected();
  }

  function chipLabel(t) {
    const lang = getLang();
    if (lang === "en") return t.en;
    if (lang === "zh") return (t.zh || t.en);
    return `${t.en}${t.zh ? `<span style="opacity:.55;font-size:10px">${t.zh}</span>` : ""}`;
  }

  function renderConflictBtn() {
    const on = getState(node).avoid_conflicts !== false;
    const b = container.querySelector(".tl-conflict-btn");
    b.textContent = on ? "🚫" : "⚔";
    b.title = on ? "防冲突已开启 (随机时同组互斥) — 点击关闭"
                 : "防冲突已关闭 — 点击开启";
    b.style.opacity = on ? "1" : ".45";
  }

  function renderAll() {
    renderTags(); renderNsfw(); renderConflictBtn();
  }

  /* ---------- ➕ 添加标签窗口 (全库挑选器) ---------- */
  function openTagPicker() {
    let dlg = document.getElementById("taglib-picker-dialog");
    if (dlg) { dlg.close(); dlg.remove(); }
    dlg = document.createElement("dialog");
    dlg.id = "taglib-picker-dialog";
    dlg.style.cssText =
      "width:min(92vw,1200px);height:min(90vh,860px);border:none;border-radius:14px;" +
      "padding:0;background:#15171d;color:#e3e7ee;max-width:none;max-height:none;";
    dlg.innerHTML = `<div id="taglib-picker-root" style="width:100%;height:100%;overflow:hidden"></div>`;
    document.body.appendChild(dlg);
    dlg.showModal();
    mountTagPicker(dlg.querySelector("#taglib-picker-root"), {
      onCancel: () => { dlg.close(); dlg.remove(); },
      onConfirm: (picked) => {
        // picked: [{en, zh?, nsfw?}] -> 追加到 state.tags
        const st = getState(node);
        const have = new Set(st.tags.map((t) => t.en.toLowerCase()));
        for (const p of picked) {
          if (!have.has(p.en.toLowerCase())) {
            st.tags.push({ ...p, enabled: true });
            have.add(p.en.toLowerCase());
          }
        }
        setState(node, { tags: st.tags });
        renderTags();
        dlg.close(); dlg.remove();
      },
      getExisting: () => new Set(getState(node).tags.map((t) => t.en.toLowerCase())),
      getExcluded: () => getState(node).exclude_categories || [],
      setExcluded: (cats) => { setState(node, { exclude_categories: cats }); },
      node,
    });
  }

  /* ---------- events ---------- */
  container.querySelector('[data-act="addtags"]').onclick = openTagPicker;
  container.querySelector('[data-act="roll"]').onclick = rollSeed;
  container.querySelector('[data-act="lang"]').onclick = cycleLang;
  container.querySelector('[data-act="conflict"]').onclick = () => {
    const cur = getState(node).avoid_conflicts !== false;
    setState(node, { avoid_conflicts: !cur });
    renderConflictBtn();
  };
  searchEl.oninput = () => { ui.filter = searchEl.value; renderTags(); };
  modeSeg.querySelectorAll("button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  /* ---------- init ---------- */
  applyScale();
  syncModeWidgets();
  fetchLibrary()
    .then(renderAll)
    .catch((err) => { container.innerHTML = `<div class="tl-empty">标签库加载失败: ${err}</div>`; });

  return {
    refresh: async () => {
      invalidateLibraryCache();
      await fetchLibrary();
      applyScale();
      renderAll();
    },
  };
}

/* --------------------------------------------- tag picker (全库挑选器) */

function mountTagPicker(rootEl, { onCancel, onConfirm, getExisting, getExcluded, setExcluded, node }) {
  const ui = { activeCat: null, filter: "", picked: [], tab: "pick" };  // pick | exclude

  rootEl.innerHTML = `
    <style>
      .tp-wrap { display:flex; flex-direction:column; height:100%; font:12.5px/1.5 "Segoe UI","Microsoft YaHei",sans-serif; }
      .tp-head { display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid rgba(255,255,255,.09); }
      .tp-head h2 { margin:0; font-size:15px; }
      .tp-search { flex:1; max-width:420px; background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.12);
                   border-radius:8px; color:#e3e7ee; padding:6px 12px; outline:none; font-size:12.5px; }
      .tp-cols { flex:1; display:flex; min-height:0; }
      .tp-cats { width:200px; border-right:1px solid rgba(255,255,255,.08); overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:4px; }
      .tp-cat {
        display:flex; align-items:center; gap:7px; padding:7px 10px; border-radius:9px;
        cursor:pointer; border:1px solid transparent; transition:.12s;
      }
      .tp-cat:hover { background:rgba(255,255,255,.05); }
      .tp-cat.active { background:color-mix(in srgb, currentColor 14%, transparent); border-color:currentColor; }
      .tp-cat .nm { flex:1; }
      .tp-cat .ct { font-size:11px; color:#8b93a5; }
      .tp-chips { flex:1; overflow-y:auto; padding:14px 16px; }
      .tp-sub { font-size:11px; color:#8b93a5; margin:10px 0 6px; letter-spacing:.03em; }
      .tp-grid { display:flex; flex-wrap:wrap; gap:5px; }
      .tp-tag {
        --c:#54a0ff;
        border:1px solid color-mix(in srgb, var(--c) 30%, rgba(255,255,255,.13));
        background:color-mix(in srgb, var(--c) 8%, rgba(255,255,255,.04));
        border-radius:8px; padding:3px 10px; cursor:pointer; font-size:12px; transition:.12s;
      }
      .tp-tag:hover { background:color-mix(in srgb, var(--c) 20%, transparent); transform:translateY(-1px); }
      .tp-tag.picked { background:var(--c); color:#fff; box-shadow:0 0 8px -2px var(--c); }
      .tp-tag.picked::before { content:"✓ "; }
      .tp-foot { display:flex; align-items:center; gap:10px; padding:11px 16px; border-top:1px solid rgba(255,255,255,.09); }
      .tp-count { font-size:13px; font-weight:600; color:#54a0ff; }
      .tp-btn { border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06); color:inherit;
                border-radius:8px; padding:7px 18px; cursor:pointer; font-size:13px; }
      .tp-btn.primary { background:linear-gradient(135deg,rgba(84,160,255,.35),rgba(84,160,255,.2));
                        border-color:rgba(84,160,255,.55); font-weight:600; }
      .tp-btn:hover { filter:brightness(1.25); }
      .tp-tabbtn {
        border:1px solid rgba(255,255,255,.14); background:transparent; color:#aab3c5;
        border-radius:8px; padding:5px 12px; cursor:pointer; font-size:12.5px;
      }
      .tp-tabbtn.active { background:rgba(84,160,255,.18); border-color:rgba(84,160,255,.5); color:#cfe4ff; }
      .tp-exc-card {
        display:flex; align-items:center; gap:10px; padding:9px 13px; margin-bottom:6px;
        border:1px solid rgba(255,255,255,.10); border-radius:10px; background:rgba(255,255,255,.03);
      }
      .tp-exc-card.excluded { border-color: rgba(255,107,107,.55); background: rgba(255,71,87,.10); }
      .tp-exc-card .nm { flex:1; font-size:13px; }
      .tp-exc-card .why { font-size:11px; color:#f7a4b1; }
      .tp-exc-hint { font-size:12px; color:#8b93a5; margin-bottom:12px; line-height:1.6; }
    </style>
    <div class="tp-wrap">
      <div class="tp-head">
        <h2>🏷 从标签库添加</h2>
        <button class="tp-tabbtn tp-picktab active">挑标签</button>
        <button class="tp-tabbtn tp-excludetab">🚫 排除类目</button>
        <input class="tp-search" placeholder="🔍 搜中文 / 英文 / 别名…" />
        <span style="flex:1"></span>
      </div>
      <div class="tp-cols">
        <aside class="tp-cats"></aside>
        <section class="tp-chips"><div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">加载中…</div></section>
        <section class="tp-excview" style="display:none;flex:1;overflow-y:auto;padding:16px 20px;"></section>
      </div>
      <div class="tp-foot">
        <span class="tp-footinfo">已挑选 <b class="tp-count">0</b> 个</span>
        <span style="flex:1"></span>
        <button class="tp-btn tp-cancel">取消</button>
        <button class="tp-btn primary tp-ok">✔ 确定并保存</button>
      </div>
    </div>
  `;

  const $ = (s) => rootEl.querySelector(s);
  const catsBox = $(".tp-cats");
  const chipsBox = $(".tp-chips");
  const searchEl = $(".tp-search");
  const countEl = $(".tp-count");

  function libCats() { return (LIB_CACHE && LIB_CACHE.categories) || []; }

  function renderCats() {
    catsBox.innerHTML = "";
    const mk = (id, label, count, icon) => {
      const el = document.createElement("div");
      el.className = "tp-cat" + (ui.activeCat === id ? " active" : "");
      el.style.color = id === "__all__" ? "#9ecbff" : findColor(id) || "#888";
      el.innerHTML = `<span>${icon || "📁"}</span><span class="nm">${label}</span><span class="ct">${count}</span>`;
      el.onclick = () => { ui.activeCat = id; renderCats(); renderChips(); };
      catsBox.appendChild(el);
    };
    let allCount = 0;
    for (const c of libCats()) allCount += countTags(c);
    mk("__all__", "全部", allCount, "🗂");
    for (const c of libCats()) mk(c.id, `${c.icon || ""} ${c.name}`, countTags(c), "");
  }

  function findColor(id) {
    return (libCats().find((c) => c.id === id) || {}).color;
  }

  function countTags(cat) {
    let n = 0;
    for (const s of cat.subcategories || []) n += (s.tags || []).length;
    return n;
  }

  function matches(t) {
    const q = ui.filter.trim().toLowerCase();
    if (!q) return true;
    return t.en.toLowerCase().includes(q) ||
           (t.zh || "").toLowerCase().includes(q) ||
           (t.aliases || []).some((a) => a.toLowerCase().includes(q));
  }

  function renderChips() {
    chipsBox.innerHTML = "";
    const existing = getExisting();
    const cats = libCats().filter((c) => !ui.activeCat || ui.activeCat === "__all__" || c.id === ui.activeCat);
    let shown = 0;
    for (const cat of cats) {
      const clr = cat.color || "#54a0ff";
      for (const sub of cat.subcategories || []) {
        const hits = (sub.tags || []).filter(matches);
        if (!hits.length) continue;
        shown += hits.length;
        const head = document.createElement("div");
        head.className = "tp-sub";
        head.textContent = `${cat.icon || ""} ${cat.name} / ${sub.name}`;
        chipsBox.appendChild(head);
        const grid = document.createElement("div");
        grid.className = "tp-grid";
        for (const t of hits) {
          const isPicked = ui.picked.some((p) => p.en.toLowerCase() === t.en.toLowerCase());
          const isExisting = existing.has(t.en.toLowerCase());
          const el = document.createElement("span");
          el.className = "tp-tag" + (isPicked ? " picked" : "") + (isExisting ? " dim" : "");
          if (isExisting) { el.title = "已在节点上"; el.style.opacity = ".38"; }
          else {
            el.title = t.nsfw ? "🔞 NSFW 标签" : "";
            el.onclick = () => {
              const i = ui.picked.findIndex((p) => p.en.toLowerCase() === t.en.toLowerCase());
              if (i >= 0) ui.picked.splice(i, 1);
              else ui.picked.push({ en: t.en, zh: t.zh, nsfw: !!t.nsfw });
              countEl.textContent = ui.picked.length;
              el.classList.toggle("picked", i < 0);
            };
          }
          el.innerHTML = `${t.en}${t.zh ? `<span style="opacity:.55"> ${t.zh}</span>` : ""}`;
          grid.appendChild(el);
        }
        chipsBox.appendChild(grid);
      }
    }
    if (!shown) chipsBox.innerHTML = `<div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">没找到匹配的标签</div>`;
  }

  /* ---------- 排除类目视图 ---------- */
  const excView = $(".tp-excview");
  const pickCols = [".tp-cats", ".tp-chips"].map((s) => rootEl.querySelector(s));

  function upstreamText() {
    // 收集上游 prefix 文本 (已连线的输入 widget / 上游节点预览)
    let text = "";
    try {
      for (const inp of node?.inputs || []) {
        if (inp.name !== "prefix" || !inp.link) continue;
        const link = window.app?.graph?.links?.get?.(inp.link) || window.app?.graph?.links?.[inp.link];
        const srcNode = link ? window.app.graph._nodes.find((x) => x.id === link.origin_id) : null;
        const srcW = srcNode?.widgets?.find((w) => w.name === "text" || w.name === "prompt");
        if (srcW?.value) text += " " + srcW.value;
      }
    } catch {}
    return text.toLowerCase();
  }

  function suggestExcludes() {
    const up = upstreamText();
    if (!up) return {};
    const hints = {};
    const RULE = [
      ["头发", ["hair", "bangs", "ponytail", "twintails", "braid", "bob cut"]],
      ["人物特征", ["eyes", "blue eyes", "green eyes", "red eyes", "pointed ears", "elf"]],
      ["表情", ["smile", "smirk", "crying", "blush", "open mouth", "closed mouth", "angry"]],
      ["服装", ["dress", "uniform", "hoodie", "kimono", "skirt", "bikini", "swimsuit", "jacket"]],
      ["动作姿势", ["sitting", "standing", "lying", "kneeling", "arms", "walking"]],
      ["配饰·道具", ["glasses", "hat", "necklace", "earrings", "sword", "bag"]],
      ["镜头构图", ["close-up", "from above", "from below", "portrait", "wide shot", "cowboy shot"]],
      ["光影", ["backlighting", "rim lighting", "dappled", "sunlight", "moonlight"]],
      ["天气·时间", ["night", "sunset", "rain", "snow", "starry"]],
      ["场景", ["bedroom", "classroom", "outdoors", "forest", "beach", "city"]],
    ];
    for (const [catName, keys] of RULE) {
      const hit = keys.filter((k) => up.includes(k));
      if (hit.length) hints[catName] = hit.slice(0, 3);
    }
    return hints;
  }

  function renderExclude() {
    const excluded = new Set(getExcluded ? getExcluded() : []);
    const hints = suggestExcludes();
    excView.innerHTML = `
      <div class="tp-exc-hint">
        勾选要<b>排除</b>的分类: 排除后<b>随机抽取</b>与<b>输出</b>都会跳过这些分类的标签。<br/>
        用途: 上游提示词已经有发色/眼睛等描述时 (如 <code>blue hair, blue eyes</code>),
        排除对应类目避免重复冲突。
        ${Object.keys(hints).length ? '<br/>💡 检测到上游提示词可能已包含以下类目的内容, 已用 <span style="color:#f7a4b1">粉色标记</span>:' : ""}
      </div>
    `;
    for (const cat of libCats()) {
      if (cat.id === "nsfwcat") continue;  // NSFW 由 nsfw_mode 管
      const isEx = excluded.has(cat.name);
      const why = hints[cat.name] ? `上游已有: ${hints[cat.name].join(", ")}` : "";
      const card = document.createElement("div");
      card.className = "tp-exc-card" + (isEx ? " excluded" : "");
      card.innerHTML = `
        <input type="checkbox" ${isEx ? "checked" : ""} style="width:16px;height:16px;accent-color:#ff4757"/>
        <span>${cat.icon || ""}</span>
        <span class="nm">${cat.name}<span style="color:#8b93a5;font-size:11px"> · ${countTags(cat)} 条</span></span>
        <span class="why">${why}</span>
      `;
      card.querySelector("input").onchange = (e2) => {
        const cur = new Set(getExcluded ? getExcluded() : []);
        e2.target.checked ? cur.add(cat.name) : cur.delete(cat.name);
        setExcluded([...cur]);
        card.classList.toggle("excluded", e2.target.checked);
      };
      excView.appendChild(card);
    }
  }

  function switchTab(tab) {
    ui.tab = tab;
    rootEl.querySelector(".tp-picktab").classList.toggle("active", tab === "pick");
    rootEl.querySelector(".tp-excludetab").classList.toggle("active", tab === "exclude");
    for (const el of pickCols) el.style.display = tab === "pick" ? "" : "none";
    excView.style.display = tab === "exclude" ? "block" : "none";
    searchEl.style.visibility = tab === "pick" ? "visible" : "hidden";
    $(".tp-footinfo").innerHTML = tab === "pick"
      ? `已挑选 <b class="tp-count">${ui.picked.length}</b> 个`
      : (() => {
          const n = (getExcluded ? getExcluded().length : 0);
          return `已排除 <b style="color:#ff6b6b">${n}</b> 个分类`;
        })();
    if (tab === "exclude") renderExclude();
  }
  rootEl.querySelector(".tp-picktab").onclick = () => switchTab("pick");
  rootEl.querySelector(".tp-excludetab").onclick = () => switchTab("exclude");

  searchEl.oninput = () => { ui.filter = searchEl.value; renderChips(); };
  $(".tp-cancel").onclick = onCancel;
  $(".tp-ok").onclick = () => onConfirm(ui.picked);

  renderCats();
  renderChips();
}

/* ------------------------------------------------- manager dialog */

function openManagerDialog() {
  let dlg = document.getElementById("taglib-manager-dialog");
  if (dlg) { dlg.close(); dlg.remove(); }
  dlg = document.createElement("dialog");
  dlg.id = "taglib-manager-dialog";
  dlg.style.cssText =
    "width:min(96vw,1400px);height:min(94vh,980px);border:none;border-radius:14px;" +
    "padding:0;background:#17191f;color:#dfe3ea;max-width:none;max-height:none;";
  dlg.innerHTML = `<iframe src="${MANAGER_URL}" style="width:100%;height:100%;border:0;border-radius:14px;display:block"></iframe>`;
  document.body.appendChild(dlg);
  dlg.showModal();
  dlg.addEventListener("close", () => {
    invalidateLibraryCache();
    window.dispatchEvent(new CustomEvent("taglib-updated"));
  });
}

/* --------------------------------------------------------- register */

app.registerExtension({
  name: "zhixin.tagLibrary",

  /* ComfyUI 设置面板里的专属设置 */
  settings: [
    {
      id: SET_DEFAULT_MODE,
      name: "标签库: 新节点的默认模式",
      type: "combo",
      options: ["manual", "random_by_category", "random_mix"],
      defaultValue: "manual",
      tooltip: "手动=点选输出 / 按类随机 / 组合随机",
    },
    {
      id: SET_DEFAULT_NSFW,
      name: "标签库: 默认启用 NSFW 标签",
      type: "boolean",
      defaultValue: false,
      tooltip: "关闭时隐藏并排除 NSFW 标签；也可在每个节点上单独开关",
    },
    {
      id: SET_SCALE,
      name: "标签库: 整体比例 (%) — 按钮/字体等内部 UI 缩放",
      type: "number",
      attrs: { min: 50, max: 200, step: 5 },
      defaultValue: 100,
      tooltip: "100% = 默认大小; 影响面板内所有按钮/字体/chip 大小; 面板高度自动跟随节点",
    },
    {
      id: SETTING_PREFIX + "chip_font_size",
      name: "标签库: 标签字号覆盖 (px, 0=跟随比例)",
      type: "number",
      attrs: { min: 0, max: 24, step: 1 },
      defaultValue: 0,
      tooltip: "单独指定标签文字大小; 0 = 使用上面的整体比例",
    },
    {
      id: SETTING_PREFIX + "chip_radius",
      name: "标签库: 标签圆角 (px)",
      type: "number",
      attrs: { min: 0, max: 16, step: 1 },
      defaultValue: 7,
      tooltip: "标签芯片的圆角半径",
    },
    {
      id: SET_LANG,
      name: "标签库: 标签文字显示",
      type: "combo",
      options: [
        { text: "双语 (英文+中文)", value: "bilingual" },
        { text: "仅英文", value: "en" },
        { text: "仅中文", value: "zh" },
      ],
      defaultValue: "bilingual",
      tooltip: "输出永远只有英文; 这里只控制面板里标签按钮的显示文字",
    },
  ],

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const node = this;

      // 面板随节点宽度自适应: 监听节点 resize, 同步最小宽度 + 重算高度
      const PANEL_MIN_W = 280;
      function syncPanelToNode() {
        // 宽度不再强制节点变宽 —— 面板 CSS (flex/min-width:0) 跟随节点实际宽度收缩,
        // 避免"面板凸出节点"的错位。仅提醒画布重绘。
        node.setDirtyCanvas?.(true, true);
      }
      const origOnResize = nodeType.prototype.onResize;
      nodeType.prototype.onResize = function (size) {
        syncPanelToNode();
        return origOnResize?.call(this, size);
      };

      // 新节点应用默认模式设置
      setTimeout(() => {
        // ---- 插槽中文化 (2进2出是什么) ----
        const IN_LABELS = {
          prefix: "⬅️ 前置文本 (可选: 上游提示词, 拼在标签前面)",
          suffix: "⬅️ 后置文本 (可选: 拼在标签后面)",
        };
        const OUT_LABELS = {
          positive: "➡️ 正面提示词 (连 CLIPTextEncode.text)",
          tags_preview: "➡️ 标签预览 (接 Preview Text 节点查看实际输出)",
        };
        for (let i = 0; i < (node.inputs || []).length; i++) {
          const inp = node.inputs[i];
          if (IN_LABELS[inp.name]) inp.label = IN_LABELS[inp.name];
        }
        for (let i = 0; i < (node.outputs || []).length; i++) {
          const out = node.outputs[i];
          if (OUT_LABELS[out.name]) { out.label = OUT_LABELS[out.name]; out.localized_name = OUT_LABELS[out.name]; }
        }
        node.onConnectionsChange = (() => {
          const orig = node.onConnectionsChange;
          return function () {
            // 连线后 ComfyUI 可能重算 slot label -> 保持中文
            for (let i = 0; i < (node.inputs || []).length; i++) {
              const inp = node.inputs[i];
              if (IN_LABELS[inp.name] && !inp.label) inp.label = IN_LABELS[inp.name];
            }
            return orig?.apply(this, arguments);
          };
        })();

        // ---- 中文化 widget 标签 (改 name 的显示别名) ----
        const LABELS = {
          mode: "模式",
          seed: "随机种子",
          nsfw_mode: "NSFW 过滤",
          min_tags: "随机最少标签数",
          max_tags: "随机最多标签数",
          search_text: "随机过滤词(中/英/别名)",
          separator: "输出分隔符",
          use_weights_syntax: "输出加权重语法 (tag:1.2)",
          dedupe: "输出去重",
          pinned_required: "📌必含标签强制加入随机结果",
        };
        for (const w of node.widgets || []) {
          if (LABELS[w.name]) {
            try {
              w.label = LABELS[w.name];
              if (w.options) w.options.multiline = w.options.multiline; // noop keep ref
            } catch {}
          }
          if (w.name === "nsfw_mode" && w.element?.tagName === "SELECT") {}
        }
        // ComfyUI 渲染用 w.label ?? w.name, label 设置即生效;
        // 老版本没有 label 字段时 hack 到 onLabel 需要额外兼容, 现代版都支持.
        const modeW2 = node.widgets?.find((w) => w.name === "mode");
        if (modeW2) {
          // combo 选项中文化 (显示层): ComfyUI 用 options.values 传值, label 映射显示
          const disp = { manual: "手动选签", random_by_category: "按分类随机", random_mix: "组合随机" };
          if (!modeW2.__zhPatched) {
            modeW2.__zhPatched = true;
            const origToString = {};
            // 简单方案: tooltip 说明含义即可, 值保持英文 (兼容工作流)
          }
        }
        const nsfwW = node.widgets?.find((w) => w.name === "nsfw_mode");
        if (nsfwW) nsfwW.tooltip = "off=排除 NSFW / on=混入 NSFW / only=只用 NSFW";

        const modeW = node.widgets?.find((w) => w.name === "mode");
        const defMode = getSetting(SET_DEFAULT_MODE, "manual");
        if (modeW && Object.values(modeW.options || {}).includes(defMode)) {
          modeW.value = defMode;
        }
        const defNsfw = getSetting(SET_DEFAULT_NSFW, false);
        if (defNsfw) {
          const sw = node.widgets?.find((w) => w.name === "selection_state");
          if (sw) {
            try {
              const st = JSON.parse(sw.value || "{}");
              st.nsfw = true;
              sw.value = JSON.stringify(st);
            } catch {}
          }
        }
        // 隐藏两个内部 widget
        for (const name of ["selection_state", "category_weights"]) {
          const w = node.widgets?.find((x) => x.name === name);
          if (w) {
            w.computeSize = () => [0, -4];
            if (w.inputEl) w.inputEl.style.display = "none";
            try { w.hidden = true; } catch {}
          }
        }
      }, 0);

      const holder = document.createElement("div");
      holder.className = "taglib-widget-holder";
      const panelApi = buildPanelWidget(node, holder);
      const domW = node.addDOMWidget("taglib_panel", "panel", holder, { hideOnZoom: false });
      node._taglibPanelApi = panelApi;

      // 面板高度跟随节点: 新版前端不再触发 DOM widget 的 onDraw,
      // 用 rAF 轻量同步循环 (同一帧有 dirty 才重算, 空闲时零开销)
      domW._syncHeight = function () {
        try {
          const available = node.size[1] - (domW.last_y || w_lastY_fallback(node)) - 8;
          const h = Math.max(90, Math.round(available));
          if (holder.style.height !== h + "px") holder.style.height = h + "px";
        } catch {}
      };
      if (!window.__taglibSync) {
        window.__taglibSync = requestAnimationFrame(function __tlLoop() {
          window.__taglibSync = requestAnimationFrame(__tlLoop);
          try {
            // 只在画布脏时同步 (node._dirty 或 canvas dirty 标记)
            const g = window.app?.graph;
            if (!g) return;
            for (const nd of g._nodes) {
              if (nd.type !== NODE_NAME || !nd.widgets) continue;
              const dw = nd.widgets.find((x) => x.name === "taglib_panel");
              if (!dw || !dw._syncHeight || !dw.last_y) continue;
              dw._syncHeight();
            }
          } catch {}
        });
      }
      function w_lastY_fallback(n) {
        let y = 0;
        for (const ww of n.widgets) {
          if (ww === domW) break;
          y += ww.computeSize ? ww.computeSize(n.size[0])[1] : 20;
        }
        return y + 30;
      }

      // 让 ComfyUI 量取面板真实高度: computeSize 报告 holder 实际高, 宽度=节点内容宽
      domW.computeSize = function (width) {
        // 宽度永远跟随节点实际宽度 (不再强制最小宽, 面板 CSS 自适应收缩)
        return [Math.max(width || 0, 200), -2];  // -2 = DOM widget 自管高度
      };
      // 高度变化(分类展开/chips 渲染/模式切换)时通知画布重算布局
      panelApi.onChange = () => {
        if (node.onResize) node.onResize(node.size);
        else node.setDirtyCanvas?.(true, true);
        app.canvas?.setDirty?.(true, true);
      };
      const ro = new ResizeObserver(() => panelApi.onChange && panelApi.onChange());
      ro.observe(holder);

      syncPanelToNode();
      // 默认尺寸: 只在宽度不足时撑到最小可用宽 (280), 高度尊重用户/前端默认, 不强加 420
      node.setSize([
        Math.max(node.size[0], 280),
        Math.max(node.size[1], Math.round((domW.last_y || w_lastY_fallback(node)) + 240)),
      ]);

      window.addEventListener("taglib-updated", () => panelApi.refresh());
      return r;
    };
  },

  async setup() {
    try {
      app.extensionManager?.registerCommand?.({
        id: "zhixin.openTagLibraryManager",
        label: "🏷 打开标签库管理页",
        function: () => openManagerDialog(),
      });
    } catch {}
  },
});
