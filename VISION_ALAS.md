# ALAS (AzurLaneAutoScript) 深度设计模式研究 — PJSK 集成路线图

> 基于 https://github.com/LmeSzinc/AzurLaneAutoScript 源代码分析

---

## 1. Button 声明式 UI 元素系统

ALAS 最核心的设计：一个 Button = 一个 UI 元素的完整描述。

```python
class Button(Resource):
    def __init__(self, area, color, button, file=None, name=None):
        # area: 元素出现区域 (x1, y1, x2, y2)
        # color: 期望该区域的颜色 (r, g, b)
        # button: 点击区域 (x1, y1, x2, y2) — 通常和 area 相同
        # file: 模板匹配图片路径
```

**关键方法：**
- `appear_on(image, threshold)` — 通过颜色相似度检测元素是否存在
- `match(image, offset, similarity)` — 模板匹配检测元素
- `match_binary(image)` — 二值化后模板匹配（抗光照变化）
- `ensure_template()` — 延迟加载模板图片（Resource 管理）
- `load_color(image)` — 从截图动态取色（用于自适应按钮）

**PJSK 应该如何抄：**
创建 `vision/button.py`，定义 Project Sekai 的 UI 元素：
```python
from dataclasses import dataclass

@dataclass
class PjskButton:
    name: str
    area: tuple      # (x1, y1, x2, y2) 相对比例 0~1
    color: tuple     # (r, g, b)
    button: tuple    # 点击区域
    template: str = ""   # 模板图片路径
    
    def appear_on(self, frame) -> bool:
        """颜色检测 — 最快的方法"""
        roi = crop_relative(frame, self.area)
        avg_color = cv2.mean(roi)[:3]
        return color_distance(avg_color, self.color) < 30
    
    def match_template(self, frame, threshold=0.85) -> bool:
        """模板匹配 — 准确但慢"""
        ...

# 游戏 UI 元素定义
BUTTONS = {
    "start_live": PjskButton(
        name="start_live",
        area=(0.42, 0.85, 0.58, 0.92),
        color=(255, 180, 50),
        button=(0.42, 0.85, 0.58, 0.92),
        template="resource/templates/start_live.png",
    ),
    "result_skip": PjskButton(
        area=(0.80, 0.05, 0.95, 0.12),
        color=(200, 200, 200),
        button=(0.80, 0.05, 0.95, 0.12),
    ),
}
```

---

## 2. Timer 双定时器

```python
class Timer:
    def __init__(self, limit, count=0):
        # limit: 时间限制（秒）
        # count: 访问次数限制
        # 两者任一达到即认为 timer reached
        
    def reached(self) -> bool    # 是否到达限制
    def reset(self)              # 重置
    def wait(self)               # 阻塞直到到达
    def reached_and_reset(self) -> bool  # 到达后自动重置
```

**双定时器价值：** 慢速设备上截图耗时 > limit 时，访问次数限制(count)兜底，确保不会无限等待。

**PJSK 直接复用：** 把 Timer 类原样抄到 `pipeline/timer.py`。

---

## 3. cached_property 装饰器

```python
# module/base/decorator.py
# 比 @functools.cached_property 更强：
# 支持通过 __dict__.pop() 手动失效
# 配合 resource_release() 统一释放

class cached_property:
    def __init__(self, func):
        self.func = func
    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value
```

**PJSK 直接复用** 到 `lib/decorators.py`。

---

## 4. Resource 资源管理器

```python
class Resource:
    """跟踪所有加载的资源，一次性释放。"""
    _resources = {}  # class-level registry
    
    def resource_add(self, key):
        Resource._resources[key] = self
    
    def resource_release(self):
        # 子类重写释放具体资源
```

**PJSK 借鉴：** 模板图片、OCR 模型等资源用统一管理器管理，避免内存泄漏。

---

## 5. OCR 前处理管线

```python
class Ocr:
    def pre_process(self, image):
        """默认预处理: 保留指定颜色 + 二值化"""
        image = color_similar_2d(image, color=self.letter)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, image = cv2.threshold(image, self.threshold, 255, cv2.THRESH_BINARY)
        return image
    
    def after_process(self, result):
        """后处理: 替换特殊字符、数字格式化"""
        # O12 → O12, 空格 → '', 特殊字符替换
```

**PJSK 改进 vision/ocr.py：** 加入 ALAS 风格的颜色提取 + Otsu 二值化前处理，提高游戏内数字识别率。

---

## 6. 异常体系的层级

```python
# 任务级异常
class CampaignEnd(Exception): pass        # 关卡结束
class OilExhausted(Exception): pass       # 资源耗尽

# 游戏级异常
class GameStuckError(Exception): pass     # 画面卡住
class GameBugError(Exception): pass       # 游戏异常
class GameTooManyClickError(Exception): pass  # 防死循环

# 用户干预
class RequestHumanTakeover(Exception): pass   # 需要用户介入

# 连接级
class EmulatorNotRunningError(Exception): pass
class GameNotRunningError(Exception): pass
class GamePageUnknownError(Exception): pass
```

**PJSK 改进 exceptions.py：** 增加 `CampaignEnd`, `OilExhausted`, `RequestHumanTakeover`，配合自动恢复策略。

---

## 7. Device/Control 多层架构

```python
class Device(Screenshot, Control, AppControl):
    # 多重继承组合
    # Screenshot: 各种截图方法 (adb exec-out / uiautomator / scrcpy)
    # Control: 各种触摸方法 (adb shell input / minitouch)
    # AppControl: 应用启动/停止/状态检测
    
    def method_check(self):
        # 自动运行 benchmark
        # 选择最快的截图方法
```

**PJSK controller/ 已实现**类似架构。可加 `_benchmark()` 方法自动选后端。

---

## 8. 配置模板系统

ALAS 的配置不直接写在代码里，而是用 JSON 模板 + YAML 覆盖：
```
config/
├── template.json          # 配置参数定义（类型、默认值、UI提示）
├── template.maa.json      # MAA 格式兼容
├── deploy.template.yaml   # 部署模板
└── deploy.template-cn.yaml
```

**PJSK 可借鉴：** 用 YAML 配置 + JSON Schema 校验，前端自动生成配置表单。

---

## 9. Handler 系统 — 游戏交互处理器

ALAS 有独立的 handlers/ 目录，每个 handler 处理一种交互：
- `handler/goto.py` — 页面导航
- `handler/map_event.py` — 地图事件处理
- `handler/inactive.py` — 闲置检测

**PJSK handler 设计：**
```
handlers/
├── goto_game.py       # 启动游戏 → 登录 → 主页
├── select_song.py     # 选歌 → 选难度
├── handle_result.py   # 结算画面 → 跳过 → 统计
└── reconnect.py       # 断线重连
```

---

## 10. PJSK 下一步路线图

基于 ALAS 研究，PJSK v5.0 应添加：

| 优先级 | 特性 | 对应 ALAS 模式 | 文件 |
|--------|------|---------------|------|
| P0 | Button 声明式 UI | Button + appear_on() + match() | `vision/button.py` |
| P0 | Timer 双定时器 | Timer(limit, count) | `pipeline/timer.py` |
| P0 | Handler 交互处理器 | module/handler/*.py | `handlers/` |
| P1 | OCR 颜色前处理 | Ocr.pre_process() | `vision/ocr.py` 改进 |
| P1 | cached_property | module/base/decorator.py | `lib/decorators.py` |
| P1 | Resource 管理 | module/base/resource.py | `lib/resource.py` |
| P1 | 配置表单 + Schema | config/template.json | `config/schema.py` |
| P2 | 方法 Benchmark | Device.method_check() | `controller/combined.py` |
| P2 | 用户提交通知 | RequestHumanTakeover | `exceptions.py` |
| P2 | 自动更新 | deploy/install.py | `scripts/auto_update.py` |
