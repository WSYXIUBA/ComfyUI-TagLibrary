"""CDP 直连评估工具: 对调试 Edge 的某个标签页执行 JS 或截图。

用法:
  python cdp_eval.py <url子串> "<js表达式>"
  python cdp_eval.py <url子串> --shot 输出.png
"""

import base64
import json
import sys
import urllib.request

from websocket import create_connection


def find_tab(sub: str) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = json.loads(r.read())
    pages = [t for t in tabs if t.get("type") == "page"]
    # 精确优先, 再模糊
    for t in pages:
        if sub == t.get("url"):
            return t
    for t in pages:
        if sub in t.get("url", ""):
            return t
    raise SystemExit(f"no tab matching {sub!r}; have: {[t.get('url') for t in pages]}")


def main() -> None:
    sub = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else None

    tab = find_tab(sub)
    ws = create_connection(tab["webSocketDebuggerUrl"], timeout=20,
                           suppress_origin=True)  # Chromium 403 拒绝带 Origin 的握手
    state = {"id": 0}

    def cmd(method: str, params: dict | None = None) -> dict:
        state["id"] += 1
        mid = state["id"]
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                return msg

    cmd("Runtime.enable")

    if action == "--shot":
        out = sys.argv[3] if len(sys.argv) > 3 else "shot.png"
        w = int(sys.argv[4]) if len(sys.argv) > 4 else 1500
        h = int(sys.argv[5]) if len(sys.argv) > 5 else 950
        cmd("Emulation.setDeviceMetricsOverride",
            {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        import time
        time.sleep(0.6)
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open(out, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print(f"saved {out}")
        ws.close()
        return

    expr = action or sys.stdin.read()
    r = cmd("Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {}).get("result", {})
    if "exceptionDetails" in r["result"]:
        exc = r["result"]["exceptionDetails"].get("exception", {})
        print("EXCEPTION:", str(exc.get("description") or exc.get("value"))[:600])
    else:
        val = res.get("value")
        if isinstance(val, str):
            print(val)
        else:
            print(json.dumps(val, ensure_ascii=False, indent=1))
    ws.close()


if __name__ == "__main__":
    main()
