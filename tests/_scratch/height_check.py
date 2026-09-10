"""高度跟随实测: 异步测试 + 轮询结果 (页面 reload 会杀 CDP 上下文, 不能 await 跨 reload)。"""

import json
import time
import urllib.request

from websocket import create_connection


def fresh_ws():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v5check" in t.get("url", "")]
    return create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)


def cmd(ws, expr, wait=True, to=10):
    mid = int(time.time() * 1000) % 1000000
    ws.settimeout(to)
    ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": False}}))
    if not wait:
        return None
    while True:
        x = json.loads(ws.recv())
        if x.get("id") == mid:
            return x["result"].get("result", {}).get("value")


JS_START = """
window.__res = null;
(async () => {
  if (document.body.innerText.includes('拒绝访问')) { location.reload(); window.__res='403'; return; }
  if (!window.app || !app.graph) { window.__res = 'notready'; return; }
  await app.graph.clear();
  const node = LiteGraph.createNode('TagLibraryNode');
  node.pos = [120, 100]; node.size = [470, 720];
  app.graph.add(node);
  await new Promise(r => setTimeout(r, 2200));
  const panel = document.querySelector('.taglib-panel');
  const sw = node.widgets.find(w => w.name === 'selection_state');
  const st = JSON.parse(sw.value);
  st.tags = [{en:'closed mouth', zh:'闭嘴', enabled:true},
             {en:'crying', zh:'哭泣', enabled:true}];
  sw.value = JSON.stringify(st);
  node.setDirtyCanvas(true, true);
  await new Promise(r => setTimeout(r, 600));
  const h1 = Math.round(panel.getBoundingClientRect().height);
  node.size[1] = 1080;
  app.canvas.setDirty(true, true);
  await new Promise(r => setTimeout(r, 1200));
  const h2 = Math.round(panel.getBoundingClientRect().height);
  const w = node.size[0];
  node.size[0] = 620;
  app.canvas.setDirty(true, true);
  await new Promise(r => setTimeout(r, 600));
  window.__res = JSON.stringify({
    h_at_720: h1, h_at_1080: h2,
    followsHeight: h2 > h1 + 80,
    tagEls: document.querySelectorAll('.tl-ttag').length,
    green: document.querySelectorAll('.tl-ttag.on').length,
    greyAfterToggle: 'skipped'
  });
})();
"""

ws = fresh_ws()
cmd(ws, JS_START, wait=False)
print("test fired, polling...")

value = None
for _ in range(30):
    time.sleep(1)
    try:
        ws2 = fresh_ws()
        v = cmd(ws2, "window.__res", wait=True, to=8)
        ws2.close()
        if v and v != "null":
            value = v
            break
    except Exception:
        continue

print("RESULT:", value)
