"""
PJSK Auto Player — ALAS-style Resource 资源管理器。

跟踪所有加载的资源（模板图片、OCR 模型、cv2.VideoCapture 等），
支持一次性释放所有资源，避免内存泄漏。

用法:
    from lib.resource import Resource

    class MyTask(Resource):
        def __init__(self):
            super().__init__()
            # 注册资源
            self.resource_add('my_template')
            self.template = cv2.imread('template.png')

        def resource_release(self):
            # 子类重写来释放具体资源
            self.template = None
"""

from __future__ import annotations

import logging
import weakref
from typing import Any

logger = logging.getLogger("pjsk.resource")


class Resource:
    """资源管理基类。

    自动跟踪所有继承此类的实例，支持全局释放。
    """

    # 类级别注册表：{resource_key: weakref_to_resource_instance}
    _resources: dict[str, Any] = {}
    _resource_lock = __import__('threading').Lock()

    def __init__(self) -> None:
        self._resource_keys: set[str] = set()

    def resource_add(self, key: str) -> None:
        """注册一个资源键。

        Args:
            key: 资源唯一标识符。释放时据此查找资源。
        """
        with Resource._resource_lock:
            Resource._resources[key] = weakref.ref(self)
            self._resource_keys.add(key)
        logger.debug("Resource registered: %s", key)

    def resource_remove(self, key: str) -> None:
        """注销一个资源键。"""
        with Resource._resource_lock:
            Resource._resources.pop(key, None)
            self._resource_keys.discard(key)
        logger.debug("Resource removed: %s", key)

    def resource_release(self) -> None:
        """释放此实例持有的所有资源。

        子类应重写此方法来实现具体的资源释放逻辑，
        然后调用 super().resource_release()。
        """
        # 从全局注册表中清理
        with Resource._resource_lock:
            for key in list(self._resource_keys):
                if Resource._resources.get(key) is not None:
                    ref = Resource._resources[key]
                    if ref() is self or ref() is None:
                        Resource._resources.pop(key, None)
            self._resource_keys.clear()

    def __del__(self) -> None:
        """析构时自动清理资源注册表。"""
        try:
            self.resource_release()
        except Exception:
            pass

    @classmethod
    def release_all(cls) -> int:
        """释放所有已注册的资源实例。

        Returns:
            释放的实例数量。
        """
        count = 0
        with cls._resource_lock:
            for key, ref in list(cls._resources.items()):
                instance = ref()
                if instance is not None:
                    try:
                        instance.resource_release()
                        count += 1
                    except Exception as e:
                        logger.warning("Resource release error (%s): %s", key, e)
                cls._resources.pop(key, None)
        logger.info("Global resource release: %d instances freed", count)
        return count

    @classmethod
    def registered_count(cls) -> int:
        """获取当前注册的资源实例数。"""
        with cls._resource_lock:
            # Only count live references
            return sum(1 for ref in cls._resources.values() if ref() is not None)


class LazyResource(Resource):
    """延迟加载资源 —— 首次访问时才加载，配合 cached_property 使用。

    用法:
        from lib.decorators import cached_property

        class TemplateResource(LazyResource):
            def __init__(self, path: str):
                super().__init__()
                self.path = path
                self.resource_add(f'template:{path}')

            @cached_property
            def image(self):
                import cv2
                return cv2.imread(self.path)

            def resource_release(self):
                self.__dict__.pop('image', None)
                super().resource_release()
    """

    def __init__(self) -> None:
        super().__init__()

    def resource_release(self) -> None:
        """清除所有 cached_property 缓存。"""
        # Clear all cached_property values
        cached_keys = [
            k for k, v in type(self).__dict__.items()
            if hasattr(v, '__get__') and 'cache' in type(v).__name__.lower()
        ]
        for key in cached_keys:
            self.__dict__.pop(key, None)

        # Also clear common cache patterns
        for key in list(self.__dict__.keys()):
            if key.startswith('_cache') or key.startswith('_cached'):
                del self.__dict__[key]

        super().resource_release()
