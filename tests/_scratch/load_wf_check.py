"""graph.configure 加载 TagLibraryNode 工作流并验证中文化 label。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v7i18n" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=12, suppress_origin=True)
mid = [2100]


def cmd(expr, to=10):
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
                r = x.get("result", {})
                if "exceptionDetails" in r:
                    return "EXC:" + str(r["exceptionDetails"]["exception"].get("description", ""))[:100]
                return json.dumps(r["result"].get("value"))
        except Exception:
            continue
    return "TIMEOUT"


WF = {
    "nodes": [{
        "id": 1, "type": "TagLibraryNode", "pos": [80, 80], "size": [470, 720],
        "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
        "properties": {"Node name for S&R": "TagLibraryNode"},
        "widgets_values": ['{}', 'manual', 0, 'off'],
    }],
    "links": [], "groups": [], "config": {}, "extra": {}, "version": 0.4,
}

cmd(f"window.__wf = {json.dumps(WF)}; 'set'")

r = cmd("""
(async () => {
  const g = window.app.graph;
  g.clear();
  try {
    await g.configure(window.__wf);
    return JSON.stringify({nodes: g._nodes.length,
      widgets: g._nodes[0]?.widgets?.length || 0,
      type: g._nodes[0]?.type});
  } catch (e) { return 'ERR:' + e.message.slice(0, 90); }
})()
""", to=12)
print("configure:", r)

time.sleep(2)
r2 = cmd("""
JSON.stringify({
  labels: app.graph._nodes[0]?.widgets?.filter(w=>w.label).map(w=>w.name+'->'+w.label),
  inLabels: app.graph._nodes[0]?.inputs?.map(i=>i.label||i.name).map(s=>s.slice(0,22)),
  outLabels: app.graph._nodes[0]?.outputs?.map(o=>o.label||o.name).map(s=>s.slice(0,26)),
  panelH: Math.round(document.querySelector('.taglib-panel')?.getBoundingClientRect().height||0)
})
""", to=10)
print("labels:", r2)
ws.close()
