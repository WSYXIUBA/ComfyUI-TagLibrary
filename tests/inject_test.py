"""CDP 注入测试: fixed 定位顶栏按钮 (绕开 bash 模板字符串转义)"""
import json
import sys
from websocket import create_connection  # noqa: E402


def main():
    import urllib.request
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5).read())
    tab = [t for t in tabs if "v21bar" in t.get("url", "")][0]
    ws = create_connection(tab["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)

    js = (
        "(() => {"
        "document.getElementById('taglib-topbar-btn')?.remove();"
        "const btn = document.createElement('button');"
        "btn.id='taglib-topbar-btn';"
        "btn.textContent='🏷';"
        "btn.title='标签库管理页';"
        "btn.style.cssText='position:fixed;z-index:99999;top:10px;right:64px;padding:4px 10px;"
        "border-radius:8px;border:1px solid rgba(128,140,160,.4);"
        "background:rgba(28,30,38,.92);color:#e3e7ee;cursor:pointer;font-size:13px;';"
        "btn.onclick=()=>{};"
        "document.body.appendChild(btn);"
        "const r=btn.getBoundingClientRect();"
        "return JSON.stringify({fixed:true,top:Math.round(r.top),w:Math.round(r.width)});"
        "})()"
    )
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": js, "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 1:
            print(msg["result"]["result"]["value"])
            break
    ws.close()


if __name__ == "__main__":
    main()
