"""v1.1.0 CSS 裸块修复后真机验收: 面板渲染 / DOM widget / CSS 注入 / 右键菜单样式。

前置: ComfyUI 8188 运行中, Edge --remote-debugging-port=9222 已打开 ComfyUI 页面。
"""
import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "8188" in t.get("url", "")]

assert tabs, "no comfyui page tab found"
ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
mid = [5200]


def cmd(m, p=None, to=15):
    mid[0] += 1
    ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    deadline = time.time() + to
    while time.time() < deadline:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]:
                return x
        except Exception:
            continue
    return {}


def ev(expr, to=15):
    x = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                 "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    if r.get("subtype") == "error":
        return "ERR:" + str(r.get("description", ""))[:200]
    return r.get("value")


# 0) 等 app 就绪 (最多 40s)
for i in range(20):
    ready = ev("!!(window.app && app.graph && app.graph._nodes)")
    if ready is True or ready == "true":
        break
    time.sleep(2)
print("app ready:", ready)

# 1) 扩展模块加载检查 (css 炸的话 extensions 会缺 taglib)
print("ext check:", ev("""
(() => {
  const exts = (app.extensions || []).map(e => e.name || '?').join(',');
  return 'extensions=[' + exts + ']';
})()
"""))

# 2) 添加节点 (程序化, 验收路径)
print("add node:", ev("""
(() => {
  if (app.graph._nodes.some(n => n.type === 'TagLibraryNode')) return 'exists';
  const n = LiteGraph.createNode('TagLibraryNode');
  if (!n) return 'create FAIL';
  n.pos = [260, 180];
  app.graph.add(n);
  app.canvas.setDirty(true, true);
  return 'added id=' + n.id;
})()
"""))

# 3) 等异步面板构建 (fetch library + widget build)
for i in range(10):
    time.sleep(1.5)
    ok = ev("""(() => {
      const n = app.graph._nodes.find(x => x.type === 'TagLibraryNode');
      if (!n) return 'no node';
      return !!document.querySelector('.tp-master') && !!n.widgets;
    })()""")
    if ok is True or ok == "true":
        break
print("panel built:", ok)

# 4) 综合断言
print("ASSERT:", ev("""(() => {
  const n = app.graph._nodes.find(x => x.type === 'TagLibraryNode');
  if (!n) return 'FAIL: no node';
  const w = (n.widgets || []).map(x => x.name);
  const sel = (n.widgets || []).find(x => x.name === 'selection_state');
  const panel = document.querySelector('.tp-master');
  const grid = document.querySelector('.tp-grid');
  const chips = document.querySelectorAll('.tp-tag').length;
  const cats = document.querySelectorAll('.tp-cat').length;
  const styleEl = document.getElementById('taglib-panel-style');
  const styleLen = styleEl ? styleEl.textContent.length : 0;
  const menuCss = styleEl ? styleEl.textContent.includes('.tl-chip-menu') : false;
  const ghostCss = styleEl ? styleEl.textContent.includes('.tl-pin.ghost') : false;
  const selIsDom = !!(sel && sel.element);
  const errors = [];
  return JSON.stringify({widgets: w, selIsDom, hasPanel: !!panel, hasGrid: !!grid,
                         chips, cats, styleLen, menuCss, ghostCss, errors});
})()
"""))

# 5) 存档截图
shot = cmd("Page.captureScreenshot", {"format": "png"}, 15)
if shot.get("result", {}).get("data"):
    import base64
    with open("tests/v110_panel_fixed.png", "wb") as f:
        f.write(base64.b64decode(shot["result"]["data"]))
    print("screenshot saved: tests/v110_panel_fixed.png")
else:
    print("screenshot FAIL")
