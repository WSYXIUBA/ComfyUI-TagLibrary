"""逐个 tab 巡检详细界面: 挑标签/排除类目/标签库管理/防冲突关系/设置 (+新加的3个)。"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cdp_eval import find_tab  # noqa
from websocket import create_connection

ws_state = {"id": 0}
ws = create_connection(find_tab("127.0.0.1:8188")["webSocketDebuggerUrl"],
                       timeout=30, suppress_origin=True)

def ev(expr):
    ws_state["id"] += 1
    ws.send(json.dumps({"id": ws_state["id"], "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == ws_state["id"]:
            r = m.get("result", {}).get("result", {})
            return r.get("value", r.get("description", "<?>"))

# 打开 picker
print(ev("""(() => {
  const node = window.app.graph._nodes.find(n=>n.type==='TagLibraryNode');
  const holder = node.widgets.find(w=>w.name==='taglib_panel').element;
  const dlg = holder.closest('body') && document.querySelector('.taglib-picker-host, .tp-wrap');
  // 若已开就直接用, 否则点按钮开
  const btn=[...holder.querySelectorAll('button')].find(b=>/添加标签/.test(b.textContent));
  if (!document.querySelector('.tp-wrap')) btn.click();
  return 'ok';
})()"""))

import time; time.sleep(1.5)

TABS = [("挑标签", ".tp-picktab"), ("排除类目", ".tp-excludetab"),
        ("标签库管理", ".tp-mgrtab"), ("防冲突关系", ".tp-cftab"),
        ("设置", ".tp-settab"), ("武器档案(新)", ".tp-proftab"),
        ("互斥域(新)", ".tp-grptab"), ("NL句式(新)", ".tp-nltab")]

for name, sel in TABS:
    print("\n" + "=" * 70)
    print(f"### TAB {name}")
    out = ev(f"""(() => {{
      const b = document.querySelector('{sel}');
      if (!b) return 'NO-BTN';
      b.click();
      return 1;
    }})()""")
    if out != 1:
        print("  按钮缺失:", out)
        continue
    time.sleep(1.2)
    body = ev("""(() => {
      const cols = document.querySelector('.tp-cols');
      const vis = [...cols.children].filter(e => e.offsetHeight > 0 && getComputedStyle(e).display !== 'none');
      const parts = [];
      for (const v of vis) {
        parts.push('--- ' + v.className + ' ---\\n' + v.innerText.slice(0, 700));
      }
      const foot = document.querySelector('.tp-foot');
      return parts.join('\\n') + '\\n[foot] ' + (foot ? foot.innerText.replace(/\\n+/g,' | ').slice(0,160) : '?');
    })()""")
    print(body)
ws.close()
