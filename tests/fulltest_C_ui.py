"""全面真机功能验收 C: 设置弹窗 / 标签选择器 / 排除类目 / 搜索。"""
import json, time, urllib.request, base64
from websocket import create_connection

tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read())
        if t.get("type") == "page" and "8188" in t.get("url", "")]
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
mid = [30000]

def cmd(m, p=None, to=60):
    mid[0] += 1; ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    dl = time.time() + to
    while time.time() < dl:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]: return x
        except Exception: continue
    return {}

def ev(e, to=60):
    x = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    return "ERR:" + str(r.get("description", ""))[:400] if r.get("subtype") == "error" else r.get("value")

# ===== C1 设置弹窗: 分隔符/权重语法/去重/钉选必含 开关读写 =====
print("C1 SETTINGS:", ev("""(async () => {
  const n = window._tln || app.graph._nodes.find(x=>x.type==='TagLibraryNode');
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  // 找设置按钮 (齿轮/⚙)
  const setBtn = el.querySelector('[data-act="settings"]') || el.querySelector('.tl-settings-btn')
    || [...el.querySelectorAll('[data-act]')].find(b => /设置|随机/.test(b.title || ''));
  if (!setBtn) return 'NO settings btn: acts=' + [...el.querySelectorAll('[data-act]')].map(b=>b.dataset.act).join(',');
  setBtn.click();
  await new Promise(r=>setTimeout(r,700));
  const sv = document.querySelector('.sv-pinned');
  const sep = document.querySelector('.sv-sep');
  const wgt = document.querySelector('.sv-weights, [class*="weight"] input, [class*="weight"] select');
  const dd = document.querySelector('.sv-dedupe, [class*="dedupe"] input');
  const found = {pinnedChk: !!sv, sepSel: !!sep, weights: !!wgt, dedupe: !!dd};
  // 改分隔符 → 保存 → 检查 selection_state
  let saved = null;
  if (sep) {
    sep.value = 'space';
    sep.dispatchEvent(new Event('change', {bubbles:true}));
    const saveBtn = [...document.querySelectorAll('button')].find(b => /保存|save/i.test(b.textContent||b.className));
    if (saveBtn) { saveBtn.click(); await new Promise(r=>setTimeout(r,500)); }
    const st = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
    saved = st.separator;
  }
  // 关闭弹窗
  const cancel = document.querySelector('.tp-cancel') || [...document.querySelectorAll('button')].find(b => /取消|close/i.test(b.textContent));
  if (cancel) cancel.click();
  await new Promise(r=>setTimeout(r,300));
  return JSON.stringify({found, separator_after_save: saved});
})()"""))

# ===== C2 标签选择器: ➕ 打开 → 搜索 → 选词 → 添加 =====
print("C2 PICKER:", ev("""(async () => {
  const n = window._tln;
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  const addBtn = el.querySelector('[data-act="addtags"]');
  addBtn.click();
  await new Promise(r=>setTimeout(r,1200));
  const root = document.querySelector('#taglib-picker-root');
  if (!root) return 'PICKER NOT OPEN';
  const tabs = [...root.querySelectorAll('.tp-tabbtn')].map(b=>b.textContent.trim());
  // 搜索: 找搜索框
  const search = root.querySelector('input[type="text"], input[type="search"], .tp-search input, input');
  let searchResult = null;
  if (search) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(search, 'twintail');
    search.dispatchEvent(new Event('input', {bubbles:true}));
    await new Promise(r=>setTimeout(r,800));
    const tagBtns = [...root.querySelectorAll('.tp-tag')];
    searchResult = {matches: tagBtns.length, sample: tagBtns.slice(0,3).map(b=>b.textContent.trim())};
    if (tagBtns.length) { tagBtns[0].click(); await new Promise(r=>setTimeout(r,400)); }
  }
  // 确认添加 (找确定按钮)
  const ok = [...root.querySelectorAll('button')].find(b => /确定|添加|应用/.test(b.textContent||''));
  if (ok) { ok.click(); await new Promise(r=>setTimeout(r,800)); }
  const st = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
  const hasTwintail = st.tags.some(t=>/twintail/i.test(t.en));
  return JSON.stringify({tabs, searchResult, added: hasTwintail,
                          totalAfter: st.tags.length});
})()"""))

# ===== C3 排除类目: 勾掉场景环境 → 填充无场景词 =====
print("C3 EXCLUDE:", ev("""(async () => {
  const n = window._tln;
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  // 排除类目在选择器 tab 里
  const addBtn = el.querySelector('[data-act="addtags"]');
  addBtn.click();
  await new Promise(r=>setTimeout(r,1000));
  const root = document.querySelector('#taglib-picker-root');
  if (!root) return 'PICKER NOT OPEN';
  const excTab = root.querySelector('.tp-excludetab');
  if (!excTab) return 'NO exclude tab';
  excTab.click();
  await new Promise(r=>setTimeout(r,500));
  // 找 场景环境 卡片并勾选
  const card = [...root.querySelectorAll('.tp-exc-card')].find(c=>/场景环境/.test(c.textContent));
  if (!card) return 'NO scene card: ' + [...root.querySelectorAll('.tp-exc-card')].map(c=>c.textContent.trim().slice(0,8)).join(',');
  const wasEx = card.classList.contains('excluded');
  if (!wasEx) card.click();
  await new Promise(r=>setTimeout(r,300));
  const ok = [...root.querySelectorAll('button')].find(b => /确定|添加|应用/.test(b.textContent||''));
  if (ok) { ok.click(); await new Promise(r=>setTimeout(r,500)); }
  // 填充验证
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2200));
  const st = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
  const sceneWords = st.tags.filter(t => (t._cat||'') === '场景环境').length;
  const excluded = st.exclude_categories || [];
  // 恢复: 取消排除
  addBtn.click(); await new Promise(r=>setTimeout(r,800));
  const root2 = document.querySelector('#taglib-picker-root');
  const excTab2 = root2 && root2.querySelector('.tp-excludetab');
  if (excTab2) { excTab2.click(); await new Promise(r=>setTimeout(r,400));
    const card2 = [...root2.querySelectorAll('.tp-exc-card')].find(c=>/场景环境/.test(c.textContent));
    if (card2 && card2.classList.contains('excluded')) { card2.click(); await new Promise(r=>setTimeout(r,300)); }
    const ok2 = [...root2.querySelectorAll('button')].find(b => /确定|添加|应用/.test(b.textContent||''));
    if (ok2) { ok2.click(); await new Promise(r=>setTimeout(r,400)); }
  }
  return JSON.stringify({excludedList: excluded, sceneWordsWhileExcluded: sceneWords,
                          verdict: (excluded.some(e=>/场景/.test(e)) && sceneWords===0) ? 'PASS' : 'FAIL'});
})()"""))

shot = cmd("Page.captureScreenshot", {"format": "png"})
if shot.get("result", {}).get("data"):
    open("tests/fulltest_C.png", "wb").write(base64.b64decode(shot["result"]["data"]))
    print("shot saved")
