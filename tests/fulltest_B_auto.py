"""全面真机功能验收 B: 自动模式真实 Queue 多轮 (出词/分组/回显/钉选幸存/防冲突)。"""
import json, time, urllib.request, base64
from websocket import create_connection

tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read())
        if t.get("type") == "page" and "8188" in t.get("url", "")]
assert tabs, "no comfyui tab"
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
mid = [17000]

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
    return "ERR:" + str(r.get("description", ""))[:300] if r.get("subtype") == "error" else r.get("value")

print("B0 node:", ev("""(() => {
  const n = app.graph._nodes.find(x => x.type==='TagLibraryNode');
  window._tln = n;
  return n ? 'ok id=' + n.id : 'NO NODE';
})()"""))

# 预置: 钉选 smile + masterpiece, auto 模式
print("B1 setup:", ev("""(() => {
  const n = window._tln;
  const w = n.widgets.find(x=>x.name==='selection_state');
  const st = JSON.parse(w.value || '{}');
  st.tags = [
    {en:'smile', weight:1.0, zh:'微笑', id:'subject.s3.smile', enabled:true, pinned:true, _cat:'人物主体'},
    {en:'masterpiece', weight:1.2, zh:'杰作', id:'quality.s1.masterpiece', enabled:true, pinned:true, _cat:'质量与技术'}
  ];
  st.pinned_required = true; st.exclude_categories = [];
  st.fill_master = true; st.fill_master_min = 1; st.fill_master_max = 1;
  w.value = JSON.stringify(st);
  n.widgets.find(x=>x.name==='mode').value = 'auto';
  n.setDirtyCanvas(true,true);
  return 'auto mode, 2 pins (smile + masterpiece)';
})()"""))

# Queue 3 轮
for rnd in range(3):
    r = ev("""(async () => {
      const n = window._tln;
      app.queuePrompt(0, 1);
      await new Promise(res => {
        const h = (d) => {
          const detail = d?.detail || {};
          if (String(detail.node) === String(n.id) && detail.output?.taglib_echo) {
            app.api.removeEventListener('executed', h);
            res(true);
          }
        };
        app.api.addEventListener('executed', h);
        setTimeout(() => res('timeout'), 45000);
      });
      await new Promise(r=>setTimeout(r,1200));
      const st = JSON.parse(n.widgets.find(x=>x.name==='selection_state').value);
      const tags = st.tags;
      const ens = tags.map(t=>t.en.toLowerCase());
      const smile = tags.find(t=>t.en==='smile');
      const master = tags.find(t=>t.en==='masterpiece');
      const el = n.widgets.find(x=>x.name==='taglib_panel').element;
      const heads = [...el.querySelectorAll('.tl-fill-group')].map(h=>h.textContent.trim());
      const pinnedIcons = el.querySelectorAll('.tl-pin.pinned').length;
      // 防冲突: 同组词不应同时出现 (open mouth vs closed mouth)
      const openMouth = ens.includes('open mouth'), closedMouth = ens.includes('closed mouth');
      return JSON.stringify({total: tags.length, smilePinned: !!(smile&&smile.pinned),
        masterPinned: !!(master&&master.pinned), dups: ens.length !== new Set(ens).size,
        groupHeads: heads.length, pinnedIconsOnDom: pinnedIcons,
        mutexClash: (openMouth && closedMouth) ? 'CLASH!' : 'ok'});
    })()""", 60)
    print(f"B2 queue round {rnd+1}:", r)

# 检查输出预览 (positive 文本)
print("B3 preview:", ev("""(() => {
  const n = window._tln;
  const el = n.widgets.find(x=>x.name==='taglib_panel').element;
  const pv = el.parentElement?.querySelector('.tl-preview') || document.querySelector('.tl-preview');
  const txt = pv ? pv.textContent : '(preview el not found)';
  return JSON.stringify({previewHead: txt.slice(0, 200), len: txt.length});
})()"""))

shot = cmd("Page.captureScreenshot", {"format": "png"})
if shot.get("result", {}).get("data"):
    open("tests/fulltest_B.png", "wb").write(base64.b64decode(shot["result"]["data"]))
    print("shot saved")
