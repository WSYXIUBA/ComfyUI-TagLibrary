"""保存/重开 循环测试: 参数必须原样保真 (不再错位)。"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab(sub):
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and sub in t["url"]]
    return tabs[0] if tabs else None


mid = [9000]


def run(expr, to=25):
    tab = find_tab("v12official")
    ws = create_connection(tab["webSocketDebuggerUrl"], timeout=to, suppress_origin=True)
    try:
        mid[0] += 1
        ws.settimeout(to)
        ws.send(json.dumps({"id": mid[0], "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True,
                                       "awaitPromise": True}}))
        deadline = time.time() + to
        while time.time() < deadline:
            try:
                x = json.loads(ws.recv())
                if x.get("id") == mid[0]:
                    rr = x.get("result", {})
                    if "exceptionDetails" in rr:
                        return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:200]
                    return rr["result"].get("value")
            except Exception:
                continue
        return "TIMEOUT"
    finally:
        ws.close()


# 第一步: 建节点, 设一组非默认参数, 拿到 serialize 前的值
print(run("""
(async () => {
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
  }
  if (!window.app?.graph) return 'noapp';
  await window.app.graph.clear();
  const node = LiteGraph.createNode('TagLibraryNode');
  node.pos=[80,80];
  window.app.graph.add(node);
  await new Promise(r=>setTimeout(r,2000));
  // 设非默认参数
  const set = (name, v) => { const w = node.widgets.find(x=>x.name===name); if (w) w.value = v; };
  set('mode', 'random_mix');
  set('nsfw_mode', 'only');
  set('min_tags', 5);
  set('max_tags', 12);
  set('separator', 'space');
  set('use_weights_syntax', true);
  set('dedupe', false);
  set('pinned_required', false);
  set('seed', 777);
  await new Promise(r=>setTimeout(r,300));
  // 序列化 (模拟保存工作流)
  const data = node.serialize();
  window.__saved = data.widgets_values;
  return JSON.stringify({saved: window.__saved});
})()
""", to=25))

time.sleep(1)

# 第二步: 清空画布, 用保存的数据 configure (模拟重开工作流)
print(run("""
(async () => {
  const node0 = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
  const saved = window.__saved;
  await window.app.graph.clear();
  const node = LiteGraph.createNode('TagLibraryNode');
  node.pos=[80,80];
  window.app.graph.add(node);
  await new Promise(r=>setTimeout(r,1800));
  node.configure({widgets_values: saved});
  await new Promise(r=>setTimeout(r,400));
  const get = (name) => { const w = node.widgets.find(x=>x.name===name); return w ? w.value : '(missing)'; };
  return JSON.stringify({
    mode: get('mode'), nsfw: get('nsfw_mode'), min: get('min_tags'), max: get('max_tags'),
    sep: get('separator'), weights: get('use_weights_syntax'), dedupe: get('dedupe'),
    pinned: get('pinned_required'), seed: get('seed')});
})()
""", to=25))
print("expect: mode=random_mix nsfw=only min=5 max=12 sep=space weights=true dedupe=false pinned=false seed=777")
