"""
PJSK Auto Player — Web GUI V2
现代暗色一站式控制面板

模块:
  app.py        HTTP + SSE 服务器 (基于 http.server 标准库)
  websocket.py  SSE 实时推送 + 广播
  dashboard.html 单页前端 (内联 CSS + JS)
"""

from .app import WebApp

__all__ = ["WebApp"]
