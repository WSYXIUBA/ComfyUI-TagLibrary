"""全面真机功能验收 A: NSFW 开关 / 性别开关 / 填充 / 钉选占名额 (手动模式)。

前置: ComfyUI 8188 + Edge 9222 (页面已开 ComfyUI)。
"""
import json, time, urllib.request, base64
from websocket import create_connection

tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read())
        if t.get("type") == "page" and "8188" in t.get("url", "")]
assert tabs, "no comfyui tab"
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=40, suppress_origin=True)
mid = [15000]

def cmd(m, p=None, to=40):
    mid[0] += 1; ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    dl = time.time() + to
    while time.time() < dl:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]: return x
        except Exception: continue
    return {}

def ev(e, to=40):
    x = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    return "ERR:" + str(r.get("description", ""))[:300] if r.get("subtype") == "error" else r.get("value")

JS_READY = """(() => {
  const n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  window._tln = n;
  return n ? 'node ok id=' + n.id : 'NO NODE';
})()"""

# ===== A0 页面就绪 =====
cmd("Page.reload", {"ignoreCache": True})
time.sleep(8)
for i in range(25):
    if ev("!!(window.app && app.graph && document.querySelector('.tp-master, .tl-head'))") is True:
        break
    time.sleep(2)
print("A0 ready:", ev(JS_READY))
time.sleep(3)

# ===== A1 NSFW 开关 =====
JS_NSFW = """(async () => {
  const el = window._tln.widgets.find(x=>x.name==='taglib_panel').element;
  const n = window._tln;
  const getVal = () => n.widgets.find(x=>x.name==='selection_state').value;
  const nsfwBtn = el.querySelector('[data-act="nsfw"]');
  const was = nsfwBtn.classList.contains('on');
  if (was) nsfwBtn.click();
  await new Promise(r=>setTimeout(r,400));
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2200));
  const t1 = JSON.parse(getVal()).tags;
  const nsfw1 = t1.filter(t=>t.nsfw).length;
  nsfwBtn.click();
  await new Promise(r=>setTimeout(r,400));
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2200));
  const t2 = JSON.parse(getVal()).tags;
  const nsfw2 = t2.filter(t=>t.nsfw).length;
  nsfwBtn.click();
  await new Promise(r=>setTimeout(r,300));
  return JSON.stringify({off_fill: t1.length, nsfw_words_off: nsfw1,
                          on_fill: t2.length, nsfw_words_on: nsfw2,
                          verdict: (nsfw1===0 && nsfw2>0) ? 'PASS'
                                 : (nsfw1===0&&nsfw2===0 ? 'WEAK-no-nsfw-word-drawn' : 'FAIL')});
})()"""
print("A1 NSFW:", ev(JS_NSFW))

# ===== A2 性别三态 =====
JS_GENDER = """(async () => {
  const el = window._tln.widgets.find(x=>x.name==='taglib_panel').element;
  const gBtn = el.querySelector('[data-act="gender"]');
  const labels = [];
  gBtn.click(); await new Promise(r=>setTimeout(r,350)); labels.push(gBtn.textContent.trim() + ':' + (gBtn.title||'').slice(0,12));
  gBtn.click(); await new Promise(r=>setTimeout(r,350)); labels.push(gBtn.textContent.trim());
  gBtn.click(); await new Promise(r=>setTimeout(r,350)); labels.push(gBtn.textContent.trim());
  gBtn.click(); await new Promise(r=>setTimeout(r,350)); labels.push(gBtn.textContent.trim());  // 回到 off
  // 现在 off。切到 female: 再点一次(顺序 off->female)
  gBtn.click(); await new Promise(r=>setTimeout(r,350));
  const cur = gBtn.textContent.trim();
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2200));
  const tags = JSON.parse(window._tln.widgets.find(x=>x.name==='selection_state').value).tags;
  const maleWords = tags.filter(t=>/1boy|multiple boys|male only/i.test(t.en)).length;
  const girlWords = tags.filter(t=>/1girl|multiple girls/i.test(t.en)).length;
  gBtn.click(); await new Promise(r=>setTimeout(r,300));  // 回 off
  return JSON.stringify({cycle: labels, female_mode_label: cur, fill_total: tags.length,
                          male_words_in_female_mode: maleWords, girl_words: girlWords,
                          verdict: (maleWords===0) ? 'PASS' : 'FAIL-male-leak'});
})()"""
print("A2 GENDER:", ev(JS_GENDER))

# ===== A3 钉选占名额 (1~1) =====
JS_PINQ = """(async () => {
  const el = window._tln.widgets.find(x=>x.name==='taglib_panel').element;
  const n = window._tln;
  const w = n.widgets.find(x=>x.name==='selection_state');
  const st = JSON.parse(w.value || '{}');
  st.tags = [{en:'smile', weight:1.0, zh:'微笑', id:'subject.s3.smile', enabled:true, pinned:true, _cat:'人物主体'}];
  st.pinned_required = true; st.exclude_categories = [];
  st.fill_master = true; st.fill_master_min = 1; st.fill_master_max = 1;
  w.value = JSON.stringify(st); n.setDirtyCanvas(true,true);
  el.querySelector('[data-mode="manual"]').click();
  await new Promise(r=>setTimeout(r,400));
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2400));
  const tags = JSON.parse(w.value).tags;
  const smile = tags.find(t=>t.en==='smile');
  const EXPR = ['smile','gentle smile','serious','cat smile','fake smile','grin','laughing','pouting','crying','angry','blush','surprised','wink','smirk','smug','tears','sweating','nervous','embarrassed','excited','bored','sleepy','confused','determined','shocked','smiling','happy','sad'];
  const exprWords = tags.filter(t => EXPR.includes(t.en));
  return JSON.stringify({total: tags.length, smilePinned: !!(smile&&smile.pinned),
    exprSubWords: exprWords.map(t=>t.en),
    verdict: (smile&&smile.pinned && exprWords.length===1) ? 'PASS' : 'FAIL'});
})()"""
print("A3 PIN-QUOTA:", ev(JS_PINQ))

# ===== A4 多轮填充稳定性 (3 轮, 钉选始终幸存 + 无重复) =====
JS_ROLL3 = """(async () => {
  const el = window._tln.widgets.find(x=>x.name==='taglib_panel').element;
  const n = window._tln;
  const w = n.widgets.find(x=>x.name==='selection_state');
  const rounds = [];
  for (let k=0;k<3;k++) {
    el.querySelector('[data-act="roll"]').click();
    await new Promise(r=>setTimeout(r,2200));
    const tags = JSON.parse(w.value).tags;
    const ens = tags.map(t=>t.en);
    const dup = ens.length !== new Set(ens.map(x=>x.toLowerCase())).size;
    const smile = tags.find(t=>t.en==='smile');
    rounds.push({round: k+1, total: tags.length, dup, smilePinned: !!(smile&&smile.pinned)});
  }
  return JSON.stringify(rounds);
})()"""
print("A4 ROLLx3:", ev(JS_ROLL3))

shot = cmd("Page.captureScreenshot", {"format": "png"})
if shot.get("result", {}).get("data"):
    open("tests/fulltest_A.png", "wb").write(base64.b64decode(shot["result"]["data"]))
    print("shot saved")
