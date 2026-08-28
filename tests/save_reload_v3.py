"""保存/重开保真测试 v3: 通过拖拽 workflow JSON 进 app.loadGraphData 完整走用户路径。

页面 reload 后扩展重新注册, 用 app.loadGraphData 加载一个最小工作流
(等价于用户打开保存的 json 文件), 然后 configure 后读参数值。
"""

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
    for _ in range(3):
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
            ws.settimeout(3)
            deadline = time.time() + to
            while time.time() < deadline:
                try:
                    x = json.loads(ws.recv())
                except Exception:
                    if time.time() > deadline:
                        break
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


# ---- 用 app.loadGraphData 加载"保存过的工作流" (widgets_values 是老错位工作流重构后的正确顺序)
WF = {
    "last_node_id": 1,
    "last_link_id": 0,
    "nodes": [{
        "id": 1, "type": "TagLibraryNode", "pos": [80, 80], "size": [320, 518],
        "flags": {}, "order": 0, "mode": 0,
        "inputs": [], "outputs": [], "properties": {},
        "widgets_values": ["{}", "random_mix", 777, "randomize", "only", 5, 12, "{}", "", "space", True, False, False]
    }],
    "links": [],
    "groups": [],
    "config": {},
    "extra": {},
    "version": 0.4,
}

print("load:", run(f"""
(async () => {{
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{{}})) {{
    try {{ if (cv[k] && cv[k].graph) {{ window.app = cv[k]; break; }} }} catch {{}}
  }}
  if (!window.app?.graph) return 'noapp';
  const wf = {json.dumps(WF)};
  await window.app.loadGraphData(wf);
  await new Promise(r=>setTimeout(r,2000));
  const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
  if (!n) return 'no node after load';
  const get = (name) => {{ const w = n.widgets.find(x=>x.name===name); return w ? String(w.value) : 'MISSING'; }};
  return JSON.stringify({{mode:get('mode'), nsfw:get('nsfw_mode'), min:get('min_tags'), max:get('max_tags'),
    sep:get('separator'), w:get('use_weights_syntax'), d:get('dedupe'), p:get('pinned_required'), seed:get('seed')}});
}})()
""", to=25))

print("expect: mode=random_mix nsfw=only min=5 max=12 sep=space w=true d=false p=false seed=777")
