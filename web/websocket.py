"""
WebSocket / SSE 实时推送模块

使用 Server-Sent Events (SSE) 模拟 WebSocket 功能。
纯 Python 标准库实现，无需外部依赖。

架构:
  SSEHandler   — HTTP 处理器，保持长连接推送事件
  Broadcast    — 全局广播器，管理所有连接客户端
  MessageBus   — 消息总线，连接后端状态变更到前端
"""

import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("pjsk.web.ws")

# ── 消息类型常量 ──
MSG_STATUS = "status"       # 状态更新
MSG_FRAME = "frame"         # 帧画面
MSG_LOG = "log"             # 日志
MSG_STATS = "stats"         # 性能统计
MSG_CONFIG = "config"       # 配置更新
MSG_COMMAND = "command"     # 命令响应

# ═══════════════════════════════════════════════════
# 消息总线 (发布-订阅)
# ═══════════════════════════════════════════════════


class MessageBus:
    """线程安全的消息总线，后端代码通过它推送消息给所有 SSE 客户端。"""

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """注册一个新的订阅者队列。"""
        q = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """移除订阅者。"""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: str, data: Any):
        """向所有订阅者推送消息。"""
        msg = json.dumps({"event": event, "data": data, "ts": time.time()},
                         ensure_ascii=False)
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


# 全局消息总线实例
bus = MessageBus()


# ═══════════════════════════════════════════════════
# SSE 处理器 (用于 http.server 的 do_GET)
# ═══════════════════════════════════════════════════


class SSEHandler:
    """
    SSE (Server-Sent Events) 处理器。
    用法: 在 HTTP handler 的 do_GET 中调用 handle_sse(self)。

    客户端通过 EventSource('/events') 连接。
    """

    SSE_RESPONSE_HEADERS = [
        ("Content-Type", "text/event-stream"),
        ("Cache-Control", "no-cache"),
        ("Connection", "keep-alive"),
        ("Access-Control-Allow-Origin", "*"),
        ("X-Accel-Buffering", "no"),
    ]

    _connections: list[queue.Queue] = []
    _lock = threading.Lock()

    # 连接生命周期回调
    on_connect: Optional[Callable] = None
    on_disconnect: Optional[Callable] = None

    @classmethod
    def handle_sse(cls, handler) -> None:
        """
        处理 SSE 连接请求。
        handler: BaseHTTPRequestHandler 实例
        """
        q = queue.Queue(maxsize=512)

        with cls._lock:
            cls._connections.append(q)

        # 发送 SSE 响应头
        handler.send_response(200)
        for header_name, header_value in cls.SSE_RESPONSE_HEADERS:
            handler.send_header(header_name, header_value)
        handler.end_headers()

        # 发送初始连接事件
        init_msg = json.dumps({
            "event": "connected",
            "data": {"status": "ok", "ts": time.time()},
        }, ensure_ascii=False)
        try:
            handler.wfile.write(f"data: {init_msg}\n\n".encode())
            handler.wfile.flush()
        except Exception:
            with cls._lock:
                if q in cls._connections:
                    cls._connections.remove(q)
            return

        if cls.on_connect:
            try:
                cls.on_connect()
            except Exception:
                pass

        logger.info("SSE client connected (%d total)", len(cls._connections))

        try:
            # 保持连接，等待消息
            while True:
                try:
                    msg = q.get(timeout=30)
                    # SSE 格式: data: <json>\n\n
                    handler.wfile.write(f"data: {msg}\n\n".encode())
                    handler.wfile.flush()
                except queue.Empty:
                    # 发送心跳保持连接
                    handler.wfile.write(b": heartbeat\n\n")
                    handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as e:
            logger.debug("SSE client error: %s", e)
        finally:
            with cls._lock:
                if q in cls._connections:
                    cls._connections.remove(q)
            if cls.on_disconnect:
                try:
                    cls.on_disconnect()
                except Exception:
                    pass
            logger.info("SSE client disconnected (%d remaining)",
                        len(cls._connections))

    @classmethod
    def broadcast(cls, event: str, data: Any):
        """
        向所有连接的 SSE 客户端广播消息。
        这是全局广播方法，不依赖于 MessageBus。
        """
        msg = json.dumps({"event": event, "data": data, "ts": time.time()},
                         ensure_ascii=False)
        dead = []
        with cls._lock:
            for q in cls._connections:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    cls._connections.remove(q)
                except ValueError:
                    pass

    @classmethod
    @property
    def client_count(cls) -> int:
        with cls._lock:
            return len(cls._connections)


# ═══════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════


def push_status(status: dict):
    """向所有客户端推送状态更新。"""
    SSEHandler.broadcast(MSG_STATUS, status)
    bus.publish(MSG_STATUS, status)


def push_frame(b64_image: str, width: int = 0, height: int = 0):
    """向所有客户端推送帧画面 (base64 JPEG)。"""
    SSEHandler.broadcast(MSG_FRAME, {
        "image": b64_image,
        "w": width,
        "h": height,
    })


def push_log(message: str, level: str = "info"):
    """向所有客户端推送日志。"""
    SSEHandler.broadcast(MSG_LOG, {
        "message": message,
        "level": level,
        "ts": time.strftime("%H:%M:%S"),
    })


def push_stats(stats: dict):
    """向所有客户端推送性能统计。"""
    SSEHandler.broadcast(MSG_STATS, stats)


def push_config(config_text: str):
    """向所有客户端推送配置内容。"""
    SSEHandler.broadcast(MSG_CONFIG, {
        "content": config_text,
    })
