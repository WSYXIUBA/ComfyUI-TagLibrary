"""检查 chip_font_size / chip_radius 设置值。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v8zh" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=12, suppress_origin=True)
mid = [3300]


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
                    return "EXC:" + str(rr["exceptionDetails"]["exception"].get("description", ""))[:150]
                return json.dumps(rr["result"].get("value"))
        except Exception:
            continue
    return "TIMEOUT"


print(cmd("""
(async () => {
  const g = window.app.extensionManager.setting;
  const fs = await g.get('zhixin.TagLibrary.chip_font_size');
  const rad = await g.get('zhixin.TagLibrary.chip_radius');
  const scale = await g.get('zhixin.TagLibrary.chip_scale');
  return JSON.stringify({fs, rad, scale});
})()
"""))
ws.close()
