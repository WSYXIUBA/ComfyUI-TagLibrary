"""通过 DOM 真实点击节点搜索面板添加 TagLibraryNode (用户路径)。"""

import json
import time
import urllib.request

from websocket import create_connection

with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
    tabs = [t for t in json.loads(r.read()) if t.get("type") == "page" and "v7i18n" in t["url"]]

ws = create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=12, suppress_origin=True)
mid = [2600]


def cmd(m, p=None, to=10):
    mid[0] += 1
    ws.settimeout(to)
    ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))
    deadline = time.time() + to
    while time.time() < deadline:
        try:
            x = json.loads(ws.recv())
            if x.get("id") == mid[0]:
                return x
        except Exception:
            continue
    return {}


def ev(expr, to=10):
    x = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                 "awaitPromise": True}, to)
    r = x.get("result", {}).get("result", {})
    if r.get("subtype") == "error":
        return "ERR:" + str(r.get("description", ""))[:100]
    return json.dumps(r.get("value"))


# 1) 绑定 app (canvas 反查)
print(ev("""
(() => {
  if (window.app && window.app.graph) return 'already';
  const cv = document.querySelector('canvas');
  for (const k of Object.getOwnPropertyNames(cv||{})) {
    try { if (cv[k] && cv[k].graph) { window.app = cv[k]; return 'bound'; } } catch {}
  }
  return 'nf';
})()
"""))

# 2) ComfyUI 搜索框: Ctrl+A 后按住键盘? 官方快捷键是双击画布或 Ctrl+M?
# 用 sidebar 的节点库: 点击左侧栏'节点'图标 -> 搜索
ev("""
(() => {
  // 侧栏按钮 data tooltip='Nodes'
  const btns=[...document.querySelectorAll('button,[role="button"]')];
  const nb=btns.find(b=>(b.title||b.getAttribute('data-tooltip')||'').match(/node/i));
  if (nb) { nb.click(); return 'clicked node lib'; }
  return 'no node lib btn';
})()
""")
time.sleep(1.5)

# 3) 在节点库搜索框输入 taglibrary
print(ev("""
(() => {
  const inp=[...document.querySelectorAll('input')].find(i=>i.offsetParent && !i.disabled);
  if (!inp) return 'no visible input';
  inp.focus();
  return 'focused:' + (inp.placeholder||'').slice(0,20);
})()
"""))
cmd("Input.insertText", {"text": "TagLibrary"})
time.sleep(1.5)

# 4) 找搜索结果里的 TagLibraryNode 条目并双击/拖入
print(ev("""
(() => {
  const items=[...document.querySelectorAll('[class*=result],[class*=item],[class*=entry]')]
    .filter(e=>e.offsetParent && e.textContent.includes('TagLibrary'));
  if (!items.length) return 'no results';
  items[0].click();
  return 'clicked: '+items[0].textContent.slice(0,40);
})()
"""))
time.sleep(2)

print(ev("""JSON.stringify({nodes: window.app.graph._nodes.map(n=>n.type)})"""))
ws.close()
