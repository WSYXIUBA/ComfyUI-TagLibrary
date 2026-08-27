"""reload 后读取比例设置的实际生效值。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v8zh" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=12, suppress_origin=True)
mid = [3500]


def cmd(expr, to=12):
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
                    return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:120]
                return json.dumps(rr["result"].get("value"))
        except Exception:
            continue
    return "TIMEOUT"


time.sleep(3)
print(cmd("""
(() => {
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
  }
  const panel = document.querySelector('.taglib-panel');
  return JSON.stringify({inlineFS: panel?.style.fontSize,
    scaleVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-scale'),
    radiusVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-radius')});
})()
"""))
ws.close()
