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
const SET_PANEL_HEIGHT = SETTING_PREFIX + "panel_max_height";

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
  return { selected: [], pinned: [], category_random: {}, nsfw: null };
}

function getState(node) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  let st = defaultState();
  try { st = { ...st, ...JSON.parse(w.value || "{}") }; } catch {}
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

  container.innerHTML = `
    <div class="tl-head">
      <span class="tl-logo">🏷</span>
      <span class="tl-title">标签库</span>
      <span class="tl-hint tl-nsfw-state"></span>
      <span class="tl-head-spacer"></span>
      <label class="tl-hint" style="display:inline-flex;align-items:center;gap:5px;cursor:pointer"
             title="NSFW 标签显示与抽取">
        <span>NSFW</span><span class="tl-switch tl-nsfw-sw"></span>
      </label>
      <button class="tl-btn icon" data-act="manager" title="打开标签库管理页">⚙</button>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="🔍 搜中文 / 英文 / 别名…" />
      <div class="tl-seg tl-mode-seg" title="工作模式">
        <button data-mode="manual">手动</button>
        <button data-mode="random_by_category">按类随机</button>
        <button data-mode="random_mix">组合随机</button>
      </div>
    </div>
    <div class="tl-cats"></div>
    <div class="tl-chipzone"></div>
    <div class="tl-selzone">
      <div class="tl-zone-label">
        <span>已选 <b class="tl-n">0</b> · 拖动排序 · 📌 随机必含</span>
        <span class="tl-clearbtn">清空 ✕</span>
      </div>
      <div class="tl-selected"></div>
    </div>
    <div class="tl-preview-row">
      <div class="tl-preview"></div>
      <button class="tl-roll-btn" data-act="roll">🎲 ROLL</button>
    </div>
  `;

  const $ = (cls) => container.querySelector(cls);
  const catsEl = $(".tl-cats");
  const chipzoneEl = $(".tl-chipzone");
  const selectedEl = $(".tl-selected");
  const searchEl = $(".tl-search");
  const previewEl = $(".tl-preview");
  const modeSeg = $(".tl-mode-seg");
  const nsfwSw = $(".tl-nsfw-sw");
  const nsfwStateEl = $(".tl-nsfw-state");

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
    nsfwStateEl.textContent = on ? "" : "";
    container.dataset.nsfw = on ? "1" : "0";
  }

  function toggleNsfw() {
    const cur = getNsfwEffective(node);
    setState(node, { nsfw: !cur });   // 显式写进状态 (跟工作流走)
    renderNsfw();
    renderCats();
    renderChips();
  }
  nsfwSw.parentElement.addEventListener("click", toggleNsfw);

  /* ---------- helpers ---------- */
  function visibleLib() {
    const nsfwOn = getNsfwEffective(node);
    if (!LIB_CACHE) return { categories: [] };
    if (nsfwOn) return LIB_CACHE;
    // off: 隐藏 nsfw 子分类/标签 (界面层面)
    const cats = LIB_CACHE.categories.map((c) => ({
      ...c,
      subcategories: (c.subcategories || [])
        .map((s) => ({ ...s, tags: (s.tags || []).filter((t) => !t.nsfw) }))
        .filter((s) => s.tags.length),
    })).filter((c) => c.subcategories.length);
    return { categories: cats };
  }

  function allTagsOf(cat) {
    const rows = [];
    for (const sub of cat.subcategories || []) rows.push(...(sub.tags || []));
    return rows;
  }

  /* ---------- cats row ---------- */
  function renderCats() {
    const st = getState(node);
    const lib = visibleLib();
    const selSet = new Set(st.selected);
    catsEl.innerHTML = "";

    for (const cat of lib.categories) {
      const pill = document.createElement("span");
      pill.className = "tl-cat-pill" + (ui.activeCat === cat.id ? " active" : "");
      pill.style.color = cat.color || "#54a0ff";

      const n = allTagsOf(cat).filter((t) => selSet.has(t.id)).length;
      pill.innerHTML =
        `${cat.icon || "🏷"} ${cat.name} <span class="tl-badge">${n}</span>` +
        (hasNsfwInCat(cat) ? ' <span title="含 NSFW 标签" style="font-size:9px">🔞</span>' : "");

      // 按类随机模式下, pill 右侧内联参数
      if (ui.mode === "random_by_category") {
        const conf = (st.category_random || {})[cat.id] || {};
        const cfg = document.createElement("span");
        cfg.className = "tl-catcfg-inline";
        cfg.style.cssText = "display:inline-flex;gap:4px;margin-left:4px;font-size:10px;color:#8b93a5;align-items:center";
        cfg.innerHTML = `
          <input type="checkbox" title="参与随机" ${conf.enabled ? "checked" : ""}/>
          ×<input type="number" min="0" max="20" value="${conf.count ?? 1}"
               style="width:34px;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.14);border-radius:4px;color:#e3e7ee;font-size:10px;padding:0 3px"/>
          空<input type="number" min="0" max="100" value="${conf.empty_chance ?? 0}" title="空抽概率%"
               style="width:38px;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.14);border-radius:4px;color:#e3e7ee;font-size:10px;padding:0 3px"/>%
        `;
        const [chk, cnt, emp] = cfg.querySelectorAll("input");
        chk.onclick = (e) => e.stopPropagation();
        cnt.onclick = emp.onclick = (e) => e.stopPropagation();
        chk.onchange = () => updateCatConf(cat.id, { enabled: chk.checked });
        cnt.onchange = () => updateCatConf(cat.id, { count: Math.max(0, parseInt(cnt.value || "0")) });
        emp.onchange = () => updateCatConf(cat.id, { empty_chance: Math.min(100, Math.max(0, parseInt(emp.value || "0"))) });
        pill.appendChild(cfg);
      }

      pill.onclick = () => {
        ui.activeCat = ui.activeCat === cat.id ? null : cat.id;
        renderCats(); renderChips();
      };
      catsEl.appendChild(pill);
    }
  }

  function hasNsfwInCat(cat) {
    return (cat.subcategories || []).some((s) => (s.tags || []).some((t) => t.nsfw));
  }

  function updateCatConf(catId, patch) {
    const st = getState(node);
    const conf = { ...(st.category_random || {}) };
    conf[catId] = { enabled: false, count: 1, empty_chance: 0, ...conf[catId], ...patch };
    setState(node, { category_random: conf });
    renderCats();
  }

  /* ---------- chips zone ---------- */
  function renderChips() {
    const st = getState(node);
    const lib = visibleLib();
    chipzoneEl.innerHTML = "";
    const q = ui.filter.trim().toLowerCase();
    const cats = lib.categories.filter((c) => !ui.activeCat || c.id === ui.activeCat);

    let shown = 0;
    for (const cat of cats) {
      const clr = cat.color || "#54a0ff";
      for (const sub of cat.subcategories || []) {
        const hits = (sub.tags || []).filter(tagMatch);
        if (!hits.length) continue;
        shown += hits.length;

        const head = document.createElement("div");
        head.className = "tl-sub-head";
        head.innerHTML = `<span class="tl-sub-name">${cat.icon || ""} ${sub.name}</span>`;
        chipzoneEl.appendChild(head);

        const wrap = document.createElement("div");
        wrap.className = "tl-chips";
        const selSet = new Set(st.selected);
        for (const t of hits) {
          const chip = document.createElement("span");
          chip.className = "tl-chip" + (selSet.has(t.id) ? " sel" : "") + (t.nsfw ? " nsfw" : "");
          chip.style.setProperty("--c", clr);
          chip.innerHTML = `${t.en}${t.zh ? `<span style="opacity:.55;font-size:10px">${t.zh}</span>` : ""}`;
          chip.title = `${t.en} · ${t.zh || ""}${t.aliases?.length ? "\n别名: " + t.aliases.join(", ") : ""}`;
          chip.onclick = () => toggleTag(t.id);
          wrap.appendChild(chip);
        }
        chipzoneEl.appendChild(wrap);
      }
    }
    if (!shown) {
      chipzoneEl.innerHTML =
        `<div class="tl-empty">${q ? `没搜到 “${ui.filter}” — 去 ⚙管理页 添加` : "这个分类还没有标签"}</div>`;
    }
  }

  function tagMatch(t) {
    const q = ui.filter.trim().toLowerCase();
    if (!q) return true;
    return (
      t.en.toLowerCase().includes(q) ||
      (t.zh || "").toLowerCase().includes(q) ||
      (t.aliases || []).some((a) => a.toLowerCase().includes(q))
    );
  }

  function toggleTag(tagId) {
    const st = getState(node);
    const sel = new Set(st.selected);
    sel.has(tagId) ? sel.delete(tagId) : sel.add(tagId);
    setState(node, { selected: [...sel] });
    renderCats(); renderChips(); renderSelected();
  }

  /* ---------- selected zone ---------- */
  function tagIndex() {
    const map = new Map();
    for (const cat of visibleLib().categories) {
      for (const t of allTagsOf(cat)) map.set(t.id, { ...t, _color: cat.color });
    }
    return map;
  }

  function renderSelected() {
    const st = getState(node);
    selectedEl.innerHTML = "";
    $(".tl-n").textContent = st.selected.length;
    const byId = tagIndex();

    st.selected.forEach((id, idx) => {
      const info = byId.get(id) || { en: id, _color: "#888" };
      const el = document.createElement("span");
      el.className = "tl-sel-tag";
      el.draggable = true;
      el.style.setProperty("--c", info._color);
      const pinned = (st.pinned || []).includes(id);
      el.innerHTML =
        `<span class="tl-pin${pinned ? " pinned" : ""}" title="随机时必含">📌</span>` +
        `${info.en}<span class="tl-x" title="移除">✕</span>`;
      el.querySelector(".tl-pin").onclick = () => togglePin(id);
      el.querySelector(".tl-x").onclick = () => toggleTag(id);
      el.ondragstart = (e) => { e.dataTransfer.setData("text/plain", String(idx)); el.classList.add("dragging"); };
      el.ondragend = () => { el.classList.remove("dragging"); selectedEl.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target")); };
      el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop-target"); };
      el.ondragleave = () => el.classList.remove("drop-target");
      el.ondrop = (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData("text/plain"));
        if (Number.isNaN(from) || from === idx) return;
        const cur = getState(node).selected.slice();
        const [moved] = cur.splice(from, 1);
        cur.splice(idx, 0, moved);
        setState(node, { selected: cur });
        renderSelected();
      };
      selectedEl.appendChild(el);
    });

    const texts = st.selected.map((id) => (byId.get(id)?.en) || id);
    previewEl.textContent = texts.length ? "→ " + texts.join(", ") : "(未选任何标签)";
  }

  function togglePin(id) {
    const pins = new Set(getState(node).pinned || []);
    pins.has(id) ? pins.delete(id) : pins.add(id);
    setState(node, { pinned: [...pins] });
    renderSelected();
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

  function applyPanelHeight() {
    const h = parseInt(getSetting(SET_PANEL_HEIGHT, 168));
    if (!Number.isNaN(h)) chipzoneEl.style.maxHeight = h + "px";
  }

  function renderAll() {
    renderCats(); renderChips(); renderSelected(); renderNsfw();
  }

  /* ---------- events ---------- */
  container.querySelector('[data-act="manager"]').onclick = () => openManagerDialog();
  container.querySelector('[data-act="roll"]').onclick = rollSeed;
  searchEl.oninput = () => { ui.filter = searchEl.value; renderChips(); };
  modeSeg.querySelectorAll("button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  $(".tl-clearbtn").onclick = () => { setState(node, { selected: [], pinned: [] }); renderAll(); };

  /* ---------- init ---------- */
  applyPanelHeight();
  syncModeWidgets();
  fetchLibrary()
    .then(renderAll)
    .catch((err) => { container.innerHTML = `<div class="tl-empty">标签库加载失败: ${err}</div>`; });

  return {
    refresh: async () => {
      invalidateLibraryCache();
      await fetchLibrary();
      applyPanelHeight();
      renderAll();
    },
  };
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
      id: SET_PANEL_HEIGHT,
      name: "标签库: 面板标签区最大高度 (px)",
      type: "number",
      attrs: { min: 60, max: 600, step: 8 },
      defaultValue: 168,
    },
  ],

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const node = this;

      // 新节点应用默认模式设置
      setTimeout(() => {
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
      node.addDOMWidget("taglib_panel", "panel", holder, { hideOnZoom: false });
      node._taglibPanelApi = panelApi;
      node.setSize([Math.max(node.size[0], 400), node.size[1] + 380]);

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
