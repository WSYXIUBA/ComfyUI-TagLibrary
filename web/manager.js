/* 标签库管理页逻辑 —— 全部改动先落在内存 working 树, 点「💾 保存更改」才 POST。 */

(() => {
  "use strict";

  const API = "/taglib/api/library";
  const $ = (sel) => document.querySelector(sel);

  /* ---------------- state ---------------- */
  let lib = { version: 1, categories: [] };   // 工作树 (可自由改)
  let serverMtime = 0;                         // 乐观锁
  let dirty = false;
  let activeCatId = null;
  let activeSubId = null;
  let filterQ = "";

  const PALETTE = ["#54a0ff", "#2ecc71", "#f39c12", "#9b59b6", "#e74c3c", "#1abc9c", "#e67e22", "#3498db"];

  /* ---------------- helpers ---------------- */
  function toast(msg, isErr = false) {
    const t = document.createElement("div");
    t.id = "toast";
    if (isErr) t.classList.add("err");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  }

  function markDirty() {
    dirty = true;
    $("#dirtyMark").classList.remove("hidden");
    $("#saveMsg").textContent = "";
  }

  function clearDirty() {
    dirty = false;
    $("#dirtyMark").classList.add("hidden");
  }

  const slugify = (s) =>
    (s || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "item";

  function uidIn(taken, base) {
    let cand = base, n = 2;
    while (taken.has(cand)) cand = `${base}-${n++}`;
    taken.add(cand);
    return cand;
  }

  function catById(id) { return lib.categories.find((c) => c.id === id); }
  function subById(sid) {
    for (const c of lib.categories)
      for (const s of c.subcategories || [])
        if (s.id === sid) return s;
    return null;
  }

  function allTakenTagIds() {
    const taken = new Set();
    for (const c of lib.categories)
      for (const s of c.subcategories || [])
        for (const t of s.tags || []) if (t.id) taken.add(t.id);
    return taken;
  }

  function subTagCount(s) {
    // 骨架模式: 未懒加载的子分类用服务端计数
    return s._loaded ? (s.tags || []).length : (s._count ?? (s.tags || []).length);
  }

  function countTags(cat) {
    let n = 0;
    for (const s of cat.subcategories || []) n += subTagCount(s);
    return n;
  }

  /* ---------------- 子分类懒加载 (骨架 → 按需取正文) ---------------- */
  const subFetches = new Map();   // 防重复拉取 (sub.id -> Promise)

  function ensureSubLoaded(cat, sub) {
    if (sub._loaded) return Promise.resolve();
    if (subFetches.has(sub.id)) return subFetches.get(sub.id);
    const p = fetch(`/taglib/api/subtags?cat_id=${encodeURIComponent(cat.id)}&sub_id=${encodeURIComponent(sub.id)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          sub.tags = data.tags || [];
          // groups 仅在真有三级结构时挂载: 空数组不能挂, 否则服务端 validate 走
          // 三级汇总分支把 tags 覆盖成 [] (清空重导后保存丢词 bug 的前端一半)
          if (data.groups && data.groups.length) sub.groups = data.groups;
          else delete sub.groups;
          sub._loaded = true;
        }
      });
    subFetches.set(sub.id, p);
    return p;
  }

  async function ensureAllLoaded() {
    // 保存/导出模板前兜底: 所有非空子分类必须已加载正文
    const jobs = [];
    for (const c of lib.categories)
      for (const s of c.subcategories || [])
        if (!s._loaded && (s._count || 0) > 0) jobs.push(ensureSubLoaded(c, s));
    await Promise.all(jobs);
  }

  /* ---------------- load / save ---------------- */
  async function load() {
    // 骨架模式: 先拿分类树 (无标签正文), 子分类标签懒加载
    const r = await fetch(API + "?mode=skeleton");
    const data = await r.json();
    // 深拷贝进工作树
    lib = JSON.parse(JSON.stringify(data.library || { categories: [] }));
    for (const c of lib.categories)
      for (const s of c.subcategories || []) {
        s._count = (s.tags || []).length || s.tag_count || 0;
        s.tags = [];
        s._loaded = !s._count;   // 空子分类视为已加载
      }
    subFetches.clear();
    serverMtime = data.mtime || 0;
    activeCatId = lib.categories[0]?.id || null;
    activeSubId = lib.categories[0]?.subcategories?.[0]?.id || null;
    clearDirty();
    renderAll();
    $("#mtimeInfo").textContent = data.library?._meta?.merged_at
      ? `当前合并库: ${data.library._meta.merged_at}${data.library._meta.has_user_data ? " (含用户修改)" : " (纯默认库)"}`
      : "";
  }

  async function save() {
    try {
      await ensureAllLoaded();
      const payload = JSON.parse(JSON.stringify(lib));
      for (const c of payload.categories)
        for (const s of c.subcategories || []) {
          delete s._loaded;
          delete s._count;
        }
      delete payload._meta;
      const r = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-TagLib-Mtime": String(serverMtime) },
        body: JSON.stringify(payload),
      });
      const res = await r.json();
      if (!r.ok || !res.ok) throw new Error(res.error || `HTTP ${r.status}`);
      serverMtime = res.mtime;
      clearDirty();
      $("#saveMsg").textContent = `✓ 已保存 ${new Date().toLocaleTimeString()}`;
      toast("已保存, 所有工作流下次生成即生效 ✅");
      await load();
      keepSelection();
    } catch (err) {
      toast(`保存失败: ${err.message}`, true);
    }
  }

  function keepSelection() {
    if (!catById(activeCatId)) activeCatId = lib.categories[0]?.id || null;
    const cat = catById(activeCatId);
    if (!subById(activeSubId)) activeSubId = cat?.subcategories?.[0]?.id || null;
  }

  /* ---------------- rendering ---------------- */
  function renderAll() {
    renderCats();
    renderTabs();
    renderTable();
    renderStats();
  }

  function renderCats() {
    const ul = $("#catList");
    ul.innerHTML = "";
    lib.categories.forEach((cat, idx) => {
      const li = document.createElement("li");
      li.className = "cat-item" + (cat.id === activeCatId ? " active" : "");
      li.style.color = cat.color || "#999";
      li.draggable = true;

      const iconEl = document.createElement("span");
      iconEl.className = "ci-icon";
      iconEl.textContent = cat.icon || "🗂";
      iconEl.title = "点击更换图标 (支持任意表情)";
      iconEl.onclick = (e) => { e.stopPropagation(); openIconPop(e.clientX, e.clientY, cat); };

      const name = document.createElement("span");
      name.className = "ci-name";
      name.textContent = cat.name;
      name.style.color = cat.id === activeCatId ? "" : "var(--text)";

      const cnt = document.createElement("span");
      cnt.className = "ci-count";
      cnt.textContent = countTags(cat);

      const acts = document.createElement("span");
      acts.className = "cat-actions";
      acts.innerHTML = `<button class="icon-btn" title="重命名">✏</button><button class="icon-btn del" title="删除分类">🗑</button>`;
      acts.querySelector("button:not(.del)").onclick = (e) => { e.stopPropagation(); renameCat(cat); };
      acts.querySelector(".del").onclick = (e) => { e.stopPropagation(); removeCat(cat); };

      li.append(iconEl, name, cnt, acts);
      li.onclick = () => {
        activeCatId = cat.id;
        activeSubId = cat.subcategories?.[0]?.id || null;
        renderAll();
      };
      li.oncontextmenu = (e) => {
        e.preventDefault();
        e.stopPropagation();
        openCatMenu(e.clientX, e.clientY, cat);
      };

      // 拖拽排序
      li.ondragstart = (e) => e.dataTransfer.setData("text/plain", String(idx));
      li.ondragover = (e) => { e.preventDefault(); li.classList.add("drag-over"); };
      li.ondragleave = () => li.classList.remove("drag-over");
      li.ondrop = (e) => {
        e.preventDefault();
        li.classList.remove("drag-over");
        const from = parseInt(e.dataTransfer.getData("text/plain"));
        if (Number.isNaN(from) || from === idx) return;
        const [moved] = lib.categories.splice(from, 1);
        lib.categories.splice(idx, 0, moved);
        markDirty();
        renderAll();
      };
      ul.appendChild(li);
    });
  }

  function visibleSubs(cat) {
    // 骨架懒加载: 本地标签过滤不可靠, 搜索走服务端 /taglib/api/search
    return cat.subcategories || [];
  }

  function tagHits(tag) {
    if (!filterQ) return true;
    const q = filterQ.toLowerCase();
    return (
      (tag.en || "").toLowerCase().includes(q) ||
      (tag.zh || "").toLowerCase().includes(q) ||
      (tag.aliases || []).some((a) => a.toLowerCase().includes(q))
    );
  }

  function renderTabs() {
    const box = $("#subTabs");
    box.innerHTML = "";
    const cat = catById(activeCatId);
    if (!cat) { $("#emptyHint").classList.remove("hidden"); return; }
    (visibleSubs(cat)).forEach((sub, idx) => {
      const el = document.createElement("span");
      el.className = "tab" + (sub.id === activeSubId ? " active" : "");
      el.draggable = true;
      el.title = "点击切换 / 右键: 重命名·删除 / 拖拽排序";
      const hits = filterQ ? "…" : subTagCount(sub);
      el.innerHTML = `${escapeHtml(sub.name)} <span class="t-count">${hits}</span>`;
      el.onclick = () => { activeSubId = sub.id; renderTabs(); renderTable(); };
      el.oncontextmenu = (e) => {
        e.preventDefault();
        e.stopPropagation();
        openSubTabMenu(e.clientX, e.clientY, cat, sub);
      };
      // 拖拽排序 (同级子分类)
      el.ondragstart = (e) => e.dataTransfer.setData("text/plain", String(idx));
      el.ondragover = (e) => { e.preventDefault(); el.classList.add("drag-over"); };
      el.ondragleave = () => el.classList.remove("drag-over");
      el.ondrop = (e) => {
        e.preventDefault();
        el.classList.remove("drag-over");
        const from = parseInt(e.dataTransfer.getData("text/plain"));
        if (Number.isNaN(from) || from === idx) return;
        const subs = cat.subcategories;
        const [moved] = subs.splice(from, 1);
        subs.splice(idx, 0, moved);
        markDirty(); renderTabs();
      };
      box.appendChild(el);
    });
  }

  /* ---------- 子分类页签右键菜单: 重命名 / 删除 ---------- */
  let subMenuEl = null;
  function closeSubTabMenu() {
    if (subMenuEl) { subMenuEl.remove(); subMenuEl = null; }
  }
  function openSubTabMenu(x, y, cat, sub) {
    closeSubTabMenu();
    subMenuEl = document.createElement("div");
    subMenuEl.className = "mtag-menu sub-menu";
    subMenuEl.innerHTML = `
      <div class="sm-title">${escapeHtml(cat.name)} / ${escapeHtml(sub.name)}</div>
      <button data-act="rename" class="sm-btn">✏ 重命名</button>
      <button data-act="del" class="sm-btn danger">🗑 删除子分类</button>
      <button data-act="conf" class="sm-btn">🧷 反冲突设置…</button>
      <div class="sm-hint">${(sub.tags || []).length} 个标签将随子分类一起删除</div>`;
    document.body.appendChild(subMenuEl);
    const r = subMenuEl.getBoundingClientRect();
    subMenuEl.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    subMenuEl.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
    subMenuEl.addEventListener("click", (e) => e.stopPropagation());
    subMenuEl.querySelector('[data-act="rename"]').onclick = () => {
      closeSubTabMenu();
      renameSub(cat, sub);
    };
    subMenuEl.querySelector('[data-act="del"]').onclick = () => {
      closeSubTabMenu();
      removeSub(cat, sub);
    };
    subMenuEl.querySelector('[data-act="conf"]').onclick = () => {
      closeSubTabMenu();
      openConflictDialog({ kind: "sub", value: `${cat.name}/${sub.name}`,
                           label: `${cat.name}/${sub.name}` });
    };
    setTimeout(() => document.addEventListener("click", closeSubTabMenu, { once: true }), 0);
  }

  /* ---------- 一级分类右键菜单: 重命名 / 删除 / 反冲突 ---------- */
  let catMenuEl = null;
  function closeCatMenu() {
    if (catMenuEl) { catMenuEl.remove(); catMenuEl = null; }
  }
  function openCatMenu(x, y, cat) {
    closeCatMenu();
    catMenuEl = document.createElement("div");
    catMenuEl.className = "mtag-menu sub-menu";
    catMenuEl.innerHTML = `
      <div class="sm-title">${escapeHtml(cat.name)}</div>
      <button data-act="rename" class="sm-btn">✏ 重命名</button>
      <button data-act="icon" class="sm-btn">😀 更改图标…</button>
      <button data-act="del" class="sm-btn danger">🗑 删除分类</button>
      <button data-act="conf" class="sm-btn">🧷 反冲突设置…</button>
      <div class="sm-hint">${countTags(cat)} 个标签将随分类一起删除</div>`;
    document.body.appendChild(catMenuEl);
    const r = catMenuEl.getBoundingClientRect();
    catMenuEl.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    catMenuEl.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
    catMenuEl.addEventListener("click", (e) => e.stopPropagation());
    catMenuEl.querySelector('[data-act="rename"]').onclick = () => { closeCatMenu(); renameCat(cat); };
    catMenuEl.querySelector('[data-act="icon"]').onclick = () => { closeCatMenu(); openIconPop(x, y, cat); };
    catMenuEl.querySelector('[data-act="del"]').onclick = () => { closeCatMenu(); removeCat(cat); };
    catMenuEl.querySelector('[data-act="conf"]').onclick = () => {
      closeCatMenu();
      openConflictDialog({ kind: "cat", value: cat.name, label: cat.name });
    };
    setTimeout(() => document.addEventListener("click", closeCatMenu, { once: true }), 0);
  }

  function renameSub(cat, sub) {
    const name = prompt("子分类名称:", sub.name);
    if (name === null) return;
    if (!name.trim()) return toast("名称不能为空", true);
    sub.name = name.trim();
    markDirty(); renderTabs(); renderTable();
  }

  function removeSub(cat, sub) {
    const n = (sub.tags || []).length;
    if (!confirm(`确定删除子分类「${sub.name}」?\n其下 ${n} 个标签将一并删除 (保存后落盘)。`)) return;
    cat.subcategories = (cat.subcategories || []).filter((s) => s !== sub);
    if (activeSubId === sub.id) activeSubId = cat.subcategories?.[0]?.id || null;
    keepSelection();
    markDirty(); renderAll();
  }

  /* ---------- 标签 chip 流 (一行多枚, 双显, 绿框/红框, 右键编辑菜单) ---------- */
  function renderTable() {
    const flow = $("#tagFlow");
    flow.innerHTML = "";
    const cat = catById(activeCatId);
    const sub = subById(activeSubId);
    if (!sub) { $("#emptyHint").classList.remove("hidden"); return; }
    if (!sub._loaded) {
      flow.innerHTML = `<div class="empty">子分类加载中…</div>`;
      ensureSubLoaded(cat, sub).then(() => renderTable());
      return;
    }
    $("#emptyHint").classList.add("hidden");

    const tags = (sub.tags || []).filter(tagHits);
    if (!tags.length && filterQ) {
      $("#emptyHint").textContent = `当前子分类没有匹配 \"${filterQ}\" 的标签`;
      $("#emptyHint").classList.remove("hidden");
      return;
    }
    $("#emptyHint").textContent =
      '没有标签。点右上「➕ 添加标签」或「📋 批量粘贴」。格式每行一条: english | 中文 | 权重';

    for (const tag of tags) {
      const el = document.createElement("span");
      el.className = "mtag" + (tag.nsfw ? " nsfw" : "") + (tag.enabled === false ? " off" : "");
      el.title = "右键: 编辑标签\\n左键拖拽排序不可用 (chip 模式), 编辑请右键";
      const zh = (tag.zh || "").trim();
      const gsym = tag.gender === "female" ? '<span class="mt-gsym g-f">♀</span>'
                 : tag.gender === "male" ? '<span class="mt-gsym g-m">♂</span>' : "";
      el.innerHTML =
        gsym +
        `<span class="mt-en">${escapeHtml(tag.en)}</span>` +
        (zh ? `<span class="mt-zh">${escapeHtml(zh)}</span>` : "") +
        (tag.weight && tag.weight !== 1.0 ? `<span class="mt-w">${tag.weight}</span>` : "") +
        (tag.enabled === false ? `<span class="mt-off">停</span>` : "");
      el.oncontextmenu = (e) => {
        e.preventDefault();
        e.stopPropagation();
        openTagMenu(e.clientX, e.clientY, tag, sub);
      };
      flow.appendChild(el);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ---------- 右键编辑菜单 ---------- */
  let menuEl = null;
  function closeTagMenu() {
    if (menuEl) { menuEl.remove(); menuEl = null; }
  }
  function openTagMenu(x, y, tag, sub) {
    closeTagMenu();
    menuEl = document.createElement("div");
    menuEl.className = "mtag-menu";
    menuEl.innerHTML = `
      <label>英文 <input data-f="en" value="${escapeHtml(tag.en)}"/></label>
      <label>中文 <input data-f="zh" value="${escapeHtml(tag.zh || "")}" placeholder="中文翻译"/></label>
      <label>默认权重 <input data-f="weight" type="number" step="0.05" min="0.1" max="3" value="${tag.weight ?? 1.0}"/></label>
      <label>别名 <input data-f="aliases" value="${escapeHtml((tag.aliases || []).join(", "))}" placeholder="同义词, 逗号隔开"/></label>
      <div class="mt-row">
        <label class="mt-chk"><input type="checkbox" data-f="nsfw" ${tag.nsfw ? "checked" : ""}/> 🔞 NSFW</label>
        <label class="mt-chk"><input type="checkbox" data-f="enabled" ${tag.enabled !== false ? "checked" : ""}/> 启用</label>
        <label class="mt-chk">性别
          <select data-f="gender">
            <option value="" ${!tag.gender ? "selected" : ""}>双性</option>
            <option value="female" ${tag.gender === "female" ? "selected" : ""}>♀ 女性</option>
            <option value="male" ${tag.gender === "male" ? "selected" : ""}>♂ 男性</option>
          </select>
        </label>
      </div>
      <button data-act="conf" class="mt-conf-btn">🧷 反冲突设置…</button>
      <div class="mt-actions">
        <button data-act="del" class="danger">🗑 删除</button>
        <button data-act="ok" class="primary">保存</button>
      </div>`;
    document.body.appendChild(menuEl);
    // 视口内定位
    const r = menuEl.getBoundingClientRect();
    menuEl.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    menuEl.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";

    menuEl.addEventListener("click", (e) => e.stopPropagation());
    menuEl.querySelector('[data-act="conf"]').onclick = () => {
      const en = tag.en;
      closeTagMenu();
      openConflictDialog({ kind: "tag", value: en, label: en });
    };
    menuEl.querySelector('[data-act="ok"]').onclick = () => {
      const g = (f) => menuEl.querySelector(`[data-f="${f}"]`);
      const en = g("en").value.trim();
      if (en) tag.en = en; else g("en").value = tag.en;
      tag.zh = g("zh").value.trim();
      const w = parseFloat(g("weight").value);
      if (!Number.isNaN(w) && w > 0 && w <= 3) tag.weight = w; else delete tag.weight;
      tag.aliases = g("aliases").value.split(",").map((s) => s.trim()).filter(Boolean);
      if (g("nsfw").checked) tag.nsfw = true; else delete tag.nsfw;
      const gv = g("gender") ? g("gender").value : "";
      if (gv === "female" || gv === "male") tag.gender = gv; else delete tag.gender;
      tag.enabled = g("enabled").checked;
      markDirty(); renderTable(); closeTagMenu();
    };
    menuEl.querySelector('[data-act="del"]').onclick = () => {
      sub.tags = sub.tags.filter((t) => t !== tag);
      markDirty(); renderTable(); closeTagMenu();
    };
    setTimeout(() => document.addEventListener("click", closeTagMenu, { once: true }), 0);
  }

  function touched() { markDirty(); }

  function renderStats() {
    const box = $("#statsBox");
    box.innerHTML = "";
    let total = 0;
    for (const cat of lib.categories) {
      const n = countTags(cat);
      total += n;
      const row = document.createElement("div");
      row.className = "stat-row";
      row.style.color = cat.color || "#888";
      row.innerHTML = `<span style="color:var(--text)">${cat.icon || ""} ${cat.name}</span><b>${n}</b>`;
      box.appendChild(row);
    }
    const tot = document.createElement("div");
    tot.className = "stat-total";
    tot.textContent = `合计 ${total} 个标签`;
    box.appendChild(tot);
  }

  /* ---------------- actions ---------------- */
  function renameCat(cat) {
    const name = prompt("分类名称:", cat.name);
    if (name === null) return;
    if (!name.trim()) return toast("名称不能为空", true);
    cat.name = name.trim();
    markDirty(); renderAll();
  }

  /* ---------- 一级分类图标编辑: 输入/粘贴任意表情, 或点预设 ---------- */
  const ICON_PRESETS = [
    "🗂","💎","🧑","👗","🤸","🎬","💡","🏞️",
    "🎨","✨","🧩","😺","🌼","🍰","🎭","🌹",
    "🍜","⚽","👠","🧵","🌙","🌊","🏙️","🎢",
    "🕯️","🪄","🔮","🦋","🌸","📷","🀄","🎁",
  ];
  let iconPopEl = null;
  function closeIconPop() {
    if (iconPopEl) { iconPopEl.remove(); iconPopEl = null; }
  }
  function openIconPop(x, y, cat) {
    closeCatMenu();
    iconPopEl = document.createElement("div");
    iconPopEl.className = "mtag-menu sub-menu icon-pop";
    iconPopEl.innerHTML = `
      <div class="sm-title">图标 — ${escapeHtml(cat.name)}</div>
      <div class="icon-row">
        <input class="icon-input" maxlength="8" value="${escapeHtml(cat.icon || "")}" placeholder="输入/粘贴表情"/>
        <button class="sm-btn" data-act="ok">确定</button>
      </div>
      <div class="icon-grid">${ICON_PRESETS.map((e) => `<button class="icon-cell" data-e="${e}">${e}</button>`).join("")}</div>
      <div class="sm-hint">支持任意 Emoji, 输入/粘贴后回车; 清空后确定 = 恢复默认 🗂</div>`;
    document.body.appendChild(iconPopEl);
    const r = iconPopEl.getBoundingClientRect();
    iconPopEl.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    iconPopEl.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
    iconPopEl.addEventListener("click", (e) => e.stopPropagation());
    const input = iconPopEl.querySelector(".icon-input");
    const apply = (v) => {
      cat.icon = (v || "").trim() || "🗂";
      markDirty(); renderAll(); closeIconPop();
      toast(`图标已更新: ${cat.icon}`);
    };
    iconPopEl.querySelector('[data-act="ok"]').onclick = () => apply(input.value);
    input.onkeydown = (e) => {
      e.stopPropagation();
      if (e.key === "Enter") apply(input.value);
    };
    iconPopEl.querySelectorAll(".icon-cell").forEach((b) => {
      b.onclick = () => { input.value = b.dataset.e; apply(b.dataset.e); };
    });
    setTimeout(() => document.addEventListener("click", closeIconPop, { once: true }), 0);
  }

  function recolorChildrenIds(cat, takenTagIds) {
    // 新建分类的子分类/标签 id 自动生成
    const seenSub = new Set();
    for (const s of cat.subcategories || []) {
      if (!s.id) s.id = `${cat.id}.${uidIn(seenSub, "sub")}`;
      const seenTag = new Set();
      for (const t of s.tags || []) {
        if (!t.id) t.id = `${s.id}.${slugify(t.en)}`;
        while (takenTagIds.has(t.id)) t.id = `${t.id}-${Math.floor(Math.random() * 99)}`;
        takenTagIds.add(t.id);
      }
    }
  }

  function addCategory() {
    const name = prompt("新分类名称:", "");
    if (!name || !name.trim()) return;
    const taken = new Set(lib.categories.map((c) => c.id));
    const id = uidIn(taken, slugify(name));
    lib.categories.push({
      id,
      name: name.trim(),
      icon: "🗂",
      color: PALETTE[lib.categories.length % PALETTE.length],
      subcategories: [{ id: `${id}.misc`, name: "未分类", tags: [] }],
    });
    activeCatId = id;
    activeSubId = `${id}.misc`;
    markDirty(); renderAll();
  }

  function removeCat(cat) {
    if (!confirm(`确定删除分类「${cat.name}」及其下所有标签 (${countTags(cat)} 个)?`)) return;
    lib.categories = lib.categories.filter((c) => c !== cat);
    keepSelection();
    markDirty(); renderAll();
  }

  function addSubcategory() {
    const cat = catById(activeCatId);
    if (!cat) return toast("先选一个分类", true);
    const name = prompt(`在「${cat.name}」下新建子分类:`, "");
    if (!name || !name.trim()) return;
    const taken = new Set((cat.subcategories || []).map((s) => s.id));
    const sid = `${cat.id}.${uidIn(taken, slugify(name))}`;
    (cat.subcategories ||= []).push({ id: sid, name: name.trim(), tags: [], _loaded: true });
    activeSubId = sid;
    markDirty(); renderAll();
  }

  async function addTagRow() {
    const sub = subById(activeSubId);
    if (!sub) return toast("先选一个子分类页签", true);
    await ensureSubLoaded(catById(activeCatId), sub);
    if (!sub._loaded) sub._loaded = true;
    const en = prompt("英文文本 (出图用):", "");
    if (!en || !en.trim()) return;
    const zh = prompt("中文显示名 (可空):", "") || "";
    const taken = allTakenTagIds();
    const id = uidIn(taken, `${sub.id}.${slugify(en)}`);
    sub.tags.push({ id, en: en.trim(), zh: zh.trim(), weight: 1.0, aliases: [], enabled: true });
    markDirty(); renderTable(); renderStats();
  }

  async function openPasteDialog() {
    const cat = catById(activeCatId);
    const sub = subById(activeSubId);
    if (!cat || !sub) return toast("先选好分类和子分类", true);
    if (!sub._loaded) await ensureSubLoaded(cat, sub);
    if (!sub._loaded) sub._loaded = true;
    $("#pasteTarget").textContent = `${cat.name} / ${sub.name}`;
    $("#pasteArea").value = "";
    $("#pasteDialog").classList.remove("hidden");
    $("#pasteArea").focus();
  }

  function doPasteImport() {
    const sub = subById(activeSubId);
    const lines = $("#pasteArea").value.split("\n").map((l) => l.trim()).filter(Boolean);
    let added = 0, skipped = 0;
    const taken = allTakenTagIds();
    for (const line of lines) {
      const parts = line.split("|").map((p) => p.trim());
      const en = parts[0];
      if (!en) { skipped++; continue; }
      const zh = parts[1] || "";
      const weight = Math.min(3, Math.max(0.05, parseFloat(parts[2]) || 1.0));
      const flagCol = (parts[3] || "").toLowerCase();
      const nsfwFlag = flagCol.includes("nsfw") || undefined;
      const gFlag = flagCol.includes("♀") || flagCol.includes("female") ? "female"
        : flagCol.includes("♂") || flagCol.includes("male") ? "male" : "";
      const tag = { id: uidIn(taken, `${sub.id}.${slugify(en)}`), en, zh, weight, aliases: [], enabled: true };
      if (nsfwFlag) tag.nsfw = true;
      if (gFlag) tag.gender = gFlag;
      sub.tags.push(tag);
      added++;
    }
    $("#pasteDialog").classList.add("hidden");
    markDirty(); renderTable(); renderStats();
    toast(`批量导入 ${added} 条${skipped ? `, 跳过 ${skipped} 条空行` : ""}`);
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ---------- 📤 导出 .json / 📥 导入 .json ----------
     1.12.0: 原文件直接进出 —— 导出的是库 .json 本身 (带 `_说明`), 不再生成 .md 模板。
     导入只覆盖「我的」层, 出厂库与扩展包不动。 */

  function exportLibraryJson(scope) {
    const a = document.createElement("a");
    a.href = `/taglib/api/library/export?scope=${scope === "user" ? "user" : "merged"}`;
    a.download = scope === "user" ? "tag_library_user.json" : "tag_library_full.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(scope === "user" ? "「我的」层已导出 (.json)" : "整库已导出 (.json, 含 _说明)");
  }

  async function importLibraryJson(file) {
    let obj;
    try {
      obj = JSON.parse(await file.text());
    } catch (err) {
      toast(`不是合法 .json: ${err.message}`, true);
      return;
    }
    const data = obj && obj.library && Array.isArray(obj.library.categories) ? obj.library : obj;
    if (!data || !Array.isArray(data.categories)) {
      toast("文件里没有 categories 数组, 不是库文件", true);
      return;
    }
    const nTags = data.categories.reduce(
      (n, c) => n + (c.subcategories || []).reduce((m, s) => m + (s.tags || []).length, 0), 0);
    if (!confirm(`导入「${file.name}」

${data.categories.length} 个分类 / ${nTags} 个标签

`
                 + "只会覆盖「我的」层, 出厂库与扩展包不动。确定导入?")) return;
    if (dirty && !confirm("有未保存修改, 导入会整体覆盖。继续?")) return;
    try {
      const res = await fetch("/taglib/api/library/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ library: data }),
      });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已导入 ${data.categories.length} 个分类 / ${nTags} 个标签`);
      await load();
    } catch (err) {
      toast(`导入失败: ${err.message}`, true);
    }
  }

  /* ---------------- 🧷 反冲突机制 (conflicts.json) ---------------- */

  const refKey = (ref) => `${ref.kind}:${String(ref.value).toLowerCase()}`;

  let cfSubject = null;     // {kind, value, label}
  let cfRules = [];         // 工作副本
  let cfInvalid = [];       // 失效清单
  let cfRelations = [];     // 当前对象的已有关系 [{key, label, invalid, via}]
  let cfChecked = new Set();
  let cfOpen = new Set();   // 勾选树展开状态
  let cfRefByKey = new Map();

  const cfInitialKeys = () => new Set(cfRelations.map((r) => r.key));

  async function openConflictDialog(subject) {
    cfSubject = subject;
    cfOpen = new Set();
    cfRefByKey = new Map();
    let st;
    try {
      st = await fetch("/taglib/api/conflicts").then((r) => r.json());
    } catch (err) {
      return toast(`反冲突规则加载失败: ${err.message}`, true);
    }
    cfRules = JSON.parse(JSON.stringify(st.rules || []));
    cfInvalid = st.invalid || [];
    cfRelations = computeRelations(subject, cfRules, cfInvalid);
    cfChecked = cfInitialKeys();
    $("#cfSubject").textContent = subject.label || subject.value;
    renderCfRelations();
    renderCfTree();
    $("#conflictDialog").classList.remove("hidden");
  }

  function relLabel(key) {
    const i = key.indexOf(":");
    return key.slice(i + 1);
  }

  function computeRelations(subject, rules, invalid) {
    const sKey = refKey(subject);
    const sVal = String(subject.value).toLowerCase();
    const out = new Map();
    const invalidVals = new Set((invalid || []).map((x) => String(x.value)));
    rules.forEach((r, idx) => {
      const L = r.left;
      if (L.kind === "tags") {
        // 组规则: 当前标签是组成员 → 与 right 各项互斥
        if (subject.kind === "tag" &&
            L.value.some((v) => String(v).toLowerCase() === sVal)) {
          for (const ref of r.right) {
            const k = refKey(ref);
            if (!out.has(k)) out.set(k, { key: k, ref, invalid: invalidVals.has(String(ref.value)),
                                          via: { idx, type: "group" } });
          }
        }
        return;
      }
      if (refKey(L) === sKey) {
        for (const ref of r.right) {
          const k = refKey(ref);
          if (k !== sKey && !out.has(k))
            out.set(k, { key: k, ref, invalid: invalidVals.has(String(ref.value)),
                         via: { idx, type: "out" } });
        }
      }
      if ((r.right || []).some((ref) => refKey(ref) === sKey)) {
        const k = refKey(L);
        if (k !== sKey && !out.has(k))
          out.set(k, { key: k, ref: L, invalid: invalidVals.has(String(L.value)),
                       via: { idx, type: "in" } });
      }
    });
    return [...out.values()];
  }

  function removeRelation(rel) {
    const r = cfRules[rel.via.idx];
    if (!r) return;
    const sVal = String(cfSubject.value).toLowerCase();
    if (rel.via.type === "out") {
      r.right = (r.right || []).filter((x) => refKey(x) !== rel.key);
      if (!r.right.length) cfRules.splice(rel.via.idx, 1);
    } else if (rel.via.type === "in") {
      r.right = (r.right || []).filter((x) => refKey(x) !== refKey(cfSubject));
      if (!r.right.length) cfRules.splice(rel.via.idx, 1);
    } else { // group: 把当前标签移出组
      r.left.value = (r.left.value || []).filter((v) => String(v).toLowerCase() !== sVal);
      if (r.left.value.length < 2) cfRules.splice(rel.via.idx, 1);
    }
    cfRelations = computeRelations(cfSubject, cfRules, cfInvalid);
    cfChecked = cfInitialKeys();
    renderCfRelations();
    renderCfTree();
  }

  function renderCfRelations() {
    const box = $("#cfRelations");
    box.innerHTML = "";
    if (!cfRelations.length) {
      box.innerHTML = `<div class="muted" style="padding:6px 2px">暂无 — 在下方勾选建立</div>`;
      return;
    }
    for (const rel of cfRelations) {
      const chip = document.createElement("span");
      chip.className = "cf-rel" + (rel.invalid ? " bad" : "");
      chip.title = rel.invalid ? "⚠ 该目标在当前标签库中不存在" : "";
      chip.innerHTML =
        `${escapeHtml(relLabel(rel.key))}${rel.invalid ? " ⚠" : ""}` +
        `<span class="cf-x" title="删除该关系">✕</span>`;
      chip.querySelector(".cf-x").onclick = () => removeRelation(rel);
      box.appendChild(chip);
    }
  }

  function cfRowEl(key, ref, label, depth, chevron, onToggle) {
    const row = document.createElement("div");
    row.className = "cf-row";
    row.style.paddingLeft = 6 + depth * 20 + "px";
    const checked = cfChecked.has(key);
    row.innerHTML = `
      ${chevron !== undefined ? `<span class="cf-chev">${chevron ? "▾" : "▸"}</span>` : `<span class="cf-chev">·</span>`}
      <label class="cf-lab"><input type="checkbox" ${checked ? "checked" : ""}/><span>${escapeHtml(label)}</span></label>`;
    row.querySelector("input").onchange = (e) => {
      e.target.checked ? cfChecked.add(key) : cfChecked.delete(key);
    };
    if (chevron !== undefined) {
      row.querySelector(".cf-chev").style.cursor = "pointer";
      row.querySelector(".cf-chev").onclick = (e) => { e.stopPropagation(); onToggle(); };
      row.querySelector(".cf-lab span").style.cursor = "pointer";
      row.querySelector(".cf-lab span").onclick = () => onToggle();
    }
    if (ref) cfRefByKey.set(key, ref);
    return row;
  }

  function renderCfTree() {
    const tree = $("#cfTree");
    tree.innerHTML = "";
    for (const cat of lib.categories || []) {
      const cKey = `cat:${cat.name.toLowerCase()}`;
      const cRef = { kind: "cat", value: cat.name };
      if (cfSubject.kind === "cat" && cfSubject.value === cat.name) {
        continue;  // 不和自己建立
      }
      const cOpen = cfOpen.has(cKey);
      tree.appendChild(cfRowEl(cKey, cRef, `${cat.icon || ""} ${cat.name} (${countTags(cat)})`,
                               0, cOpen, () => {
        cOpen ? cfOpen.delete(cKey) : cfOpen.add(cKey);
        renderCfTree();
      }));
      if (!cOpen) continue;
      for (const sub of cat.subcategories || []) {
        const sKey = `sub:${cat.name}/${sub.name}`.toLowerCase();
        if (cfSubject.kind === "sub" &&
            String(cfSubject.value).toLowerCase() === sKey.slice(4)) {
          continue;
        }
        const sOpen = cfOpen.has(sKey);
        tree.appendChild(cfRowEl(sKey, { kind: "sub", value: `${cat.name}/${sub.name}` },
                                 `${sub.name} (${(sub.tags || []).length})`, 1, sOpen, () => {
          sOpen ? cfOpen.delete(sKey) : cfOpen.add(sKey);
          renderCfTree();
        }));
        if (!sOpen) continue;
        const flow = document.createElement("div");
        flow.className = "cf-tags-flow";
        flow.style.marginLeft = 46 + "px";
        for (const t of sub.tags || []) {
          const tKey = `tag:${String(t.en).toLowerCase()}`;
          if (cfSubject.kind === "tag" &&
              String(cfSubject.value).toLowerCase() === tKey.slice(4)) {
            continue;
          }
          const chip = document.createElement("span");
          chip.className = "cf-tag" + (t.nsfw ? " nsfw" : "") + (cfChecked.has(tKey) ? " checked" : "");
          chip.innerHTML = `<input type="checkbox" ${cfChecked.has(tKey) ? "checked" : ""}/>${escapeHtml(t.en)}`;
          chip.querySelector("input").onchange = (e) => {
            e.target.checked ? cfChecked.add(tKey) : cfChecked.delete(tKey);
            chip.classList.toggle("checked", e.target.checked);
          };
          cfRefByKey.set(tKey, { kind: "tag", value: t.en });
          flow.appendChild(chip);
        }
        tree.appendChild(flow);
      }
    }
  }

  async function saveConflictDialog() {
    const before = cfInitialKeys();
    const toRemove = [...before].filter((k) => !cfChecked.has(k));
    const toAdd = [...cfChecked].filter((k) => !before.has(k));
    // 删除: 走关系上的移除逻辑
    for (const k of toRemove) {
      const rel = cfRelations.find((x) => x.key === k);
      if (rel) removeRelation(rel);
    }
    // 新增: 统一挂到 left=subject 的一条规则
    const adds = toAdd.map((k) => cfRefByKey.get(k)).filter(Boolean);
    if (adds.length) {
      const sKey = refKey(cfSubject);
      let rule = cfRules.find((r) => r.left.kind !== "tags" && refKey(r.left) === sKey);
      if (!rule) {
        rule = { id: `cf.${Date.now().toString(36)}.${Math.floor(Math.random() * 999)}`,
                 left: { kind: cfSubject.kind, value: cfSubject.value }, right: [] };
        cfRules.push(rule);
      }
      for (const ref of adds) {
        if (!rule.right.some((x) => refKey(x) === refKey(ref))) rule.right.push(ref);
      }
    }
    try {
      const res = await fetch("/taglib/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules: cfRules }),
      });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      const badN = (out.invalid || []).length;
      toast(`✅ 反冲突规则已保存 (${out.count} 条${badN ? `, ${badN} 条失效引用` : ""})`);
      $("#conflictDialog").classList.add("hidden");
    } catch (err) {
      toast(`保存失败: ${err.message}`, true);
    }
  }

  async function exportConflicts() {
    const st = await fetch("/taglib/api/conflicts").then((r) => r.json());
    downloadText(JSON.stringify({ _说明: st.doc, version: 1, rules: st.rules }, null, 1),
                 "conflicts.json");
  }

  /* 反冲突文件导入: 预览 -> 替换/合并 -> 落盘 */
  let cfiPending = null;
  async function openConflictsImport(rules) {
    const res = await fetch("/taglib/api/conflicts/preview-import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules }),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) { toast(`反冲突文件解析失败: ${out.error || ""}`, true); return; }
    cfiPending = rules;
    $("#cfiTotal").textContent = out.total;
    $("#cfiValid").textContent = out.valid;
    $("#cfiInvalid").textContent = (out.invalid || []).length;
    const list = $("#cfiInvalidList");
    if ((out.invalid || []).length) {
      list.classList.remove("hidden");
      list.innerHTML = out.invalid
        .map((x) => `<div>⚠ <b>${escapeHtml(String(x.id || ""))}</b> — ${escapeHtml(x.reason || x.value || "")}</div>`)
        .join("");
    } else {
      list.classList.add("hidden");
      list.innerHTML = "";
    }
    $("#conflictImportDialog").classList.remove("hidden");
  }

  async function confirmConflictsImport() {
    if (!cfiPending) return;
    const mode = document.querySelector('input[name="cfiMode"]:checked')?.value || "replace";
    $("#cfiOk").disabled = true;
    try {
      const res = await fetch("/taglib/api/conflicts/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules: cfiPending, mode }),
      });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      const badN = (out.invalid || []).length;
      toast(`✅ 反冲突规则已${mode === "merge" ? "合并" : "替换"} (${out.count} 条${badN ? `, ${badN} 条失效` : ""})`);
      $("#conflictImportDialog").classList.add("hidden");
      cfiPending = null;
    } catch (err) {
      toast(`导入失败: ${err.message}`, true);
    } finally {
      $("#cfiOk").disabled = false;
    }
  }

  $("#cfCancel").onclick = () => $("#conflictDialog").classList.add("hidden");
  $("#cfSave").onclick = saveConflictDialog;
  $("#cfiOk").onclick = confirmConflictsImport;
  $("#cfiCancel").onclick = () => { $("#conflictImportDialog").classList.add("hidden"); cfiPending = null; };

  /* ---------------- bind UI ---------------- */
  $("#btnAddCat").onclick = addCategory;
  $("#btnAddSub").onclick = addSubcategory;
  $("#btnAddTag").onclick = addTagRow;
  $("#btnPaste").onclick = openPasteDialog;
  $("#pasteOk").onclick = doPasteImport;
  $("#pasteCancel").onclick = () => $("#pasteDialog").classList.add("hidden");
  $("#btnImport").onclick = () => $("#importChoiceDialog").classList.remove("hidden");
  $("#importChoiceCancel").onclick = () => $("#importChoiceDialog").classList.add("hidden");
  $("#importTags").onclick = () => { $("#importChoiceDialog").classList.add("hidden"); $("#libraryFileInput").click(); };
  $("#importConflicts").onclick = () => { $("#importChoiceDialog").classList.add("hidden"); $("#conflictsFileInput").click(); };
  $("#conflictsFileInput").onchange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const obj = JSON.parse(await file.text());
      if (!Array.isArray(obj.rules)) throw new Error("不是反冲突文件 (缺少 rules 数组)");
      await openConflictsImport(obj.rules);
    } catch (err) {
      toast(`反冲突文件读取失败: ${err.message}`, true);
    }
  };
  $("#libraryFileInput").onchange = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) importLibraryJson(f);
  };
  $("#btnExportFull").onclick = () => exportLibraryJson("merged");
  $("#btnExportUser").onclick = () => exportLibraryJson("user");

  /* ---------- 备份库 / 清空标签库 ---------- */
  async function backupSave() {
    if (dirty && !confirm("有未保存修改, 备份的是已保存的库内容。先保存再备份? (确定=继续备份)")) return;
    try {
      const res = await fetch("/taglib/api/library/backup", { method: "POST" });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已存为默认库 (备份于 data/default/backups/, ${new Date(out.mtime * 1000).toLocaleString()})`);
    } catch (err) {
      toast(`备份失败: ${err.message}`, true);
    }
  }

  async function backupRestore() {
    if (dirty && !confirm("有未保存修改, 恢复会覆盖工作树。继续?")) return;
    // 备份状态提示: 有用户备份恢复用户基准, 没有恢复出厂
    let info = {};
    try { info = await (await fetch("/taglib/api/library/backup")).json(); } catch {}
    const hasUser = info.user?.exists, hasFactory = info.factory?.exists || info.legacy?.exists;
    if (!hasUser && !hasFactory) { toast("还没有备份文件 (先「💾 存为默认库」)", true); return; }
    const srcName = hasUser ? "你的默认库备份 (用户备份)" : "出厂备份 (插件自带)";
    if (!confirm(`恢复默认库 = 用 ${srcName} 整体覆盖当前标签库。确定?`)) return;
    try {
      const res = await fetch("/taglib/api/library/restore-backup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: hasUser ? "user" : "factory" }) });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已恢复默认库 (${out.source === "user" ? "用户基准" : out.source === "auto" ? "自动滚动备份" : "出厂"})`);
      await load();
    } catch (err) {
      toast(`恢复失败: ${err.message}`, true);
    }
  }

  /* ---------- 升级弹窗: 标记文件存在 + 用户备份存在 → 问一次 ---------- */
  async function checkUpgradePrompt() {
    try {
      const info = await (await fetch("/taglib/api/library/backup")).json();
      if (!info.upgrade_prompt || !info.user?.exists) return;
      if (!confirm("插件已更新。\n\n是否恢复你的默认库 (上次「存为默认库」保存的内容)?\n\n确定=恢复我的库 / 取消=使用新版官方库")) {
        await fetch("/taglib/api/library/upgrade-dismiss", { method: "POST" });
        toast("已保留新版官方库");
        await load();
        return;
      }
      await backupRestore();
    } catch {}
  }

  async function clearLibrary(withExport) {
    $("#clearDialog").classList.add("hidden");
    if (withExport) exportLibraryJson("merged");
    try {
      const r = await fetch(API, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast(withExport ? "整库已导出, 标签库已完全清空 (等待导入)" : "标签库已完全清空 (等待导入)");
      await load();
    } catch (err) {
      toast(`清空失败: ${err.message}`, true);
    }
  }

  $("#btnBackupSave").onclick = backupSave;
  $("#btnBackupRestore").onclick = backupRestore;
  $("#btnClearLib").onclick = () => $("#clearDialog").classList.remove("hidden");
  $("#clearOk").onclick = () => clearLibrary(false);
  $("#clearExport").onclick = () => clearLibrary(true);
  $("#clearCancel").onclick = () => $("#clearDialog").classList.add("hidden");
  /* ---------------- 1.8.0 批量工具 (全部客户端操作, 改工作树后统一保存) ---------------- */

  function bulkIterSubs(scopeSub) {
    // scopeSub = {cat, sub} 或 null (全库) → [{cat, sub, name}]
    const out = [];
    for (const c of lib.categories || []) {
      for (const s of c.subcategories || []) {
        if (scopeSub && (c.id !== scopeSub.cat.id || s.id !== scopeSub.sub.id)) continue;
        out.push({ c, s, path: `${c.name}/${s.name}` });
      }
    }
    return out;
  }

  function openBulkTools() {
    const old = document.getElementById("bulkDlg");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "bulkDlg";
    dlg.style.cssText = "background:#1a1d24;color:#e3e7ee;border:1px solid #333845;border-radius:12px;"
      + "padding:16px;width:min(680px,94vw);max-height:84vh;overflow:auto;";
    const curCat = (lib.categories || []).find((c) => c.id === activeCatId);
    const curSub = curCat?.subcategories?.find((s) => s.id === activeSubId);
    const subOpts = bulkIterSubs(null)
      .map((x) => `<option value="${escapeHtml(x.c.id)}||${escapeHtml(x.s.id)}">${escapeHtml(x.path)} (${(x.s.tags || []).length})</option>`)
      .join("");
    const scopeNote = curSub
      ? `当前子分类: <b>${escapeHtml(curCat.name)}/${escapeHtml(curSub.name)}</b>`
      : "当前未选中子分类, 只能用「全库」范围";
    dlg.innerHTML = `
      <div style="font-weight:600;font-size:15px;margin-bottom:10px;">🧰 批量工具 <span style="opacity:.6;font-size:11px;">改动先落工作树, 点「💾 保存更改」才生效</span></div>
      <div style="opacity:.7;font-size:12px;margin-bottom:10px;">${scopeNote}</div>

      <details open style="margin-bottom:8px;"><summary style="cursor:pointer;font-weight:600;">1️⃣ 正则重命名</summary>
        <div style="padding:8px 0;display:grid;gap:6px;font-size:12px;">
          <label>范围 <select id="bt-ren-scope"><option value="sub">当前子分类</option><option value="all">全库</option></select>
                字段 <select id="bt-ren-field"><option value="en">英文 en</option><option value="zh">中文 zh</option></select></label>
          <label>查找 (正则) <input id="bt-ren-find" style="width:100%;" placeholder="例如  \\(medium\\)  或  ^old_" /></label>
          <label>替换为 <input id="bt-ren-rep" style="width:100%;" placeholder="支持 $1 引用分组; 留空即删除匹配段" /></label>
          <button id="bt-ren-go" class="btn small primary">应用重命名</button>
          <div id="bt-ren-out" style="opacity:.85;"></div>
        </div>
      </details>

      <details style="margin-bottom:8px;"><summary style="cursor:pointer;font-weight:600;">2️⃣ 批量移动</summary>
        <div style="padding:8px 0;display:grid;gap:6px;font-size:12px;">
          <div>从当前子分类移动到目标槽位 (可用正则筛选词, 留空 = 全部):</div>
          <label>筛选 (en 正则, 可空) <input id="bt-mv-q" style="width:100%;" /></label>
          <label>目标槽位 <select id="bt-mv-to" style="max-width:100%;">${subOpts}</select></label>
          <button id="bt-mv-go" class="btn small primary">移动匹配词</button>
          <div id="bt-mv-out" style="opacity:.85;"></div>
        </div>
      </details>

      <details style="margin-bottom:8px;"><summary style="cursor:pointer;font-weight:600;">3️⃣ NSFW 批量标记</summary>
        <div style="padding:8px 0;display:grid;gap:6px;font-size:12px;">
          <label>词表 (逗号或换行分隔, 支持正则; 匹配 en):</label>
          <textarea id="bt-nsfw-words" rows="3" style="width:100%;" placeholder="nude, topless, micro bikini, .*panties.*"></textarea>
          <label>动作 <select id="bt-nsfw-mode"><option value="on">标记为 NSFW (自动带未成年锁定)</option><option value="off">取消 NSFW</option></select></label>
          <button id="bt-nsfw-go" class="btn small primary">应用标记</button>
          <div id="bt-nsfw-out" style="opacity:.85;"></div>
        </div>
      </details>

      <details><summary style="cursor:pointer;font-weight:600;">4️⃣ 跨槽位查重</summary>
        <div style="padding:8px 0;font-size:12px;">
          <button id="bt-dup-go" class="btn small">扫描全库重复词</button>
          <div id="bt-dup-out" style="margin-top:6px;"></div>
        </div>
      </details>

      <div style="position:sticky;bottom:0;background:#1a1d24;text-align:right;margin-top:10px;padding:8px 0;"><button id="bt-close" class="btn">关闭</button></div>
    `;
    document.body.appendChild(dlg);
    dlg.querySelector("#bt-close").onclick = () => dlg.close();

    // 1) 正则重命名
    dlg.querySelector("#bt-ren-go").onclick = () => {
      const scope = dlg.querySelector("#bt-ren-scope").value;
      const field = dlg.querySelector("#bt-ren-field").value;
      const find = dlg.querySelector("#bt-ren-find").value;
      const rep = dlg.querySelector("#bt-ren-rep").value;
      let re;
      try { re = new RegExp(find, "g"); } catch (e) { toast("正则不合法: " + e.message, true); return; }
      if (!find) { toast("查找内容不能为空", true); return; }
      const scopeSub = scope === "sub" && curCat && curSub ? { cat: curCat, sub: curSub } : null;
      const changes = [];
      for (const { c, s, path } of bulkIterSubs(scopeSub)) {
        for (const t of s.tags || []) {
          const v = String(t[field] || "");
          const nv = v.replace(re, rep);
          if (nv !== v && nv.trim()) {
            changes.push(`${path}: ${v} → ${nv}`);
            t[field] = nv.trim();
            if (field === "en") t.id = `${s.id}.${t.en.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").slice(0, 40) || "tag"}`;
          }
        }
      }
      dlg.querySelector("#bt-ren-out").textContent =
        changes.length ? `已改 ${changes.length} 词 (前 20):\n` + changes.slice(0, 20).join("\n") : "没有匹配";
      if (changes.length) { markDirty(); renderAll(); }
    };

    // 2) 批量移动
    dlg.querySelector("#bt-mv-go").onclick = () => {
      if (!curCat || !curSub) { toast("请先在左侧选中一个子分类作为来源", true); return; }
      const q = dlg.querySelector("#bt-mv-q").value.trim();
      let re = null;
      try { if (q) re = new RegExp(q, "i"); } catch (e) { toast("正则不合法: " + e.message, true); return; }
      const [tcid, tsid] = dlg.querySelector("#bt-mv-to").value.split("||");
      const tc = (lib.categories || []).find((c) => c.id === tcid);
      const ts = tc?.subcategories?.find((s) => s.id === tsid);
      if (!tc || !ts) { toast("目标槽位无效", true); return; }
      if (tc.id === curCat.id && ts.id === curSub.id) { toast("来源与目标相同", true); return; }
      const keep = [], moved = [];
      for (const t of curSub.tags || []) {
        if ((!re || re.test(String(t.en || ""))) && !t.pinned2) moved.push(t);
        else keep.push(t);
      }
      if (!moved.length) { dlg.querySelector("#bt-mv-out").textContent = "没有匹配的词"; return; }
      const taken = new Set((ts.tags || []).map((x) => String(x.en || "").toLowerCase()));
      const really = moved.filter((t) => !taken.has(String(t.en || "").toLowerCase()));
      ts.tags = [...(ts.tags || []), ...really];
      curSub.tags = keep;
      dlg.querySelector("#bt-mv-out").textContent =
        `移动 ${really.length} 词 → ${tc.name}/${ts.name}` + (moved.length - really.length ? ` (跳过 ${moved.length - really.length} 个已存在)` : "");
      markDirty(); renderAll();
    };

    // 3) NSFW 批量标记
    dlg.querySelector("#bt-nsfw-go").onclick = () => {
      const raw = dlg.querySelector("#bt-nsfw-words").value.trim();
      if (!raw) { toast("词表不能为空", true); return; }
      let patterns;
      try { patterns = raw.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean).map((x) => new RegExp(x, "i")); }
      catch (e) { toast("正则不合法: " + e.message, true); return; }
      const on = dlg.querySelector("#bt-nsfw-mode").value === "on";
      let n = 0;
      for (const { s } of bulkIterSubs(null)) {
        for (const t of s.tags || []) {
          const en = String(t.en || "");
          if (patterns.some((re) => re.test(en))) {
            t.nsfw = on;
            if (on) t.minor_block = true; else delete t.minor_block;
            n++;
          }
        }
      }
      dlg.querySelector("#bt-nsfw-out").textContent = on ? `已标记 ${n} 词为 NSFW` : `已取消 ${n} 词的 NSFW`;
      if (n) { markDirty(); renderAll(); }
    };

    // 4) 查重
    dlg.querySelector("#bt-dup-go").onclick = () => {
      const byEn = new Map();
      for (const { c, s, path } of bulkIterSubs(null)) {
        for (const t of s.tags || []) {
          const k = String(t.en || "").toLowerCase();
          if (!k) continue;
          if (!byEn.has(k)) byEn.set(k, []);
          byEn.get(k).push({ path, t, s });
        }
      }
      const dups = [...byEn.entries()].filter(([, lst]) => lst.length > 1);
      const out = dlg.querySelector("#bt-dup-out");
      if (!dups.length) { out.textContent = "没有跨槽位重复词 ✅"; return; }
      out.innerHTML = "";
      const head = document.createElement("div");
      head.style.cssText = "margin-bottom:4px;";
      head.textContent = `发现 ${dups.length} 个重复词:`;
      out.appendChild(head);
      for (const [en, lst] of dups) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:8px;align-items:center;padding:2px 0;flex-wrap:wrap;";
        row.innerHTML = `<b>${escapeHtml(en)}</b><span style="opacity:.6;">${lst.map((x) => escapeHtml(x.path)).join(" / ")}</span>`;
        // 保留第一份, 其余一键删
        const btn = document.createElement("button");
        btn.className = "btn small";
        btn.textContent = `删多余 ${lst.length - 1} 份`;
        btn.onclick = () => {
          for (const x of lst.slice(1)) {
            x.s.tags = (x.s.tags || []).filter((t) => t !== x.t);
          }
          btn.disabled = true;
          btn.textContent = "已删";
          markDirty(); renderAll();
        };
        row.appendChild(btn);
        out.appendChild(row);
      }
    };

    // ⚠ 必须 showModal() —— 原生 <dialog> 不调它就一直 display:none。
    //   这个弹层从 1.8.0 上线起就没显示过: 「🧰 批量工具」点了毫无反应。
    dlg.showModal();
  }
  $("#btnBulkTools").onclick = openBulkTools;

  $("#btnSave").onclick = save;
  $("#btnCancel").onclick = async () => {
    if (dirty && !confirm("放弃当前全部未保存修改?")) return;
    await load();
    toast("已还原到上次保存的状态");
  };
  let searchTimer = null;
  $("#globalSearch").oninput = (e) => {
    filterQ = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearchView, 150);   // 防抖
  };

  async function runSearchView() {
    if (!filterQ) {
      renderAll();
      return;
    }
    const cat = catById(activeCatId);
    if (cat && !visibleSubs(cat).some((s) => s.id === activeSubId))
      activeSubId = visibleSubs(cat)[0]?.id || null;
    renderTabs();
    // 服务端全文搜索 (en/zh/别名), 10k 库也 <100ms
    try {
      const r = await fetch(`/taglib/api/search?q=${encodeURIComponent(filterQ)}`);
      const data = await r.json();
      if (!data.ok) return;
      renderSearchResults(data.results || [], data.count || 0);
    } catch { /* 保持原视图 */ }
  }

  function renderSearchResults(results, count) {
    const flow = $("#tagFlow");
    flow.innerHTML = "";
    if (!results.length) {
      flow.innerHTML = `<div class="empty">没有匹配 “${escapeHtml(filterQ)}” 的标签</div>`;
      return;
    }
    const head = document.createElement("div");
    head.className = "file-group";
    head.textContent = `🔍 ${count} 条匹配 (显示前 ${results.length}) — 点击定位到子分类`;
    flow.appendChild(head);
    const grid = document.createElement("div");
    grid.className = "cf-tags-flow";
    for (const t of results) {
      const chip = document.createElement("span");
      chip.className = "cf-tag" + (t.nsfw ? " nsfw" : "");
      chip.title = `${t.cat} / ${t.sub}`;
      chip.textContent = `${t.en} ${t.zh || ""}`;
      chip.onclick = () => {
        activeCatId = t.cat_id;
        const c = catById(activeCatId);
        const sub = (c.subcategories || []).find((x) => x.id === t.sub_id);
        if (sub) { activeSubId = sub.id; ensureSubLoaded(c, sub); }
        filterQ = "";
        $("#globalSearch").value = "";
        renderAll();
      };
      grid.appendChild(chip);
    }
    flow.appendChild(grid);
  }

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    if (e.key === "Escape") $("#pasteDialog").classList.add("hidden");
  });

  load().catch((err) => toast(`加载失败: ${err.message}`, true));
  checkUpgradePrompt();
})();
