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
    (visibleSubs(cat)).forEach((sub) => {
      const el = document.createElement("span");
      el.className = "tab" + (sub.id === activeSubId ? " active" : "");
      const hits = filterQ ? (sub.tags || []).filter(tagHits).length : (sub.tags || []).length;
      el.innerHTML = `${sub.name} <span class="t-count">${hits}</span>`;
      el.onclick = () => { activeSubId = sub.id; renderTabs(); renderTable(); };
      box.appendChild(el);
    });
  }

  function renderTable() {
    const tbody = $("#tagRows");
    tbody.innerHTML = "";
    const sub = subById(activeSubId);
    if (!sub) { $("#emptyHint").classList.remove("hidden"); return; }
    $("#emptyHint").classList.add("hidden");

    const tags = (sub.tags || []).filter(tagHits);
    if (!tags.length && filterQ) {
      $("#emptyHint").textContent = `当前子分类没有匹配 "${filterQ}" 的标签`;
      $("#emptyHint").classList.remove("hidden");
      return;
    }
    $("#emptyHint").textContent =
      '没有标签。点右上「➕ 添加标签」或「📋 批量粘贴」。格式每行一条: english | 中文 | 权重';

    for (const tag of tags) {
      const tr = document.createElement("tr");
      if (tag.enabled === false) tr.classList.add("disabled-tag");
      if (tag.nsfw) tr.classList.add("nsfw-row");

      const tdEn = mkCellInput(tag.en, (v) => { tag.en = v.trim(); touched(tr); }, "英文文本");
      const tdZh = mkCellInput(tag.zh || "", (v) => { tag.zh = v.trim(); touched(tr); }, "中文显示名");
      const tdW = mkCellInput(String(tag.weight ?? 1.0), (v) => {
        const w = parseFloat(v);
        if (!Number.isNaN(w) && w > 0 && w <= 3) { tag.weight = w; touched(tr); }
      }, "(0,3]");
      tdW.firstChild.classList.add("w-num");

      const tdAlias = document.createElement("td");
      tdAlias.appendChild(mkAliasInput(tag));

      const tdEn3 = document.createElement("td");
      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = tag.enabled !== false;
      chk.onchange = () => { tag.enabled = chk.checked; touched(tr); tr.classList.toggle("disabled-tag", !chk.checked); renderStats(); };
      tdEn3.appendChild(chk);

      const tdNsfw = document.createElement("td");
      const nchk = document.createElement("input");
      nchk.type = "checkbox";
      nchk.className = "nsfw-chk";
      nchk.checked = !!tag.nsfw;
      nchk.title = "标记为 NSFW (节点 off 模式会排除)";
      nchk.onchange = () => { tag.nsfw = nchk.checked || undefined; if (!nchk.checked) delete tag.nsfw; touched(tr); };
      tdNsfw.appendChild(nchk);

      const tdDel = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "icon-btn del";
      delBtn.title = "删除标签";
      delBtn.textContent = "🗑";
      delBtn.onclick = () => {
        sub.tags = sub.tags.filter((t) => t !== tag);
        markDirty(); renderTable(); renderStats();
      };
      tdDel.appendChild(delBtn);

      tr.append(tdEn, tdZh, tdW, tdAlias, tdEn3, tdNsfw, tdDel);
      tbody.appendChild(tr);
    }
  }

  function touched() { markDirty(); }

  function mkCellInput(value, onchg, placeholder) {
    const td = document.createElement("td");
    const inp = document.createElement("input");
    inp.className = "cell-input";
    inp.value = value;
    inp.placeholder = placeholder || "";
    inp.onchange = () => onchg(inp.value);
    td.appendChild(inp);
    return td;
  }

  function mkAliasInput(tag) {
    const inp = document.createElement("input");
    inp.className = "cell-input";
    inp.value = (tag.aliases || []).join(", ");
    inp.placeholder = "同义词, 逗号隔开";
    inp.onchange = () => {
      tag.aliases = inp.value.split(",").map((s) => s.trim()).filter(Boolean);
      markDirty();
    };
    const wrap = document.createElement("div");
    wrap.appendChild(inp);
    return wrap;
  }

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

  function exportJson() {
    const blob = new Blob([JSON.stringify(lib, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "tag_library.export.json";
    a.click();
    URL.revokeObjectURL(a.href);
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

  async function resetDefault() {
    if (!confirm("恢复默认库 = 清空你的全部修改 (用户库删除)。确定?")) return;
    if (dirty && !confirm("还有未保存的修改也会一并丢弃。继续?")) return;
    try {
      // 直接以"空categories + 墓碑清空"提交会全删 —— 所以恢复默认要走后端约定:
      // 提交一棵与默认库等价的空树会被墓碑机制误伤, 干脆提供专用信号: 空 payload + reset flag
      const r = await fetch(API, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast("已恢复默认库");
      await load();
    } catch (err) {
      toast(`恢复失败: ${err.message} (也可以手动删除 custom_nodes/ComfyUI-TagLibrary/data/tag_library.user.json 后刷新)`, true);
    }
  }

  /* ---------------- bind UI ---------------- */
  $("#btnAddCat").onclick = addCategory;
  $("#btnAddSub").onclick = addSubcategory;
  $("#btnAddTag").onclick = addTagRow;
  $("#btnPaste").onclick = openPasteDialog;
  $("#pasteOk").onclick = doPasteImport;
  $("#pasteCancel").onclick = () => $("#pasteDialog").classList.add("hidden");
  $("#btnExport").onclick = exportJson;
  $("#btnImport").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => {
    if (e.target.files[0]) importJson(e.target.files[0]);
    e.target.value = "";
  };
  $("#btnReset").onclick = resetDefault;
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

  load().catch((err) => toast(`加载失败: ${err.message}`, true));
})();
