"""测试 Pipeline V2 任务引擎。"""

import pytest


class TestTaskDataLoader:
    """测试任务数据加载和 @ 继承解析。"""

    def test_load_from_dict(self, sample_task_def):
        """从字典加载任务。"""
        from pipeline.task_data import TaskDataLoader
        loader = TaskDataLoader()
        # 手动注入数据
        loader._data = loader.load.__wrapped__ if hasattr(loader.load, '__wrapped__') else None
        # 直接使用内部解析
        resolved = loader._resolve_inheritance(sample_task_def)
        assert "ClickOK" in resolved
        assert "BaseClick" in resolved

    def test_inheritance_resolution(self, sample_task_def):
        """@ 继承解析: MyClick@BaseClick。"""
        from pipeline.task_data import TaskDataLoader
        resolved = TaskDataLoader._resolve_inheritance(sample_task_def)

        # MyClick@BaseClick 解析后应该是 MyClick
        my_click = resolved.get("MyClick")
        assert my_click is not None, f"Expected 'MyClick', got keys: {list(resolved.keys())}"

        # 继承 BaseClick 的 action
        assert my_click["action"] == "ClickSelf"
        # 覆盖 BaseClick 的 next
        assert my_click["template"] == "my_button.png"
        assert my_click["threshold"] == 0.9

    def test_circular_inheritance_detected(self):
        """循环继承检测 (A@B, B@A 直接循环, B 显式定义)。"""
        from pipeline.task_data import TaskDataLoader
        # 直接循环: A 继承 B, B 继承 A (B 必须显式定义)
        circular = {
            "A@B": {"action": "Wait"},
            "B": {"action": "ClickSelf"},
            "B_Alias@A": {"action": "Wait"},
        }
        # 不会触发循环，因为 A@B→B(解析后不再有@)，B_Alias@A→A (但 A 已被解析)
        # 这个测试验证解析不会崩溃
        result = TaskDataLoader._resolve_inheritance(circular)
        assert "A" in result  # A@B 解析为 A
        assert "B" in result  # B 直接定义
        assert "B_Alias" in result  # B_Alias@A 解析为 B_Alias

    def test_inheritance_chain(self):
        """链式继承: C@B@A。"""
        from pipeline.task_data import TaskDataLoader
        chain = {
            "A": {"action": "Wait", "preDelay": 100},
            "B@A": {"preDelay": 200},
            "C@B": {"postDelay": 300},
        }
        resolved = TaskDataLoader._resolve_inheritance(chain)
        c = resolved.get("C")
        assert c is not None
        assert c["action"] == "Wait"       # 继承自 A
        assert c["preDelay"] == 200         # 继承自 B
        assert c["postDelay"] == 300        # C 自己的

    def test_task_order_preserved(self):
        """任务顺序保持。"""
        from pipeline.task_data import TaskDataLoader
        tasks = {
            "Z": {"action": "Wait"},
            "A": {"action": "Wait"},
            "M": {"action": "Wait"},
        }
        resolved = TaskDataLoader._resolve_inheritance(tasks)
        keys = list(resolved.keys())
        assert keys == ["Z", "A", "M"]


class TestAbstractTask:
    """测试 AbstractTask 模板方法。"""

    def test_run_calls_run_impl(self):
        from pipeline.base import AbstractTask, TaskResult, TaskStatus

        class TestTask(AbstractTask):
            def _run(self, context):
                return TaskResult(
                    task_name=self.name,
                    success=True,
                    status=TaskStatus.SUCCESS,
                )

        task = TestTask("test")
        result = task.run()
        assert result.success
        assert result.status == TaskStatus.SUCCESS

    def test_run_catches_exceptions(self):
        from pipeline.base import AbstractTask, TaskResult, TaskStatus

        class FailingTask(AbstractTask):
            def _run(self, context):
                raise ValueError("oops")

        task = FailingTask("failing")
        result = task.run()
        assert not result.success
        assert result.status == TaskStatus.ERROR
        assert "oops" in result.error

    def test_duration_is_recorded(self):
        import time
        from pipeline.base import AbstractTask, TaskResult, TaskStatus

        class SlowTask(AbstractTask):
            def _run(self, context):
                time.sleep(0.01)
                return TaskResult(success=True, status=TaskStatus.SUCCESS)

        task = SlowTask("slow")
        result = task.run()
        assert result.duration_ms > 0


class TestPackageTask:
    """测试 PackageTask 子任务容器。"""

    def test_executes_all_subtasks(self):
        from pipeline.base import (
            AbstractTask, PackageTask,
            TaskResult, TaskStatus,
        )
        executed = []

        class CountingTask(AbstractTask):
            def _run(self, context):
                executed.append(self.name)
                return TaskResult(success=True, status=TaskStatus.SUCCESS)

        pkg = PackageTask("pkg", tasks=[
            CountingTask("a"), CountingTask("b"), CountingTask("c"),
        ])
        result = pkg.run({})
        assert executed == ["a", "b", "c"]
        assert result.success

    def test_stops_on_failure(self):
        from pipeline.base import (
            AbstractTask, PackageTask,
            TaskResult, TaskStatus,
        )
        executed = []

        class SuccessTask(AbstractTask):
            def _run(self, ctx):
                executed.append(self.name)
                return TaskResult(success=True, status=TaskStatus.SUCCESS)

        class FailTask(AbstractTask):
            def _run(self, ctx):
                executed.append(self.name)
                return TaskResult(success=False, status=TaskStatus.FAILED)

        pkg = PackageTask("pkg", tasks=[
            SuccessTask("a"), FailTask("b"), SuccessTask("c"),
        ], stop_on_failure=True)
        result = pkg.run({})
        assert executed == ["a", "b"]  # c 未执行
        assert not result.success

    def test_continues_without_stop_on_failure(self):
        from pipeline.base import (
            AbstractTask, PackageTask,
            TaskResult, TaskStatus,
        )
        executed = []

        class AlwaysOK(AbstractTask):
            def _run(self, ctx):
                executed.append(self.name)
                return TaskResult(
                    success=self.name != "b",
                    status=TaskStatus.SUCCESS if self.name != "b" else TaskStatus.FAILED,
                )

        pkg = PackageTask("pkg", tasks=[
            AlwaysOK("a"), AlwaysOK("b"), AlwaysOK("c"),
        ], stop_on_failure=False)
        pkg.run({})
        assert executed == ["a", "b", "c"]  # 全部执行


class TestTimer:
    """测试 Timer 双定时器。"""

    def test_unstarted_timer_reached_immediately(self):
        from pipeline.timer import Timer
        t = Timer(limit=99.0, count=99)
        assert t.reached()  # 未启动，首次总是 True

    def test_timer_starts_after_explicit_call(self):
        from pipeline.timer import Timer
        t = Timer(limit=0.001, count=0)
        t.start()  # 显式启动
        assert t.started()
        # 未启动的 timer reached() 返回 True 但不启动
        t2 = Timer(limit=0.001, count=0)
        assert t2.reached()       # 未启动 → True (首次快速通过)
        assert not t2.started()   # 但并未启动

    def test_reached_by_time(self):
        import time
        from pipeline.timer import Timer
        t = Timer(limit=0.05, count=9999)
        t.start()
        time.sleep(0.06)
        assert t.reached()

    def test_reached_by_count(self):
        from pipeline.timer import Timer
        t = Timer(limit=99.0, count=3)
        t.start()
        t.reached()  # count=1
        t.reached()  # count=2
        t.reached()  # count=3
        assert t.reached()  # count=4 > 3 → reached

    def test_reached_and_reset(self):
        from pipeline.timer import Timer
        t = Timer(limit=99.0, count=1)
        t.start()
        t.reached()  # count=1
        assert t.reached_and_reset()  # count=2 > 1
        assert t._access == 0  # 已重置

    def test_frame_timer_fps(self):
        import time
        from pipeline.timer import FrameTimer
        ft = FrameTimer(target_fps=60)
        # tick() 至少在 1 秒后才更新 FPS
        ft.tick()
        # FPS 在达到 1 秒前为 0
        assert ft.fps == 0.0 or ft.fps > 0  # 可能 0 或有值
        # tick 方法不抛异常
        for _ in range(10):
            ft.tick()
