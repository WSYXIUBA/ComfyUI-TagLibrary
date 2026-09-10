"""保存/重开 循环测试 v2: 短超时 + 无限循环重试。"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab(sub):
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and sub in t["url"]]
    return tabs[0] if tabs else None


mid = [9000]


def run(expr, to=30):
    for attempt in range(3):
        tab = find_tab("v12official")
        if not tab:
            time.sleep(3)
            continue
        try:
            ws = create_connection(tab["webSocketDebuggerUrl"], timeout=8, suppress_origin=True)
        except Exception:
            time.sleep(3)
            continue
        try:
            mid[0] += 1
            ws.settimeout(to)
            ws.send(json.dumps({"id": mid[0], "method": "Runtime.evaluate",
                                "params": {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True}}))
            deadline = time.time() + to
            done = False
            while time.time() < deadline and not done:
                try:
                    ws.settimeout(3)
                    x = json.loads(ws.recv())
                except Exception:
                    continue
                if isinstance(x, dict) and x.get("id") == mid[0]:
                    rr = x.get("result", {})
                    if "exceptionDetails" in rr:
                        return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:200]
                    return rr["result"].get("value")
            return "TIMEOUT"
        finally:
            try:
                ws.close()
            except Exception:
                pass
    return "ws-failed"


print("step1:", run("""
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
  await new Promise(r=>setTimeout(r,1500));
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
  const data = node.serialize();
  window.__saved = data.widgets_values;
  return JSON.stringify(window.__saved);
})()
""", to=12))
