"""task_data.py — JSON 加载与 @继承解析。

TaskDataLoader 从 resource/tasks/*.json 加载所有任务定义,
并解析 @ 继承语法 (TaskName@BaseTask)。

继承规则 (参考 MAA):
  - "TaskName@BaseTask" 以 BaseTask 的字段为模板
  - TaskName 中的显式字段覆盖 BaseTask 的对应字段
  - 列表字段 (next, sub 等): TaskName 的列表完全覆盖 BaseTask 的列表
  - 支持链式继承: "TaskA@TaskB@TaskC"
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("pjsk_pipeline_v2")


# ──────────────────────────────────────────
# 任务数据容器
# ──────────────────────────────────────────


@dataclass
class TaskData:
    """加载后的任务数据容器。

    包含原始 JSON 数据和解析后的任务定义字典。
    """

    raw: dict[str, dict] = field(default_factory=dict)
    resolved: dict[str, dict] = field(default_factory=dict)
    task_order: list[str] = field(default_factory=list)

    def get_task(self, name: str) -> dict | None:
        """获取完全解析后的任务定义。"""
        return self.resolved.get(name)

    def get_raw(self, name: str) -> dict | None:
        """获取原始 (可能带 @) 的任务定义。"""
        return self.raw.get(name)

    def has_task(self, name: str) -> bool:
        """检查任务是否存在。"""
        return name in self.resolved

    def __contains__(self, name: str) -> bool:
        return name in self.resolved

    def __len__(self) -> int:
        return len(self.resolved)

    def __iter__(self):
        return iter(self.resolved.items())

    @property
    def task_names(self) -> list[str]:
        return list(self.resolved.keys())


# ──────────────────────────────────────────
# 任务数据加载器
# ──────────────────────────────────────────


# @继承语法正则: "TaskName@BaseTask@GrandParent..."
_INHERIT_RE = re.compile(r"^(.+)@(.+)$")


class TaskDataLoader:
    """任务数据加载器。

    从 JSON 文件/目录加载任务定义, 解析 @ 继承。

    用法:
        loader = TaskDataLoader()
        data = loader.load("resource/tasks/")
        task_def = data.get_task("MyTask")
    """

    def __init__(self, resource_dirs: list[str] | str | None = None):
        if isinstance(resource_dirs, str):
            resource_dirs = [resource_dirs]
        self.resource_dirs: list[str] = resource_dirs or []
        self._data: TaskData | None = None

    def load(self, path: str | None = None) -> TaskData:
        """加载任务数据。

        Args:
            path: JSON 文件或目录路径。
                  如果为 None, 使用 self.resource_dirs。
        """
        if path is None and not self.resource_dirs:
            raise ValueError("必须指定 path 或设置 resource_dirs")

        all_raw: dict[str, dict] = OrderedDict()

        targets: list[str] = []
        if path:
            targets.append(path)
        targets.extend(self.resource_dirs)

        for target in targets:
            if os.path.isdir(target):
                self._load_directory(target, all_raw)
            elif os.path.isfile(target):
                self._load_file(target, all_raw)
            else:
                logger.warning(f"[TaskDataLoader] 路径不存在: {target}")

        # 解析 @继承
        resolved = self._resolve_inheritance(all_raw)
        task_order = list(resolved.keys())

        self._data = TaskData(
            raw=all_raw,
            resolved=resolved,
            task_order=task_order,
        )

        logger.info(
            f"[TaskDataLoader] 已加载 {len(all_raw)} 个原始任务定义, "
            f"解析后 {len(resolved)} 个任务"
        )
        return self._data

    def _load_directory(self, dir_path: str, dest: dict[str, dict]) -> None:
        """加载目录下所有 JSON 文件。"""
        if not os.path.isdir(dir_path):
            logger.warning(f"[TaskDataLoader] 目录不存在: {dir_path}")
            return

        for fname in sorted(os.listdir(dir_path)):
            if fname.endswith(".json"):
                fpath = os.path.join(dir_path, fname)
                try:
                    self._load_file(fpath, dest)
                except Exception as e:
                    logger.error(f"[TaskDataLoader] 加载文件失败 {fpath}: {e}")

    def _load_file(self, file_path: str, dest: dict[str, dict]) -> None:
        """加载单个 JSON 文件。"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            logger.warning(f"[TaskDataLoader] JSON 根对象不是 dict: {file_path}")
            return

        for name, task_def in data.items():
            if not isinstance(task_def, dict):
                continue
            # 跳过文档/元数据键 (以 "=" 开头的)
            if name.startswith("=") or name.startswith("_"):
                continue
            if name in dest:
                logger.debug(f"[TaskDataLoader] 任务 '{name}' 被覆盖 (来自 {file_path})")
            dest[name] = task_def

    @classmethod
    def _resolve_inheritance(cls, raw: dict[str, dict]) -> dict[str, dict]:
        """解析所有 @ 继承语法。

        处理:
          - "TaskA@BaseTask" → TaskA 继承 BaseTask
          - "TaskA@BaseA@BaseB" → TaskA 继承 BaseA, BaseA 继承 BaseB
          - 循环继承检测
        """
        resolved: dict[str, dict] = {}
        _resolving: set[str] = set()  # 用于循环检测

        def _resolve(name: str) -> dict:
            """递归解析单个任务名。"""
            if name in resolved:
                return resolved[name]

            if name in _resolving:
                raise ValueError(f"[TaskDataLoader] 循环继承检测: {name}")

            raw_def = raw.get(name)
            if raw_def is None:
                # 任务名可能没有 @ 且不存在于原始数据中
                # 返回空定义
                logger.warning(f"[TaskDataLoader] 任务 '{name}' 未定义, 返回空定义")
                resolved[name] = {}
                return resolved[name]

            # 检查是否有 @ 继承
            match = _INHERIT_RE.match(name)
            if not match:
                # 没有 @, 直接使用原始定义
                resolved[name] = dict(raw_def)
                return resolved[name]

            derived_name = match.group(1)  # TaskName
            parent_name = match.group(2)   # BaseTask

            # 标记正在解析
            _resolving.add(name)

            # 递归解析父任务
            parent_def = _resolve(parent_name)

            # 合并: 子任务覆盖父任务
            merged = dict(parent_def)
            # 子任务中显式定义的字段覆盖父任务
            for key, value in raw_def.items():
                merged[key] = value

            _resolving.discard(name)

            # 以派生名 (TaskName) 存储, 而非 "TaskName@BaseTask"
            resolved[derived_name] = merged
            return merged

        # 解析所有任务
        for name in list(raw.keys()):
            try:
                effective_name = _INHERIT_RE.match(name)
                if effective_name:
                    _resolve(name)
                else:
                    resolved[name] = dict(raw[name])
            except Exception as e:
                logger.error(f"[TaskDataLoader] 解析任务 '{name}' 失败: {e}")
                resolved[name] = dict(raw.get(name, {}))

        return resolved

    def get_data(self) -> TaskData | None:
        """获取已加载的任务数据。"""
        return self._data

    def reload(self) -> TaskData:
        """重新加载任务数据。"""
        self._data = None
        return self.load()

    # ── 便捷方法 ──

    def get_task(self, name: str) -> dict | None:
        """获取解析后的任务定义。"""
        if self._data is None:
            return None
        return self._data.get_task(name)

    @property
    def task_order(self) -> list[str]:
        """获取任务顺序列表 (按首次加载顺序)。"""
        if self._data is None:
            return []
        return self._data.task_order

    @property
    def all_tasks(self) -> dict[str, dict]:
        """获取所有解析后的任务定义。"""
        if self._data is None:
            return {}
        return self._data.resolved

    @staticmethod
    def merge_tasks(base: dict, override: dict) -> dict:
        """合并两个任务定义 (手动继承)。

        Args:
            base: 基准任务定义
            override: 覆盖字段

        Returns:
            合并后的任务定义
        """
        merged = dict(base)
        for key, value in override.items():
            merged[key] = value
        return merged
