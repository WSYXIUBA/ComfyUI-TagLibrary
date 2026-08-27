"""验证比例设置端到端: 读取真实设置 -> 改值 -> refresh -> 字体变化。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v8zh" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=12, suppress_origin=True)
mid = [3000]


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
                r = x.get("result", {})
                if "exceptionDetails" in r:
                    return "EXC:" + str(r["exceptionDetails"]["exception"].get("description", ""))[:120]
                return r["result"].get("value")
        except Exception:
            continue
    return "TIMEOUT"


def js(v):
    return json.dumps(v)


# 当前比例设置值
print("current:", cmd(f"""
(async () => {{
  const g = window.app.extensionManager.setting;
  return JSON.stringify({{
    scale: await g.get('zhixin.TagLibrary.chip_scale'),
  }});
}})()
"""))

# 改成 140%
cmd(f"""
(async () => {{
  const panel = document.querySelector('.taglib-panel');
  localStorage.setItem('taglib.zhixin.TagLibrary.chip_scale', '140');
  const n = window.app.graph._nodes[0];
  await n._taglibPanelApi.refresh();
  return 'refreshed';
}})()
""")
time.sleep(2)

r = cmd("""
JSON.stringify({
  fontSize: getComputedStyle(document.querySelector('.taglib-panel')).fontSize,
  chipVar: getComputedStyle(document.documentElement).getPropertyValue('--taglib-chip-font').trim()
})
""")
print("after set 140%:", r)
ws.close()
