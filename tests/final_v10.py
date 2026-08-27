"""最终验证: 宽度不凸出 + 排除类目 UI + 状态保存。"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab(sub):
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and sub in t["url"]]
    return tabs[0] if tabs else None


def new_tab(url):
    req = urllib.request.Request(
        f"http://127.0.0.1:9222/json/new?url={url}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


def bind_and_build():
    """绑定 app 并放一个标签库节点。"""
    code = """
(async () => {
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
  }
  if (!window.app?.graph) return 'no app';
  await window.app.graph.clear();
  const node = LiteGraph.createNode('TagLibraryNode');
  if (!node) return 'ext not ready';
  node.pos=[80,80]; node.size=[470,720];
  window.app.graph.add(node);
  await new Promise(r=>setTimeout(r,2000));
  // 预置: 加 hair 类相关 + smile 标签, 模拟上游 roxy 提示词场景
  const n = window.app.graph._nodes[0];
  const sw = n.widgets.find(w=>w.name==='selection_state');
  const st = JSON.parse(sw.value);
  st.tags = [
    {en:'closed mouth', zh:'闭嘴', enabled:true},
    {en:'light smile', zh:'浅笑', enabled:true},
    {en:'blue hair', zh:'蓝发', enabled:true},
    {en:'blue eyes', zh:'蓝眼', enabled:true},
    {en:'sitting', zh:'坐', enabled:true},
  ];
  sw.value = JSON.stringify(st);
  await n._taglibPanelApi.refresh();
  return 'ready';
})()
"""
    return run(code)


def run(expr, to=25):
    tab = None
    for sub in ("v10final", "v10f"):
        tab = find_tab(sub)
        if tab:
            break
    if not tab:
        # 用 json/new 开页再 CDP 导航 (Edge 会吞 url 参数)
        new_tab("http://127.0.0.1:9222/json/placeholder")
        time.sleep(2)
        with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
            tabs = [t for t in json.loads(r.read()) if t.get("type") == "page"]
        blank = next((t for t in tabs if t["url"] in ("about:blank", "http://127.0.0.1:9222/json/placeholder")), None)
        if blank:
            ws0 = create_connection(blank["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
            ws0.send(json.dumps({"id": 1, "method": "Page.navigate",
                                 "params": {"url": "http://127.0.0.1:8188/?v10final"}}))
            time.sleep(1)
            ws0.close()
        time.sleep(18)
        tab = find_tab("v10final")
    ws = create_connection(tab["webSocketDebuggerUrl"], timeout=to, suppress_origin=True)
    mid = [7000]
    mid[0] += 1
    ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": True}}))
    deadline = time.time() + to
    result = "TIMEOUT"
    while time.time() < deadline:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]:
                rr = x.get("result", {})
                if "exceptionDetails" in rr:
                    result = "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:150]
                else:
                    result = rr["result"].get("value")
                break
        except Exception:
            continue
    ws.close()
    return result


print("step1 build:", bind_and_build())

# 宽度跟随测试: 缩节点宽度到 300, 面板应≤300 (不凸出)
r = run("""
(async () => {
  const n = window.app.graph._nodes[0];
  n.size[0] = 300;
  window.app.canvas.setDirty(true,true);
  await new Promise(r=>setTimeout(r,500));
  const pr = document.querySelector('.taglib-panel').getBoundingClientRect();
  return JSON.stringify({nodeW: n.size[0], panelScreenW: Math.round(pr.width),
    zoom: Math.round(window.app.canvas.ds.scale*100)/100});
})()
""")
print("width test:", r)

# 排除类目: 模拟 selection_state 写入 exclude_categories -> 面板预览更新
r = run("""
(async () => {
  const n = window.app.graph._nodes[0];
  const sw = n.widgets.find(w=>w.name==='selection_state');
  const st = JSON.parse(sw.value);
  st.exclude_categories = ['头发', '人物特征'];
  sw.value = JSON.stringify(st);
  await n._taglibPanelApi.refresh();
  await new Promise(r=>setTimeout(r,400));
  const preview = document.querySelector('.tl-preview').textContent;
  return JSON.stringify({preview: preview.slice(0,60),
    blueHairGone: !preview.includes('blue hair'),
    blueEyesGone: !preview.includes('blue eyes')});
})()
""")
print("exclude test:", r)

# 排除类目随工作流序列化
r = run("""
JSON.stringify({
  hasExclude: JSON.parse(window.app.graph._nodes[0].widgets.find(w=>w.name==='selection_state').value).exclude_categories})
""")
print("serialized:", r)
