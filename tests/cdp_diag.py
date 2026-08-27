"""一次性诊断: 监听导航到 /taglib 的网络事件, 打印主文档响应头。"""

import json
import sys
import time
import urllib.request

from websocket import create_connection

TARGET_URL = "http://127.0.0.1:8188/taglib"


def find_tab(sub: str) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = json.loads(r.read())
    for t in tabs:
        if t.get("type") == "page" and sub in t.get("url", ""):
            return t
    raise SystemExit(f"no tab {sub!r}")


tab = find_tab(sys.argv[1] if len(sys.argv) > 1 else "8188")
ws = create_connection(tab["webSocketDebuggerUrl"], timeout=25, suppress_origin=True)
mid = [0]


def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid[0]:
            if "error" in m:
                print("cmd error:", m["error"])
            return m
        # 收集事件
        if m.get("method") == "Network.responseReceived":
            resp = m["params"]["response"]
            if "/taglib" in resp.get("url", ""):
                print(f"\n== response {resp['status']} {resp['url']}")
                print("   headers:", json.dumps(resp.get("headers", {}), indent=1)[:800])


cmd("Network.enable")
cmd("Page.enable")
r = cmd("Page.navigate", {"url": TARGET_URL})
print("navigate result:", r.get("result"))
time.sleep(6)
r = cmd("Runtime.evaluate", {"expression": "document.body ? document.body.innerText.slice(0,200) : 'no body'",
                             "returnByValue": True})
print("\nbody:", r["result"]["result"].get("value"))
ws.close()
