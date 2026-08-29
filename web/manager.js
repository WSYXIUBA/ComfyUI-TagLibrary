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

  function countTags(cat) {
    let n = 0;
    for (const s of cat.subcategories || []) n += (s.tags || []).length;
    return n;
  }

  /* ---------------- load / save ---------------- */
  async function load() {
    const r = await fetch(API);
    const data = await r.json();
    // 深拷贝进工作树
    lib = JSON.parse(JSON.stringify(data.library || { categories: [] }));
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
      const payload = JSON.parse(JSON.stringify(lib));
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

      const name = document.createElement("span");
      name.className = "ci-name";
      name.textContent = `${cat.icon || "🏷"} ${cat.name}`;
      name.style.color = cat.id === activeCatId ? "" : "var(--text)";

      const cnt = document.createElement("span");
      cnt.className = "ci-count";
      cnt.textContent = countTags(cat);

      const acts = document.createElement("span");
      acts.className = "cat-actions";
      acts.innerHTML = `<button class="icon-btn" title="重命名">✏</button><button class="icon-btn del" title="删除分类">🗑</button>`;
      acts.querySelector("button:not(.del)").onclick = (e) => { e.stopPropagation(); renameCat(cat); };
      acts.querySelector(".del").onclick = (e) => { e.stopPropagation(); removeCat(cat); };

      li.append(name, cnt, acts);
      li.onclick = () => {
        activeCatId = cat.id;
        activeSubId = cat.subcategories?.[0]?.id || null;
        renderAll();
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
    if (!filterQ) return cat.subcategories || [];
    // 搜索时高亮含命中标签的子分类 (其余折叠为空)
    return (cat.subcategories || []).filter((s) =>
      (s.tags || []).some(tagHits)
    );
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
      const hits = filterQ ? (sub.tags || []).filter(tagHits).length : (sub.tags || []).length;
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
    setTimeout(() => document.addEventListener("click", closeSubTabMenu, { once: true }), 0);
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
    const sub = subById(activeSubId);
    if (!sub) { $("#emptyHint").classList.remove("hidden"); return; }
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
      el.innerHTML =
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
      </div>
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
    menuEl.querySelector('[data-act="ok"]').onclick = () => {
      const g = (f) => menuEl.querySelector(`[data-f="${f}"]`);
      const en = g("en").value.trim();
      if (en) tag.en = en; else g("en").value = tag.en;
      tag.zh = g("zh").value.trim();
      const w = parseFloat(g("weight").value);
      if (!Number.isNaN(w) && w > 0 && w <= 3) tag.weight = w; else delete tag.weight;
      tag.aliases = g("aliases").value.split(",").map((s) => s.trim()).filter(Boolean);
      if (g("nsfw").checked) tag.nsfw = true; else delete tag.nsfw;
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
      icon: "🏷",
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
    (cat.subcategories ||= []).push({ id: sid, name: name.trim(), tags: [] });
    activeSubId = sid;
    markDirty(); renderAll();
  }

  function addTagRow() {
    const sub = subById(activeSubId);
    if (!sub) return toast("先选一个子分类页签", true);
    const en = prompt("英文文本 (出图用):", "");
    if (!en || !en.trim()) return;
    const zh = prompt("中文显示名 (可空):", "") || "";
    const taken = allTakenTagIds();
    const id = uidIn(taken, `${sub.id}.${slugify(en)}`);
    sub.tags.push({ id, en: en.trim(), zh: zh.trim(), weight: 1.0, aliases: [], enabled: true });
    markDirty(); renderTable(); renderStats();
  }

  function openPasteDialog() {
    const cat = catById(activeCatId);
    const sub = subById(activeSubId);
    if (!cat || !sub) return toast("先选好分类和子分类", true);
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
      const nsfwFlag = (parts[3] || "").toLowerCase() === "nsfw" || undefined;
      const tag = { id: uidIn(taken, `${sub.id}.${slugify(en)}`), en, zh, weight, aliases: [], enabled: true };
      if (nsfwFlag) tag.nsfw = true;
      sub.tags.push(tag);
      added++;
    }
    $("#pasteDialog").classList.add("hidden");
    markDirty(); renderTable(); renderStats();
    toast(`批量导入 ${added} 条${skipped ? `, 跳过 ${skipped} 条空行` : ""}`);
  }

  /* ---------- 📤 导出模板 (基础/全量两种, 文件内嵌 AI 使用说明) ----------
     按当前库的分类结构实时生成 .md; 说明写在 HTML 注释里 (导入解析时被忽略)。 */
  function fmtTag(t) {
    let s = t.en || "";
    if (t.zh) s += `(${t.zh})`;
    if (t.weight && t.weight !== 1.0) s += `{${t.weight}}`;
    if (t.nsfw) s += "[nsfw]";
    return s;
  }

  const TPL_RULES = ` 1. 保持「# 大分类」「## 子分类」两级标题结构 (全量模板重构分类时除外, 见下)
 2. 每行写多个标签, 用逗号分隔; 单个标签语法:
      english(中文翻译){权重}[nsfw]
    - 中文翻译尽量填写; 权重可省略 (默认 1.0); NSFW 词必须带 [nsfw] 后缀
    - 例: smile(微笑){1.1}, long hair(长发), some_word(某描述){1.0}[nsfw]
 3. 完成后把整个文件内容直接输出返回 (保持 Markdown 格式)
导入: 回填的文件 → 管理页「📥 导入」, 自动按分类归位+去重, 预览确认后入库`;

  function buildTemplateMd(full) {
    const SAMPLES = 5;
    const scope = full
      ? `任务: 本文件包含标签库的全部标签。你可以:
 - 在任意「## 子分类」下继续补充新标签 (不要与现有标签重复)
 - 配合「🗑 清空标签库」后导入本文件, 即可重构一二级分类 (增删改标题、重新组织标签)
 - 直接把本文件分享给别人, 对方导入即可获得整库`
      : `任务: 为每个「## 子分类」补充 8~15 个高质量、互相不重复的新标签。
已有标签只是格式示例 (每个子分类最多展示 ${SAMPLES} 个), 原样保留不要改。`;
    const head = `<!--
==================================================================
🏷 ComfyUI-TagLibrary 标签模板 (${full ? "全量" : "基础"}) —— 标签库管理页自动生成, 与当前库分类结构实时一致

【使用说明 —— 直接把本文件发给 AI, 并附一句: "请按文件内说明处理"】

${scope}
规则:
${TPL_RULES}
==================================================================
-->`;
    const parts = [head];
    for (const cat of lib.categories || []) {
      parts.push(``, `# ${cat.name}`);
      const subs = cat.subcategories || [];
      if (!subs.length) parts.push(`<!-- (此大分类暂无子分类) -->`);
      for (const sub of subs) {
        parts.push(``, `## ${sub.name}`);
        const tags = (sub.tags || []);
        const shown = full ? tags : tags.slice(0, SAMPLES);
        if (!shown.length) {
          parts.push(`<!-- (此子分类暂无标签, 请在下方补充) -->`);
        } else {
          for (let i = 0; i < shown.length; i += 6)
            parts.push(shown.slice(i, i + 6).map(fmtTag).join(", "));
          if (!full && tags.length > SAMPLES)
            parts.push(`<!-- (另有 ${tags.length - SAMPLES} 个已有标签未展示, 补充时避免与其重复) -->`);
        }
      }
    }
    parts.push("");
    return parts.join("\n");
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function exportTemplate(full) {
    downloadText(buildTemplateMd(full), full ? "taglib_模板_全量.md" : "taglib_模板.md");
    toast(full ? "全量模板已下载" : "基础模板已下载: 发给 AI, 回填后从「📥 导入」预览入库");
    $("#templateDialog").classList.add("hidden");
  }

  function importJson(file) {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const incoming = JSON.parse(reader.result);
        if (!Array.isArray(incoming.categories)) throw new Error("缺少 categories 数组");
        if (dirty && !confirm("当前有未保存修改, 导入将覆盖工作树。继续?")) return;
        // 合并策略: 按 id 去重追加 (同名覆盖属性)
        const exist = new Map(lib.categories.map((c) => [c.id, c]));
        for (const icat of incoming.categories) {
          if (exist.has(icat.id)) {
            Object.assign(exist.get(icat.id), icat);  // 整体替换该分类
          } else {
            lib.categories.push(icat);
            exist.set(icat.id, icat);
          }
        }
        keepSelection();
        markDirty(); renderAll();
        toast("导入完成 (工作树已更新, 记得保存)");
      } catch (err) {
        toast(`导入失败: ${err.message}`, true);
      }
    };
    reader.readAsText(file, "utf-8");
  }

  /* ---------------- 导入预览: dry-run -> 确认弹窗 -> 真正入库 ---------------- */
  let pendingPayload = null;   // 确认后原样发给 /import 的请求体

  function renderPreview(out) {
    $("#pvCount").textContent = out.total_new;
    $("#pvDup").textContent = out.duplicates_removed;
    const box = $("#previewList");
    box.innerHTML = "";
    for (const g of out.groups || []) {
      const head = document.createElement("div");
      head.className = "pv-group";
      head.textContent = `${g.cat_icon || "📦"} ${g.cat} / ${g.sub}`;
      box.appendChild(head);
      const flow = document.createElement("div");
      flow.className = "pv-flow";
      for (const t of g.tags) {
        const chip = document.createElement("span");
        chip.className = "pv-tag" + (t.nsfw ? " nsfw" : "");
        chip.textContent = t.en + (t.zh ? ` ${t.zh}` : "") +
          (t.weight && t.weight !== 1.0 ? ` {${t.weight}}` : "");
        flow.appendChild(chip);
      }
      box.appendChild(flow);
    }
  }

  async function openImportPreview(payload) {
    const res = await fetch("/taglib/api/tagfiles/preview-import", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TagLib-Mtime": String(serverMtime) },
      body: JSON.stringify(payload),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) { toast(`解析失败: ${out.error || "HTTP " + res.status}`, true); return; }
    if (!out.total_new) {
      toast(`没有新增标签 (跳过已有 ${out.duplicates_removed} 个), 无需导入`);
      return;
    }
    pendingPayload = payload;
    renderPreview(out);
    $("#previewDialog").classList.remove("hidden");
  }

  async function confirmImport() {
    if (!pendingPayload) return;
    $("#pvOk").disabled = true;
    try {
      const res = await fetch("/taglib/api/tagfiles/import", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-TagLib-Mtime": String(serverMtime) },
        body: JSON.stringify(pendingPayload),
      });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已新增 ${out.imported_new_tags} 个标签, 跳过已有 ${out.duplicates_removed} 个`);
      $("#previewDialog").classList.add("hidden");
      pendingPayload = null;
      await load();
      refreshFileList();
    } catch (err) {
      toast(`导入失败: ${err.message}`, true);
    } finally {
      $("#pvOk").disabled = false;
    }
  }

  /* ---------------- 标签文件导入 (两级文件夹 = 两级分类) ---------------- */
  let lastFiles = [];   // 最近一次列表, 供「全部导入」使用
  let libraryDir = "";

  function filePayload(files) {
    // files: [{path, cat_dir, sub_dir}] -> 请求体 (items + 可选外置目录)
    const dir = $("#extDirInput").value.trim();
    const body = { items: files.map((f) => ({ path: f.path, cat_dir: f.cat_dir || null, sub_dir: f.sub_dir || null })) };
    if (dir) body.external_dir = dir;
    return body;
  }

  async function refreshFileList() {
    const dir = $("#extDirInput").value.trim();
    const r = await fetch("/taglib/api/tagfiles" + (dir ? `?dir=${encodeURIComponent(dir)}` : ""));
    const data = await r.json();
    if (!data.ok) return;
    libraryDir = data.library_dir || "";
    $("#builtinDir").textContent = libraryDir;
    lastFiles = data.files || [];
    const box = $("#fileList");
    box.innerHTML = "";
    // 按文件夹归属分组: 大类 / 子分类 / 散文件
    const groups = new Map();   // "cat/sub" -> files[]
    const loose = [];
    for (const f of lastFiles) {
      if (f.cat_dir) {
        const key = `${f.cat_dir}/${f.sub_dir || ""}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(f);
      } else {
        loose.push(f);
      }
    }
    const mkRow = (f, indent) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const src = f.source === "builtin" ? "内置" : "外置";
      const loc = f.cat_dir ? `${f.cat_dir}${f.sub_dir ? " / " + f.sub_dir : ""}` : "散文件 (按文件内标题)";
      row.style.paddingLeft = indent ? "26px" : "";
      row.innerHTML = `<span class="f-src ${f.source}">${src}</span>
        <span class="f-name">${escapeHtml(f.file_name)}</span>
        <span class="muted">${escapeHtml(loc)} · ${(f.size / 1024).toFixed(1)} KB</span>`;
      const btn = document.createElement("button");
      btn.className = "btn small primary";
      btn.textContent = "⬇ 导入";
      btn.onclick = () => openImportPreview(filePayload([f]));
      row.appendChild(btn);
      return row;
    };
    for (const [key, files] of groups) {
      const [c, s] = key.split("/");
      const head = document.createElement("div");
      head.className = "file-group";
      head.textContent = `📁 ${c}${s ? ` / 📁 ${s}` : ""}`;
      box.appendChild(head);
      for (const f of files) box.appendChild(mkRow(f, true));
    }
    if (loose.length) {
      const head = document.createElement("div");
      head.className = "file-group";
      head.textContent = "📄 散文件";
      box.appendChild(head);
      for (const f of loose) box.appendChild(mkRow(f, false));
    }
    if (!lastFiles.length)
      box.innerHTML = `<div class="empty">目录里没有 .md/.txt 文件。点「📁 同步当前库到文件夹」生成结构。</div>`;
  }

  async function importAllFiles() {
    if (!lastFiles.length) return toast("没有可导入的文件", true);
    await openImportPreview(filePayload(lastFiles));
  }

  async function syncToFolder() {
    const dir = $("#extDirInput").value.trim();
    if (dirty && !confirm("有未保存修改, 同步的是已保存的库内容。先保存再同步? (确定=继续同步)")) return;
    try {
      const res = await fetch("/taglib/api/tagfiles/export-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dir ? { dir } : {}),
      });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已导出 ${out.categories} 个分类 / ${out.subcategories} 个子分类 / ${out.tags} 标签 → ${out.folder}`);
      await refreshFileList();
    } catch (err) {
      toast(`同步失败: ${err.message}`, true);
    }
  }

  function openFilesDialog() {
    $("#filesDialog").classList.remove("hidden");
    refreshFileList();
  }

  async function uploadFiles(files) {
    // .md/.txt → 预览确认入库; .json → 按库结构合并进工作树 (保存时落盘)
    const texts = [];
    for (const file of files) {
      if (file.name.toLowerCase().endsWith(".json")) {
        importJson(file);
        continue;
      }
      texts.push({ text: await file.text() });
    }
    if (texts.length) await openImportPreview({ items: texts });
    await load();
    refreshFileList();
  }

  $("#btnFiles").onclick = openFilesDialog;
  $("#filesCancel").onclick = () => $("#filesDialog").classList.add("hidden");
  $("#extDirInput").onchange = refreshFileList;
  $("#btnImportAll").onclick = importAllFiles;
  $("#btnSyncFolder").onclick = syncToFolder;
  $("#mdFileInput").onchange = (e) => {
    if (e.target.files.length) uploadFiles([...e.target.files]);
    e.target.value = "";
  };
  $("#pvOk").onclick = confirmImport;
  $("#pvCancel").onclick = () => { $("#previewDialog").classList.add("hidden"); pendingPayload = null; };

  /* ---------------- bind UI ---------------- */
  $("#btnAddCat").onclick = addCategory;
  $("#btnAddSub").onclick = addSubcategory;
  $("#btnAddTag").onclick = addTagRow;
  $("#btnPaste").onclick = openPasteDialog;
  $("#pasteOk").onclick = doPasteImport;
  $("#pasteCancel").onclick = () => $("#pasteDialog").classList.add("hidden");
  $("#btnTemplate").onclick = () => $("#templateDialog").classList.remove("hidden");
  $("#tplBasic").onclick = () => exportTemplate(false);
  $("#tplFull").onclick = () => exportTemplate(true);
  $("#tplCancel").onclick = () => $("#templateDialog").classList.add("hidden");
  $("#btnImport").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => {
    if (e.target.files.length) uploadFiles([...e.target.files]);
    e.target.value = "";
  };

  /* ---------- 备份库 / 清空标签库 ---------- */
  async function backupSave() {
    if (dirty && !confirm("有未保存修改, 备份的是已保存的库内容。先保存再备份? (确定=继续备份)")) return;
    try {
      const res = await fetch("/taglib/api/library/backup", { method: "POST" });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast(`✅ 已存为默认库 (备份于 data/备份库/, ${new Date(out.mtime * 1000).toLocaleString()})`);
    } catch (err) {
      toast(`备份失败: ${err.message}`, true);
    }
  }

  async function backupRestore() {
    if (dirty && !confirm("有未保存修改, 恢复会覆盖工作树。继续?")) return;
    if (!confirm("恢复备份库 = 用 data/备份库/ 里的内容整体覆盖当前标签库。确定?")) return;
    try {
      const res = await fetch("/taglib/api/library/restore-backup", { method: "POST" });
      const out = await res.json();
      if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
      toast("✅ 已从备份恢复标签库");
      await load();
    } catch (err) {
      toast(`恢复失败: ${err.message}`, true);
    }
  }

  async function clearLibrary(withExport) {
    $("#clearDialog").classList.add("hidden");
    if (withExport) exportTemplate(true);
    try {
      const r = await fetch(API, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast(withExport ? "全量模板已导出, 标签库已清空 (回出厂默认)" : "标签库已清空 (回出厂默认)");
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
  $("#btnSave").onclick = save;
  $("#btnCancel").onclick = async () => {
    if (dirty && !confirm("放弃当前全部未保存修改?")) return;
    await load();
    toast("已还原到上次保存的状态");
  };
  $("#globalSearch").oninput = (e) => {
    filterQ = e.target.value.trim();
    const cat = catById(activeCatId);
    if (cat && !(visibleSubs(cat)).some((s) => s.id === activeSubId))
      activeSubId = visibleSubs(cat)[0]?.id || null;
    renderTabs(); renderTable();
  };

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    if (e.key === "Escape") $("#pasteDialog").classList.add("hidden");
  });

  // 调试/测试钩子 (不参与 UI)
  window.__taglib = { openImportPreview, getLib: () => lib };

  load().catch((err) => toast(`加载失败: ${err.message}`, true));
})();
