/**
 * ComfyUI-TagLibrary 节点面板扩展
 *
 * - 给 TagLibraryNode 挂一个 DOM widget 面板: 分类条 + chips 点选 + 已选区(拖拽排序/钉选) + 模式切换
 * - selection_state widget 双向同步 (序列化进工作流)
 * - ⚙ 打开 /taglib 管理页 iframe 全屏弹窗; 顶栏菜单注册"打开标签库管理页"
 *
 * 只使用稳定 API: app.registerExtension / beforeRegisterNodeDef / addDOMWidget / extensionManager
 */
import { app } from "../../scripts/app.js";

const NODE_NAME = "TagLibraryNode";
const MANAGER_URL = "/taglib?embed=1";

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

/* ------------------------------------------------------------------ state */

function defaultState() {
  return { selected: [], pinned: [], category_random: {} };
}

function getState(node) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  let st = defaultState();
  try { st = { ...st, ...JSON.parse(w.value || "{}") }; } catch {}
  // 去掉已不存在的 id
  const valid = new Set();
  for (const cat of LIB_CACHE?.categories || []) {
    valid.add(cat.id);
    for (const sub of cat.subcategories || []) {
      valid.add(sub.id);
      for (const t of sub.tags || []) valid.add(t.id);
    }
  }
  st.selected = (st.selected || []).filter((id) => valid.has(id));
  st.pinned = (st.pinned || []).filter((id) => valid.has(id));
  return st;
}

function setState(node, patch) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  if (!w) return;
  w.value = JSON.stringify({ ...getState(node), ...patch });
  node.setDirtyCanvas?.(true, true);
}

/* ------------------------------------------------------------------ panel */

function tagColor(node, lib) {
  // 由分类色生成 chip 底色系
  return lib.categories.find((c) => c.color)?.color || "#54a0ff";
}

function colorOfCategory(catState, catId) {
  return catState?.find?.((c) => c.id === catId)?.color;
}

export function buildPanelWidget(node, container) {
  container.classList.add("taglib-panel");
  const ui = { activeCat: null, filter: "", els: {} };

  container.innerHTML = `
    <div class="tl-head">
      <span class="tl-title">🏷 标签库</span>
      <span class="tl-head-actions">
        <button class="tl-btn" data-act="manager">⚙ 管理页</button>
        <button class="tl-btn primary" data-act="roll">🎲 ROLL</button>
      </span>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="搜中文/英文/别名…" />
      <select class="tl-mode">
        <option value="manual">手动点选</option>
        <option value="random_by_category">按类随机</option>
        <option value="random_mix">组合随机</option>
      </select>
    </div>
    <div class="tl-cats"></div>
    <div class="tl-chipzone"></div>
    <div class="tl-selected-zone">
      <div class="tl-selected-label">
        <span>已选 <b class="tl-n">0</b> · 拖拽排序 · 📌=随机时必含</span>
        <span class="tl-clear">清空✕</span>
      </div>
      <div class="tl-selected"></div>
    </div>
    <div class="tl-preview"></div>
  `;

  const $ = (cls) => container.querySelector(cls);
  const catsEl = $(".tl-cats");
  const chipzoneEl = $(".tl-chipzone");
  const selectedEl = $(".tl-selected");
  const searchEl = $(".tl-search");
  const modeEl = $(".tl-mode");
  const previewEl = $(".tl-preview");

  /* ---- sync widgets <-> panel ---- */
  function syncFromWidgets() {
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) modeEl.value = modeW.value;
    renderAll();
  }

  function setMode(v) {
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) { modeW.value = v; modeW.callback?.(v); }
    renderCats();
    chipzoneEl.style.display = v === "random_mix" ? "none" : "";
    node.setDirtyCanvas?.(true);
  }

  /* ---- rendering ---- */
  function allTagsOf(cat) {
    const rows = [];
    for (const sub of cat.subcategories || []) {
      for (const t of sub.tags || []) rows.push(t);
    }
    return rows;
  }

  function selectedCountForCat(st, catId) {
    // 该分类下被选中的数量
    let n = 0;
    const cat = (LIB_CACHE?.categories || []).find((c) => c.id === catId);
    if (!cat) return 0;
    const sel = new Set(st.selected);
    for (const t of allTagsOf(cat)) if (sel.has(t.id)) n++;
    return n;
  }

  function renderCats() {
    const st = getState(node);
    const mode = modeEl.value;
    catsEl.innerHTML = "";
    for (const cat of LIB_CACHE?.categories || []) {
      const pill = document.createElement("span");
      pill.className = "tl-cat-pill" + (ui.activeCat === cat.id ? " active" : "");
      pill.style.color = cat.color || "#888";
      const n = selectedCountForCat(st, cat.id);
      pill.innerHTML = `${cat.icon || ""} ${cat.name} <span class="tl-count">${n}</span>`;
      pill.onclick = () => {
        ui.activeCat = ui.activeCat === cat.id ? null : cat.id;
        renderCats();
        renderChips();
      };

      if (mode === "random_by_category") {
        // 分类行内随机参数
        const cfgDiv = document.createElement("span");
        cfgDiv.className = "tl-catcfg";
        const conf = (st.category_random || {})[cat.id] || {};
        cfgDiv.innerHTML = `
          <label title="该分类参与随机"><input type="checkbox" ${conf.enabled ? "checked" : ""}/>随</label>
          <label title="抽取数量">×<input type="number" min="0" max="20" value="${conf.count ?? 1}"/></label>
          <label title="空抽概率%">空<input type="number" min="0" max="100" value="${conf.empty_chance ?? 0}"/></label>
        `;
        const [chk, cnt, emp] = cfgDiv.querySelectorAll("input");
        chk.onchange = () => updateCatConf(cat.id, { enabled: chk.checked });
        cnt.onchange = () => updateCatConf(cat.id, { count: Math.max(0, parseInt(cnt.value || "0")) });
        emp.onchange = () => updateCatConf(cat.id, { empty_chance: Math.min(100, Math.max(0, parseInt(emp.value || "0"))) });
        pill.appendChild(cfgDiv);
      }
      catsEl.appendChild(pill);
    }
  }

  function updateCatConf(catId, patch) {
    const st = getState(node);
    const conf = { ...(st.category_random || {}) };
    conf[catId] = { enabled: false, count: 1, empty_chance: 0, ...conf[catId], ...patch };
    setState(node, { category_random: conf });
    renderCats();
  }

  function renderChips() {
    const st = getState(node);
    chipzoneEl.innerHTML = "";
    const q = ui.filter.trim().toLowerCase();
    const cats = (LIB_CACHE?.categories || [])
      .filter((c) => !ui.activeCat || c.id === ui.activeCat);

    let shown = 0;
    for (const cat of cats) {
      const clr = cat.color || "#54a0ff";
      for (const sub of cat.subcategories || []) {
        const hits = (sub.tags || []).filter(
          (t) => !q ||
            t.en.toLowerCase().includes(q) ||
            (t.zh || "").toLowerCase().includes(q) ||
            (t.aliases || []).some((a) => a.toLowerCase().includes(q))
        );
        if (!hits.length) continue;
        shown += hits.length;

        const title = document.createElement("div");
        title.className = "tl-sub-title";
        title.textContent = `${cat.icon || ""}${cat.name} / ${sub.name}`;
        chipzoneEl.appendChild(title);

        const wrap = document.createElement("div");
        wrap.className = "tl-chips";
        const selSet = new Set(st.selected);
        for (const t of hits) {
          const chip = document.createElement("span");
          chip.className = "tl-chip" + (selSet.has(t.id) ? " sel" : "");
          chip.style.color = selSet.has(t.id) ? clr : "#dfe3ea";
          chip.innerHTML = `${t.en}<span class="zh">${t.zh || ""}</span>`;
          chip.title = `${t.en} · ${t.zh || ""}${t.aliases?.length ? " / " + t.aliases.join(", ") : ""}`;
          chip.onclick = () => toggleTag(t.id);
          wrap.appendChild(chip);
        }
        chipzoneEl.appendChild(wrap);
      }
    }
    if (!shown && q) {
      chipzoneEl.innerHTML = `<div class="tl-empty">没搜到 "${ui.filter}" — 可以去管理页添加这个标签</div>`;
    }
  }

  function toggleTag(tagId) {
    const st = getState(node);
    const sel = new Set(st.selected);
    sel.has(tagId) ? sel.delete(tagId) : sel.add(tagId);
    setState(node, { selected: [...sel] });
    renderCats();
    renderChips();
    renderSelected();
  }

  /* ---- 已选区 (拖拽排序 + 钉选 + 删除) ---- */
  function renderSelected() {
    const st = getState(node);
    selectedEl.innerHTML = "";
    $(".tl-n").textContent = st.selected.length;
    const byId = new Map();
    for (const cat of LIB_CACHE?.categories || [])
      for (const t of allTagsOf(cat)) byId.set(t.id, { ...t, _color: cat.color });

    st.selected.forEach((id, idx) => {
      const info = byId.get(id);
      const el = document.createElement("span");
      el.className = "tl-sel-tag";
      el.draggable = true;
      el.style.color = info?._color || "#ccc";
      const pinned = st.pinned.includes(id);
      el.innerHTML = `<span class="tl-pin${pinned ? " pinned" : ""}" title="随机时必含">📌</span>${info?.en || id}<span class="x">✕</span>`;
      el.querySelector(".tl-pin").onclick = () => {
        const pins = new Set(getState(node).pinned);
        pins.has(id) ? pins.delete(id) : pins.add(id);
        setState(node, { pinned: [...pins] });
        renderSelected();
      };
      el.querySelector(".x").onclick = () => toggleTag(id);
      el.ondragstart = (e) => { e.dataTransfer.setData("text/plain", String(idx)); el.classList.add("dragging"); };
      el.ondragend = () => el.classList.remove("dragging");
      el.ondragover = (e) => e.preventDefault();
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

    // 预览
    const texts = st.selected.map((id) => byId.get(id)?.en || id);
    previewEl.textContent = texts.length ? "→ " + texts.join(", ") : "";
  }

  function renderAll() {
    renderCats();
    renderChips();
    renderSelected();
  }

  /* ---- events ---- */
  container.querySelector('[data-act="manager"]').onclick = () => openManagerDialog(node);
  container.querySelector('[data-act="roll"]').onclick = () => rollSeed(node);
  searchEl.oninput = () => { ui.filter = searchEl.value; renderChips(); };
  modeEl.onchange = () => setMode(modeEl.value);
  container.querySelector(".tl-clear").onclick = () => {
    setState(node, { selected: [], pinned: [] });
    renderAll();
  };

  // 初始
  const modeW = node.widgets?.find((x) => x.name === "mode");
  if (modeW) modeEl.value = modeW.value;
  fetchLibrary()
    .then(() => {
      syncFromWidgets();
      chipzoneEl.style.display = modeEl.value === "random_mix" ? "none" : "";
    })
    .catch((err) => {
      container.innerHTML = `<div class="tl-empty">标签库加载失败: ${err}</div>`;
    });

  return {
    refresh: async () => {
      invalidateLibraryCache();
      await fetchLibrary();
      renderAll();
    },
  };
}

function rollSeed(node) {
  const seedW = node.widgets?.find((x) => x.name === "seed");
  if (seedW) {
    seedW.value = Math.floor(Math.random() * 4294967295);
    seedW.callback?.(seedW.value);
    node.setDirtyCanvas?.(true);
  }
}

/* ------------------------------------------------------ manager dialog */

function openManagerDialog(_node) {
  let dlg = document.getElementById("taglib-manager-dialog");
  if (dlg) { dlg.close(); dlg.remove(); }
  dlg = document.createElement("dialog");
  dlg.id = "taglib-manager-dialog";
  dlg.style.cssText = [
    "width:min(96vw,1400px)", "height:min(94vh,980px)",
    "border:none", "border-radius:14px", "padding:0",
    "background:#17191f", "color:#dfe3ea",
    "max-width:none", "max-height:none",
  ].join(";");
  dlg.innerHTML = `
    <iframe src="${MANAGER_URL}" style="width:100%;height:100%;border:0;border-radius:14px;display:block"></iframe>
  `;
  document.body.appendChild(dlg);
  dlg.showModal();
  // iframe 内管理页请求重载库后, 关窗刷新缓存
  dlg.addEventListener("close", () => {
    invalidateLibraryCache();
    window.dispatchEvent(new CustomEvent("taglib-updated"));
  });
}

/* -------------------------------------------------------------- register */

app.registerExtension({
  name: "zhixin.tagLibrary",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const node = this;

      // selection_state 对用户隐藏 (保留序列化)
      setTimeout(() => {
        const sw = node.widgets?.find((w) => w.name === "selection_state");
        if (sw) {
          sw.computeSize = () => [0, -4];
          sw.domManager?.hidden ?? true;
          if (sw.inputEl) sw.inputEl.style.display = "none";
          try { sw.hidden = true; } catch {}
        }
        const cw = node.widgets?.find((w) => w.name === "category_weights");
        if (cw) {
          cw.computeSize = () => [0, -4];
          if (cw.inputEl) cw.inputEl.style.display = "none";
          try { cw.hidden = true; } catch {}
        }
      }, 0);

      const holder = document.createElement("div");
      holder.className = "taglib-widget-holder";
      const panelApi = buildPanelWidget(node, holder);
      node.addDOMWidget("taglib_panel", "panel", holder);
      node._taglibPanelApi = panelApi;
      node.setSize([Math.max(node.size[0], 360), node.size[1] + 330]);

      window.addEventListener("taglib-updated", () => panelApi.refresh());
      return r;
    };
  },

  async setup() {
    // 顶栏命令: 标签库 -> 打开管理页 (也出现在命令面板)
    try {
      app.extensionManager?.registerCommand?.({
        id: "zhixin.openTagLibraryManager",
        label: "🏷 打开标签库管理页",
        function: () => openManagerDialog(null),
      });
    } catch {}
  },
});
