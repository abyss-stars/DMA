import json
import random
import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JWaitFreezes


@AgentServer.custom_action("click_target")
class ClickTargetAction(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("ClickTargetAction is running!")

        param = json.loads(argv.custom_action_param or "{}") or {}
        target = param.get("target")
        if not isinstance(target, list) or len(target) != 2:
            return False

        # 执行点击
        click_job = context.tasker.controller.post_click(target[0], target[1])
        # 等待点击完成，这一步必须有！
        click_job.wait()

        return True


def _point(box) -> tuple[int, int]:
    """[x, y] 原样返回；[x, y, w, h] 返回框内一点（靠近中心概率更高，与 pipeline Swipe 行为一致）。"""
    if len(box) == 2:
        return int(box[0]), int(box[1])

    x, y, w, h = (int(v) for v in box)
    px = random.gauss(x + w / 2, max(w, 1) / 4)
    py = random.gauss(y + h / 2, max(h, 1) / 4)
    px = min(max(px, x), x + w - 1)
    py = min(max(py, y), y + h - 1)
    return int(px), int(py)


@AgentServer.custom_action("abyss_align")
class AbyssAlignAction(CustomAction):
    """开启深渊：抬视角 → 右转对准入口图标 → 前进，直到看到「开始深渊」。

    流程（对应 assets/resource/pipeline/test.json 里验证过的写法）：
       1. MoveViewUp  ×times   —— 把视角抬到能看见入口指示
       2. MoveViewRight 反复    —— 直到 [icon_roi] 内识别到指令图标
       3. MoveForward  duration —— 持续前进（约 2s）
       4. 未见「开始深渊」则每次 MoveForward 0.5s 再查，直到看到或用尽次数

    参数全部来自 custom_action_param，改轨迹不用动代码。
    """

    # region 基础动作

    def _settle(self, context: Context, cfg: dict, default: int = 300) -> None:
        """等画面静止 settle 毫秒；静止判定失败时退回固定等待。

        settle 语义 = “画面至少静止这么久”，长滑之后自动多等，短滑之后不浪费时间。
        target 显式给全屏 (0,0,0,0)，因为自定义动作里没有“本节点识别到的位置”，
        让它走 target=true（自身）会退化成未定义行为。
        """
        ms = int(cfg.get("settle", default))
        if ms <= 0:
            return
        target = tuple(cfg.get("freeze_target", (0, 0, 0, 0)))
        param = JWaitFreezes(
            time=ms,
            target=target,
            threshold=float(cfg.get("freeze_threshold", 0.95)),
            timeout=max(ms * 3, 1000),
        )
        if not context.wait_freezes(box=target, wait_freezes_param=param):
            time.sleep(ms / 1000)

    def _swipe(self, context: Context, begin, end, duration: int) -> None:
        bx, by = _point(begin)
        ex, ey = _point(end)
        context.tasker.controller.post_swipe(bx, by, ex, ey, duration).wait()

    def _move_view_up(self, context: Context, cfg: dict) -> None:
        times = int(cfg.get("times", 5))
        delay = int(cfg.get("delay", 300)) / 1000
        for i in range(times):
            self._swipe(context, cfg["begin"], cfg["end"], int(cfg.get("duration", 300)))
            if i + 1 < times:
                time.sleep(delay)
        print(f"[abyss_align] 抬视角 ×{times}", flush=True)

    def _move_view_right(self, context: Context, cfg: dict) -> None:
        self._swipe(context, cfg["begin"], cfg["end"], int(cfg.get("duration", 300)))
        self._settle(context, cfg, 300)

    def _move_forward(self, context: Context, begin, end, duration: int) -> None:
        self._swipe(context, begin, end, duration)

    def _find(self, context: Context, node: str):
        """截图并识别 node，命中返回 detail，否则返回 None。"""
        image = context.tasker.controller.post_screencap().wait().get()
        detail = context.run_recognition(node, image)
        if detail is not None and detail.hit:
            return detail
        return None

    def _wait_for(self, context: Context, node: str, timeout: float):
        """在 timeout 秒内反复识别 node，命中返回 detail。"""
        deadline = time.time() + timeout
        while True:
            detail = self._find(context, node)
            if detail is not None and detail.box is not None:
                return detail
            if time.time() >= deadline:
                return None
            time.sleep(0.3)

    def _see(self, context: Context, node: str) -> bool:
        return self._find(context, node) is not None

    # endregion

    # region 重开

    def _restart(self, context: Context, cfg: dict) -> bool:
        """重开本次深渊，三步依次走：ErrorExit → ClickRestart → Confirm。

        1. ErrorExit    —— 关卡里的异常退出按钮，点开退出/重开菜单
        2. ClickRestart —— 菜单里的「重新开始」
        3. Confirm      —— 「确定」二次确认（Confirm 复用 enterAbyss.json 的定义）

        每步统一「先等节点出现，再执行它的动作」：弹窗有弹出动画，
        死等固定时长既慢又不可靠。全程只用 Context API
        （AgentServer 下 controller.post_click 会崩）。
        confirm_node 配成空串/None 可跳过第三步，留作兜底。
        """
        dialog_timeout = float(cfg.get("dialog_timeout", 5))
        steps = (
            (cfg.get("exit_node", "ErrorExit"), 2.0),
            (cfg.get("restart_node", "ClickRestart"), dialog_timeout),
            (cfg.get("confirm_node", "Confirm"), dialog_timeout),
        )

        done = []
        for node, timeout in steps:
            if not node:
                continue
            detail = self._wait_for(context, node, timeout)
            if detail is None:
                prefix = " → ".join(done) if done else "无"
                print(
                    f"[abyss_align] 未等到 {node}，重开中止（已执行: {prefix}）",
                    flush=True,
                )
                return False
            context.run_action(node, detail.box)
            done.append(node)

        print(f"[abyss_align] 已调用 {' → '.join(done)} 重开", flush=True)

        ready_node = cfg.get("ready_node", "AbyssAlign")
        deadline = time.time() + float(cfg.get("ready_timeout", 15))
        while time.time() < deadline:
            time.sleep(0.5)
            if self._see(context, ready_node):
                print("[abyss_align] 重开完成，已回到准备界面", flush=True)
                return True
        print("[abyss_align] 重开等待超时，继续尝试", flush=True)
        return True

    # endregion

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # 任何异常都显式返回 False：ctypes 回调会吞异常，若不拦会被框架当成“动作成功”
        try:
            return self._run(context, argv)
        except Exception as exc:
            print(f"[abyss_align] 异常终止: {exc!r}", flush=True)
            return False

    def _run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        param = json.loads(argv.custom_action_param or "{}")
        restart = param.get("restart") or {}
        max_restarts = int(restart.get("max_times", 0)) if restart.get("enabled", True) else 0

        # 首次尝试 + 每次失败后重开再来一轮
        for attempt in range(max_restarts + 1):
            if self._align_once(context, param):
                return True
            if attempt < max_restarts:
                print(f"[abyss_align] 第 {attempt + 1} 轮对齐失败，重开本次深渊", flush=True)
                if not self._restart(context, restart):
                    return False
            else:
                print(f"[abyss_align] 已重开 {max_restarts} 次仍未开启，放弃", flush=True)
                return False
        return False

    def _align_once(self, context: Context, param: dict) -> bool:
        """一轮完整对齐：抬视角 → 右转对准 → 前进 → 微调若干次。"""
        view_up = param.get("view_up", {})
        view_right = param.get("view_right", {})
        forward = param.get("forward", {})
        step = param.get("step", {})
        icon_node = param.get("icon", "InstructionIcon")
        target_node = param.get("target", "AbyssStart")

        # 0. 已经能看到「开始深渊」就别动（重试/重开后已在按钮前的情况）
        if self._see(context, target_node):
            print("[abyss_align] 已看到「开始深渊」，无需移动", flush=True)
            return True

        # 1. 抬视角
        if view_up:
            self._move_view_up(context, view_up)

        # 2. 右转直到看到入口图标
        max_right = int(view_right.get("max_times", 45))
        aligned = False
        for i in range(max_right):
            if self._see(context, icon_node):
                aligned = True
                print(f"[abyss_align] 右转 {i} 次后看到入口图标", flush=True)
                break
            self._move_view_right(context, view_right)
        if not aligned:
            print(f"[abyss_align] 右转 {max_right} 次仍未看到入口图标，继续前进", flush=True)

        # 3. 前进约 1.5s
        fw_begin = forward.get("begin", [208, 533])
        fw_end = forward.get("end", [230, 440])
        if forward:
            self._move_forward(context, fw_begin, fw_end, int(forward.get("duration", 1500)))
            self._settle(context, forward, 300)

        # 4. 未见「开始深渊」就每次前进一小步再查（复用 forward 的坐标）
        if self._see(context, target_node):
            print("[abyss_align] 已看到「开始深渊」", flush=True)
            return True

        st_duration = int(step.get("duration", 200))
        max_step = int(step.get("max_times", 5))
        for i in range(max_step):
            self._move_forward(context, fw_begin, fw_end, st_duration)
            self._settle(context, step, 200)
            if self._see(context, target_node):
                print(f"[abyss_align] 前进 {i + 1} 小步后看到「开始深渊」", flush=True)
                return True

        print(f"[abyss_align] 微调 {max_step} 次仍未看到「开始深渊」", flush=True)
        return False
