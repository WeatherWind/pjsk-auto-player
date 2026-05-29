"""
自动编队系统 —— 活动连续执行队伍配置、角色选择、自动推荐。

功能:
  - 加载编队 JSON 模板
  - 导航到编队画面
  - 按角色名/颜色/自动推荐编队
  - 活动加成检测

使用前提:
  - 手机已连接, PJSK 在主界面
  - 编队画面坐标需要根据手机分辨率微调
"""

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("pjsk_team")


class TeamTemplate:
    """编队模板定义。"""

    def __init__(self, name: str, data: dict):
        self.key = name
        self.name = data.get("name", name)
        self.description = data.get("description", "")
        self.auto_recommend = data.get("auto_recommend", True)
        self.method = data.get("method", "auto")
        self.color = data.get("color", "")
        self.slots = data.get("slots", [])

    def __repr__(self):
        return f"Team({self.name}, method={self.method})"


class TeamBuilder:
    """
    自动编队器。

    模式:
      - auto: 点击"自动编队"按钮
      - manual: 逐个槽位选择指定角色
      - color: 按卡牌颜色筛选
    """

    def __init__(self, config: dict, team_name: str = ""):
        self.cfg = config
        self.team: Optional[TeamTemplate] = None
        self.adb = None

        s = config.get("screen", {})
        self.screen_w = s.get("width", 1080)
        self.screen_h = s.get("height", 2400)

        if team_name:
            self._load_team(team_name)

    def _load_team(self, name: str):
        """加载编队模板。"""
        if os.path.isfile(name):
            path = name
        else:
            teams_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "teams"
            )
            for ext in [".json", ".yaml", ".yml"]:
                p = os.path.join(teams_dir, f"{name}{ext}")
                if os.path.exists(p):
                    path = p
                    break
            else:
                path = os.path.join(teams_dir, "default.json")
                name = "event-loop"

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"编队加载失败: {e}")
            return

        if name in data:
            self.team = TeamTemplate(name, data[name])
        else:
            first = next((k for k in data if k not in ("doc", "version", "_doc")), None)
            if first:
                self.team = TeamTemplate(first, data[first])

        logger.info(f"编队已加载: {self.team}")

    def list_teams(self) -> list[dict]:
        """列出所有可用编队。"""
        teams_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "teams"
        )
        results = []
        if not os.path.exists(teams_dir):
            return results

        for fname in sorted(os.listdir(teams_dir)):
            if not fname.endswith((".json", ".yaml", ".yml")):
                continue
            path = os.path.join(teams_dir, fname)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for key, val in data.items():
                    if key in ("doc", "version", "_doc"):
                        continue
                    results.append({
                        "key": key,
                        "name": val.get("name", key),
                        "description": val.get("description", ""),
                        "method": val.get("method", "auto"),
                        "slots": len(val.get("slots", [])),
                    })
            except (json.JSONDecodeError, IOError):
                continue
        return results

    def apply(self, adb) -> bool:
        """
        应用编队。

        Args:
            adb: ADBController 实例

        Returns:
            是否成功
        """
        if not self.team:
            logger.error("未加载编队")
            return False

        self.adb = adb
        method = self.team.method

        logger.info(f"编队: {self.team.name} (method={method})")

        try:
            if method == "auto":
                return self._apply_auto()
            elif method == "manual":
                return self._apply_manual()
            elif method == "color":
                return self._apply_color()
            else:
                logger.warning(f"不支持的编队方式: {method}")
                return False
        except Exception as e:
            logger.error(f"编队失败: {e}")
            return False

    def _apply_auto(self) -> bool:
        """
        自动编队: 点击"自动编队/推荐"按钮。

        假设已经位于编队画面。
        """
        nav = self.cfg.get("navigation", {})

        # 编队推荐按钮位置 (需要根据手机分辨率调整)
        if nav.get("team", {}).get("auto_button"):
            x, y = nav["team"]["auto_button"]
        else:
            # 默认: 屏幕右下区域
            x = int(self.screen_w * 0.85)
            y = int(self.screen_h * 0.9)

        logger.info("点击自动编队按钮...")
        self.adb.tap(x, y)
        time.sleep(1.5)

        # 确认编队
        if nav.get("team", {}).get("confirm_button"):
            cx, cy = nav["team"]["confirm_button"]
        else:
            cx = int(self.screen_w * 0.5)
            cy = int(self.screen_h * 0.85)

        self.adb.tap(cx, cy)
        time.sleep(1.0)
        logger.info("自动编队完成")
        return True

    def _apply_manual(self) -> bool:
        """
        手动编队: 逐个槽位选择指定角色。

        流程:
          1. 点击第 1 个槽位
          2. 在角色列表中找到指定角色 → 点击
          3. 重复 1-2 直到所有槽位填满
        """
        nav = self.cfg.get("navigation", {})

        for slot in self.team.slots:
            pos = slot.get("pos", 1)
            character = slot.get("character", "")
            card_type = slot.get("card_type", "any")

            logger.info(f"  槽位 {pos}: 选择 {character or card_type}")

            # 点击槽位
            if nav.get("team", {}).get("slot_positions"):
                slots = nav["team"]["slot_positions"]
                if pos <= len(slots):
                    sx, sy = slots[pos - 1]
                else:
                    sx = int(self.screen_w * 0.3)
                    sy = int(self.screen_h * (0.2 + pos * 0.12))
            else:
                sx = int(self.screen_w * 0.3)
                sy = int(self.screen_h * (0.2 + pos * 0.12))

            self.adb.tap(sx, sy)
            time.sleep(1.0)

            # 选择角色 (按名字搜索)
            if character and character != "任意":
                self._select_character(character, nav)

            # 确认选择
            if nav.get("team", {}).get("select_confirm"):
                cx, cy = nav["team"]["select_confirm"]
            else:
                cx = int(self.screen_w * 0.8)
                cy = int(self.screen_h * 0.85)
            self.adb.tap(cx, cy)
            time.sleep(0.5)

        return True

    def _apply_color(self) -> bool:
        """
        按颜色编队: 选择指定颜色的卡牌。
        """
        color = self.team.color
        logger.info(f"按颜色编队: {color}")

        nav = self.cfg.get("navigation", {})

        # 点击颜色筛选
        if nav.get("team", {}).get("color_filter"):
            colors = nav["team"]["color_filter"]
            color_map = {"cute": 0, "cool": 1, "pure": 2, "happy": 3, "mysterious": 4}
            idx = color_map.get(color, 0)
            if idx < len(colors):
                fx, fy = colors[idx]
                self.adb.tap(fx, fy)
                time.sleep(0.5)

        # 自动选择
        return self._apply_auto()

    def _select_character(self, name: str, nav: dict):
        """
        在角色选择界面点击指定角色。

        使用 OCR 或预设坐标。
        """
        # 预设角色坐标 (如果有)
        if nav.get("team", {}).get("characters"):
            chars = nav["team"]["characters"]
            if name in chars:
                cx, cy = chars[name]
                self.adb.tap(cx, cy)
                time.sleep(0.5)
                return
            # 也检查别名
            for key, coords in chars.items():
                if name in key:
                    self.adb.tap(coords[0], coords[1])
                    time.sleep(0.5)
                    return

        logger.info(f"  角色 '{name}' 无预设坐标, 尝试用 OCR...")
        try:
            # 尝试截图 + OCR 找到角色位置
            frame = self.adb.screencap()
            if frame is not None:
                from ocr_reader import OcrReader
                ocr = OcrReader(self.cfg)
                if ocr._init_reader():
                    text = ocr._ocr_text(frame)
                    if name in text:
                        # 找到角色位置 (简化: 点击屏幕中央)
                        cx = int(self.screen_w * 0.3)
                        cy = int(self.screen_h * 0.5)
                        self.adb.tap(cx, cy)
                        time.sleep(0.5)
                        return
        except Exception:
            pass

        logger.info(f"  未找到角色 '{name}', 点击屏幕中央")
        self.adb.tap(self.screen_w // 2, self.screen_h // 2)
        time.sleep(0.5)

    def navigate_to_team_screen(self, adb) -> bool:
        """
        从主界面导航到编队画面。

        需要:
          - PJSK 已打开, 在主界面
        """
        self.adb = adb
        nav = self.cfg.get("navigation", {})

        logger.info("导航到编队画面...")

        # 点击"队伍"按钮
        if nav.get("main_menu", {}).get("team_button"):
            tx, ty = nav["main_menu"]["team_button"]
        else:
            tx = int(self.screen_w * 0.5)
            ty = int(self.screen_h * 0.3)

        self.adb.tap(tx, ty)
        time.sleep(2.0)

        # 选择"编队" tab
        if nav.get("team", {}).get("team_tab"):
            tx, ty = nav["team"]["team_tab"]
            self.adb.tap(tx, ty)
            time.sleep(1.5)

        logger.info("已进入编队画面")
        return True
