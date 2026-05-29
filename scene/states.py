"""游戏场景定义 —— 基于 ALAS 启发式分类的场景枚举。"""

from enum import Enum, auto


class GameScene(str, Enum):
    """PJSK 游戏场景枚举。

    按检测成本从低到高排列:
        LOADING < RESULT < MENU < GAME < UNKNOWN
    """

    GAME = "game"           # 执行中 — 判定线有 note 活动
    RESULT = "result"       # 结算画面 — 整体高亮, 无 note
    MENU = "menu"           # 主菜单 / 选歌 / 设置
    LOADING = "loading"     # 加载中 — 全黑 / 渐变 / 模糊
    UNKNOWN = "unknown"     # 无法识别


class SceneTask(str, Enum):
    """每个场景下对应的自动化任务名称。"""

    # --- GAME ---
    PLAY_AUTO = "play_auto"           # 自动执行
    PLAY_MANUAL = "play_manual"       # 手动执行 (仅监控)

    # --- RESULT ---
    READ_SCORE = "read_score"         # 读取结算分数
    RETRY_CHECK = "retry_check"       # 检查是否可以重试

    # --- MENU ---
    SELECT_SONG = "select_song"       # 选歌
    NAVIGATE = "navigate"             # 导航
    SETTINGS = "settings"             # 设置
    IDLE = "idle"                     # 空闲等待

    # --- LOADING ---
    WAIT = "wait"                     # 等待加载完成

    # --- UNKNOWN ---
    DIAGNOSE = "diagnose"            # 诊断 / 降级策略
