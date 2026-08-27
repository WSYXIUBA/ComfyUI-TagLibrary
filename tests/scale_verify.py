"""比例设置验证 (resilient: 兼容 tab 冻结, 用较短超时重试)。"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v8zh" in t["url"]]
    return tabs[0] if tabs else None


def cmd(ws, mid_box, expr, to=8):
    mid_box[0] += 1
    ws.settimeout(to)
    ws.send(json.dumps({"id": mid_box[0], "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True}}))
    deadline = time.time() + to
    while time.time() < deadline:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid_box[0]:
                rr = x.get("result", {})
                if "exceptionDetails" in rr:
                    return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:120]
                return rr["result"].get("value")
        except websocket_timeout:
            return "TIMEOUT"
        except Exception:
            continue
    return "TIMEOUT"


class websocket_timeout(Exception):
    pass


tab = find_tab()
ws = create_connection(tab["webSocketDebuggerUrl"], timeout=8, suppress_origin=True)
mid = [4000]

r = cmd(ws, mid, """
(() => {
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
  }
  const panel = document.querySelector('.taglib-panel');
  return JSON.stringify({panelReady: !!panel,
    inlineFS: panel ? panel.style.fontSize : null,
    scaleVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-scale').trim(),
    radiusVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-radius').trim(),
    fontVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-font').trim()});
})()
""")
print("state:", r)
ws.close()
