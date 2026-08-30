"""钉选语义 v2 真机验收: no-ghost / 占配额 / 位置归位 / auto 回显保留钉选。"""
import json, time, urllib.request, base64
from websocket import create_connection

tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read())
        if t.get("type") == "page" and "8188" in t.get("url", "")]
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
mid = [11000]

def cmd(m, p=None, to=20):
    mid[0] += 1; ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    dl = time.time() + to
    while time.time() < dl:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]: return x
        except Exception: continue
    return {}

def ev(e, to=20):
    x = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    return "ERR:" + str(r.get("description", ""))[:300] if r.get("subtype") == "error" else r.get("value")

# 0) 刷新页面 (加载新 JS)
cmd("Page.reload", {"ignoreCache": True})
time.sleep(8)
for i in range(20):
    if ev("!!(window.app && app.graph && app.graph._nodes && document.querySelector('.tp-master, .tl-head'))") is True:
        break
    time.sleep(2)
print("page ready")

# 1) 节点就位 + 面板渲染
print("SETUP:", ev("""(() => {
  let n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  if (!n) { n = LiteGraph.createNode('TagLibraryNode'); n.pos=[260,180]; app.graph.add(n); }
  return 'node id=' + n.id;
})()"""))
time.sleep(4)

# 2) 手动模式: 状态清空 → 手动加一个钉选 smile (表情情绪) → 填充
print("PIN+ROLL:", ev("""(async () => {
  const n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  const w = n.widgets.find(x=>x.name==='selection_state');
  const st = JSON.parse(w.value || '{}');
  st.tags = [{en:'smile', weight:1.0, aliases:[], zh:'微笑', id:'subject.s3.smile',
              type:'content', priority:50, rarity:'common', groups:[], requires:[],
              mutex_with:[], desc:'', meta:{}, enabled:true, pinned:true, _cat:'人物主体'}];
  st.pinned_required = true;
  st.exclude_categories = [];
  w.value = JSON.stringify(st);
  n.setDirtyCanvas(true,true);
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2500));
  const st2 = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
  const tags = st2.tags;
  const smileIdx = tags.findIndex(t=>t.en==='smile');
  return JSON.stringify({
    total: tags.length,
    smilePinnedSurvived: smileIdx>=0 && tags[smileIdx].pinned,
    domGhostPins: el.querySelectorAll('.tl-pin.ghost').length,
    domPinnedReal: el.querySelectorAll('.tl-pin.pinned').length,
    nonPinnedChipHasPinIcon: [...el.querySelectorAll('.tl-ttag')].filter(c=>!c.querySelector('.tl-pin.pinned') && c.querySelector('.tl-pin')).length
  });
})()""", 25))

# 3) 位置断言: smile 应在"人物主体"分组内而不是最顶上
print("POSITION:", ev("""(() => {
  const n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  const chips = [...el.querySelectorAll('.tl-ttag')];
  const heads = [...el.querySelectorAll('.tl-fill-group')];
  const smileChip = chips.find(c=>c.querySelector('b')?.textContent==='smile');
  const smilePinned = smileChip && smileChip.querySelector('.tl-pin.pinned');
  // smile 前面应有分组标题行 (人物主体), 而不是 smile 直接排第一
  const firstIsHead = el.firstElementChild?.classList?.contains('tl-fill-group');
  const headTexts = heads.map(h=>h.textContent.trim()).slice(0,12);
  return JSON.stringify({
    smileHasRealPin: !!smilePinned,
    heads: headTexts,
    firstChildIsGroupHead: !!firstIsHead
  });
})()"""))

# 4) auto 模式队列模拟: 直接调后端格式化路径验证 (Queue 太重, 用 engine 一致性)
print("AUTO-QUEUE:", ev("""(async () => {
  const n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  el.querySelector('[data-mode="auto"]').click();
  await new Promise(r=>setTimeout(r,500));
  el.querySelector('[data-act="roll"]').click();
  await new Promise(r=>setTimeout(r,2500));
  const st = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
  const smile = st.tags.find(t=>t.en==='smile');
  el.querySelector('[data-mode="manual"]').click();
  return JSON.stringify({
    mode2: n.widgets.find(w=>w.name==='mode').value,
    smileStillPinned: !!(smile && smile.pinned),
    total: st.tags.length
  });
})()""", 25))

shot = cmd("Page.captureScreenshot", {"format": "png"})
if shot.get("result", {}).get("data"):
    open("tests/pin_v2_final.png", "wb").write(base64.b64decode(shot["result"]["data"]))
    print("shot saved")
