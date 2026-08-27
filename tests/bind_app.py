"""检查 v7i18n 页面的 app 绑定 (loadGraphData 路径)。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v7i18n" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
mid = [1800]


def cmd(expr, to=14):
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
                return json.dumps(r["result"].get("value"))
        except Exception:
            continue
    return "TIMEOUT"


print(cmd("""
(async () => {
  const paths = ['/scripts/app.js', '/assets/index-Chvz2wUd.js'];
  for (const p of paths) {
    try {
      const m = await import(p);
      if (m && m.app) { window.app = m.app; return JSON.stringify({bound: p, hasGraph: !!m.app.graph}); }
      if (m) return JSON.stringify({p, keys: Object.keys(m).slice(0, 12)});
    } catch (e) { continue; }
  }
  return 'all failed';
})()
"""))
ws.close()
