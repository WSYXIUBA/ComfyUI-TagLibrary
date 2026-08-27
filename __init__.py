"""ComfyUI-TagLibrary: 结构化标签库节点。

多分类标签库 + 节点内选签小面板 + 独立管理页 (/taglib)。
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .api import register_routes

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS",
           "WEB_DIRECTORY", "register_routes"]

try:  # ComfyUI 启动时加载; 独立测试时容忍缺 server 模块
    register_routes()
except Exception as _exc:  # noqa: BLE001
    print(f"[ComfyUI-TagLibrary] 路由注册延迟/失败 (独立导入时属正常): {_exc}")
