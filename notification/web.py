#!/usr/bin/env python3
"""
PJSK Auto Player — Web 推送通知

通过 WebSocket 向连接的 Web 客户端推送通知，
并支持浏览器原生 toast 通知 (通过 Service Worker).

用法:
    # 作为独立通知器
    from notification.web import WebNotifier
    wn = WebNotifier(ws_server="ws://localhost:8080")
    wn.notify(title="PJSK", message="打歌完成！")

    # 集成到 WebSocket 服务器
    from notification.web import WebNotifier
    wn = WebNotifier()
    wn.register_websocket(websocket)
    wn.broadcast("打歌完成！", "PJSK")
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger("pjsk.notification.web")


@dataclass
class NotificationPayload:
    """通知数据载荷。"""
    type: str = "notification"          # 消息类型
    id: str = ""                         # 唯一 ID
    title: str = ""                      # 标题
    message: str = ""                    # 正文
    level: str = "info"                  # info / success / warning / error
    timestamp: float = 0.0               # Unix 时间戳
    data: dict = field(default_factory=dict)  # 附加数据


class WebNotifier:
    """
    Web 推送通知器。

    通过 WebSocket 向已连接的客户端推送通知。
    支持浏览器原生 toast 和 Web 控制面板内通知。

    参数:
        ws_server: WebSocket 服务器地址 (可选，用于初始配置)
    """

    def __init__(self, ws_server: Optional[str] = None):
        self._ws_server = ws_server
        self._websockets: list = []       # 已连接的 WebSocket 对象列表
        self._lock = threading.Lock()
        self._notification_id = 0
        self._history: list[NotificationPayload] = []  # 通知历史
        self._max_history = 100

    # ── 连接管理 ─────────────────────────────────────────────

    def register_websocket(self, ws: Any) -> None:
        """
        注册一个 WebSocket 连接以接收通知。

        参数:
            ws: WebSocket 对象 (需支持 ws.send() / ws.close() 方法)
        """
        with self._lock:
            if ws not in self._websockets:
                self._websockets.append(ws)
                logger.debug(f"WebSocket 注册: {id(ws)}")

    def unregister_websocket(self, ws: Any) -> None:
        """
        注销一个 WebSocket 连接。

        参数:
            ws: 之前注册的 WebSocket 对象
        """
        with self._lock:
            if ws in self._websockets:
                self._websockets.remove(ws)
                logger.debug(f"WebSocket 注销: {id(ws)}")

    @property
    def connected_count(self) -> int:
        """当前连接的客户端数量。"""
        with self._lock:
            return len(self._websockets)

    # ── 发送通知 ─────────────────────────────────────────────

    def notify(
        self,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[dict] = None,
        broadcast: bool = True,
    ) -> NotificationPayload:
        """
        发送一条通知。

        参数:
            title: 通知标题
            message: 通知正文
            level: 级别 (info / success / warning / error)
            data: 附加数据 (可选)
            broadcast: 是否广播到所有 WebSocket 客户端

        返回:
            NotificationPayload: 已发送的通知对象
        """
        self._notification_id += 1
        payload = NotificationPayload(
            type="notification",
            id=f"notif_{self._notification_id}_{int(time.time())}",
            title=title,
            message=message,
            level=level,
            timestamp=time.time(),
            data=data or {},
        )

        # 保存到历史
        self._add_history(payload)

        # 广播
        if broadcast:
            sent = self._broadcast(payload)
            if sent == 0:
                logger.debug(f"通知已排队 (无连接客户端): {title}")
            else:
                logger.debug(f"通知已发送到 {sent} 个客户端: {title}")

        return payload

    def notify_success(self, title: str, message: str, **kwargs) -> NotificationPayload:
        """发送成功通知。"""
        return self.notify(title, message, level="success", **kwargs)

    def notify_warning(self, title: str, message: str, **kwargs) -> NotificationPayload:
        """发送警告通知。"""
        return self.notify(title, message, level="warning", **kwargs)

    def notify_error(self, title: str, message: str, **kwargs) -> NotificationPayload:
        """发送错误通知。"""
        return self.notify(title, message, level="error", **kwargs)

    # ── 历史管理 ─────────────────────────────────────────────

    def _add_history(self, payload: NotificationPayload):
        """保存通知到历史记录。"""
        with self._lock:
            self._history.append(payload)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def get_history(
        self,
        limit: int = 50,
        since: Optional[float] = None,
        level: Optional[str] = None,
    ) -> list[NotificationPayload]:
        """
        获取历史通知。

        参数:
            limit: 最大返回条数
            since: 只返回此时间戳之后的通知
            level: 按级别筛选

        返回:
            list[NotificationPayload]: 符合条件的通知列表
        """
        with self._lock:
            results = list(self._history)

        # 筛选
        if since:
            results = [n for n in results if n.timestamp >= since]
        if level:
            results = [n for n in results if n.level == level]

        return results[-limit:]

    def clear_history(self):
        """清空通知历史。"""
        with self._lock:
            self._history.clear()
        logger.debug("通知历史已清空")

    # ── 内部广播 ─────────────────────────────────────────────

    def _broadcast(self, payload: NotificationPayload) -> int:
        """
        广播通知到所有已注册的 WebSocket。

        返回:
            int: 成功接收的客户端数量
        """
        payload_dict = asdict(payload)
        message = json.dumps(payload_dict, ensure_ascii=False)

        sent_count = 0
        dead_connections = []

        with self._lock:
            for ws in self._websockets:
                try:
                    ws.send(message)
                    sent_count += 1
                except Exception as e:
                    logger.debug(f"WebSocket 发送失败 (移除): {e}")
                    dead_connections.append(ws)

            # 清理断开的连接
            for ws in dead_connections:
                self._websockets.remove(ws)

        return sent_count

    # ── 浏览器 toast 支持 ────────────────────────────────────

    @staticmethod
    def generate_browser_toast_script(
        title: str,
        message: str,
        icon: Optional[str] = None,
        click_url: Optional[str] = None,
    ) -> str:
        """
        生成浏览器 Service Worker toast 通知的 JavaScript 代码片段。

        可以在服务端渲染时嵌入 HTML，或通过 WebSocket 发送
        让客户端执行。

        参数:
            title: 通知标题
            message: 通知正文
            icon: 图标 URL (可选)
            click_url: 点击通知时跳转的 URL (可选)

        返回:
            str: JavaScript 代码
        """
        options = {
            "body": message,
            "requireInteraction": True,
        }
        if icon:
            options["icon"] = icon

        click_handler = ""
        if click_url:
            click_handler = (
                f"  notification.onclick = function() {{\n"
                f"    window.open('{click_url}', '_blank');\n"
                f"    notification.close();\n"
                f"  }};\n"
            )

        script = (
            f"// PJSK Auto Player — 浏览器 Toast 通知\n"
            f"if ('Notification' in window) {{\n"
            f"  if (Notification.permission === 'granted') {{\n"
            f"    var notification = new Notification(\n"
            f"      '{title}',\n"
            f"      {json.dumps(options, ensure_ascii=False)}\n"
            f"    );\n"
            f"{click_handler}"
            f"  }} else if (Notification.permission !== 'denied') {{\n"
            f"    Notification.requestPermission().then(function(permission) {{\n"
            f"      if (permission === 'granted') {{\n"
            f"        new Notification('{title}', {json.dumps(options, ensure_ascii=False)});\n"
            f"      }}\n"
            f"    }});\n"
            f"  }}\n"
            f"}}\n"
        )
        return script

    # ── WS 服务器集成辅助 ────────────────────────────────────

    @staticmethod
    def handle_ws_message(ws: Any, raw_message: str) -> Optional[dict]:
        """
        处理 WebSocket 接收到的通知相关消息。

        支持的客户端请求:
          - {"cmd": "get_history", "limit": 50}
          - {"cmd": "clear_history"}
          - {"cmd": "ping"}

        参数:
            ws: WebSocket 对象
            raw_message: 原始 JSON 字符串

        返回:
            dict 或 None: 需要回复的消息 (None = 无需回复)
        """
        try:
            msg = json.loads(raw_message)
        except json.JSONDecodeError:
            return None

        cmd = msg.get("cmd", "")
        if cmd == "ping":
            return {"type": "pong", "timestamp": time.time()}
        # 其他命令由外部处理
        return None


# ══════════════════════════════════════════════════════════════
#  快捷函数
# ══════════════════════════════════════════════════════════════

_default_web_notifier: Optional[WebNotifier] = None
_web_notifier_lock = threading.Lock()


def get_web_notifier() -> WebNotifier:
    """
    获取全局 WebNotifier 单例。

    用法:
        from notification.web import get_web_notifier
        wn = get_web_notifier()
        wn.notify("PJSK", "通知内容")
    """
    global _default_web_notifier
    with _web_notifier_lock:
        if _default_web_notifier is None:
            _default_web_notifier = WebNotifier()
        return _default_web_notifier


def notify_web(
    title: str,
    message: str,
    level: str = "info",
    **kwargs,
) -> NotificationPayload:
    """
    一键发送 Web 通知 (使用全局单例)。

    用法:
        from notification.web import notify_web
        notify_web("PJSK", "打歌完成！", level="success")
    """
    notifier = get_web_notifier()
    return notifier.notify(title, message, level=level, **kwargs)


# ── 自测 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    wn = WebNotifier()
    print(f"WebNotifier 就绪 (客户端数: {wn.connected_count})")

    # 发送测试通知
    p = wn.notify("PJSK Auto Player 测试", "这是 Web 通知测试消息", level="success")
    print(f"通知已发送: id={p.id}, title={p.title}")

    # 生成浏览器 toast 脚本
    script = WebNotifier.generate_browser_toast_script(
        "PJSK Auto Player",
        "打歌完成！点击查看详情",
        icon="/static/icon.png",
        click_url="http://localhost:8080/",
    )
    print(f"\n浏览器 Toast 脚本 ({len(script)} 字符):")
    print(script[:200] + "..." if len(script) > 200 else script)

    # 历史
    history = wn.get_history(limit=10)
    print(f"\n历史通知: {len(history)} 条")
