import json
import random
import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


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
    """[x, y] 原样返回；[x, y, w, h] 返回框内一点（靠近中心概率更高）。"""
    if len(box) == 2:
        return int(box[0]), int(box[1])

    x, y, w, h = (int(v) for v in box)
    px = random.gauss(x + w / 2, max(w, 1) / 4)
    py = random.gauss(y + h / 2, max(h, 1) / 4)
    px = min(max(px, x), x + w - 1)
    py = min(max(py, y), y + h - 1)
    return int(px), int(py)


def _center(box) -> tuple[int, int]:
    x, y, w, h = (int(v) for v in box)
    return x + w // 2, y + h // 2


@AgentServer.custom_action("abyss_align")
class AbyssAlignAction(CustomAction):
    """深渊入场对齐：长移（end.x 逐档 +step）→ 微调 → 检查「开始深渊」。

    没看到「开始深渊」就点「异常退出」→「重开」，回到准备界面后用下一档 end.x 再试。
    任意一档成功即返回 True，由 pipeline 的 next 继续点「开始深渊」走正常流程。
    """

    def _recognize(self, context: Context, name: str, timeout: float):
        """截图并在 timeout 秒内反复识别 name，命中返回 detail，否则返回 None。"""
        ctrl = context.tasker.controller
        deadline = time.time() + timeout
        while True:
            image = ctrl.post_screencap().wait().get()
            detail = context.run_recognition(name, image)
            if detail is not None and detail.hit:
                return detail
            if time.time() >= deadline:
                return None
            time.sleep(0.3)

    def _swipe(self, context: Context, begin, end, duration: int, randomize_end: bool = False):
        bx, by = _point(begin)
        # 终点必须是确定点：阶梯靠 end.x + step 递进，随机化会让档位失去意义
        ex, ey = _point(end) if randomize_end else _center(end)
        context.tasker.controller.post_swipe(bx, by, ex, ey, duration).wait()

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        param = json.loads(argv.custom_action_param or "{}")
        begin = param.get("begin", [207, 529, 22, 18])
        end = param.get("end", [285, 455, 15, 12])
        step = int(param.get("step", 10))
        tries = int(param.get("tries", 5))
        duration = int(param.get("duration", 1600))
        settle = float(param.get("settle", 1.0))
        fine = param.get("fine", {})

        base_x, base_y = int(end[0]), int(end[1])
        end_tail = [int(v) for v in end[2:]] or [1, 1]
        ctrl = context.tasker.controller

        for i in range(tries):
            end_x = base_x + i * step
            self._swipe(context, begin, [end_x, base_y, *end_tail], duration)
            if fine:
                self._swipe(
                    context,
                    fine.get("begin", begin),
                    fine.get("end", end),
                    int(fine.get("duration", 160)),
                )

            time.sleep(settle)
            if self._recognize(context, "AbyssStart", 0.5):
                print(f"[abyss_align] 第 {i + 1} 档 end.x={end_x} 成功", flush=True)
                return True

            print(f"[abyss_align] 第 {i + 1} 档 end.x={end_x} 失败，重开", flush=True)

            detail = self._recognize(context, "ErrorExit", 2.0)
            if detail is None or detail.box is None:
                print("[abyss_align] 未找到异常退出按钮，放弃", flush=True)
                return False
            ctrl.post_click(*_center(detail.box)).wait()
            time.sleep(settle)

            detail = self._recognize(context, "ClickRestart", 5.0)
            if detail is None or detail.box is None:
                print("[abyss_align] 未找到重开按钮，放弃", flush=True)
                return False
            ctrl.post_click(*_center(detail.box)).wait()

            # 等重开回到准备界面（摇杆出现）
            if self._recognize(context, "AbyssAlign", 10.0) is None:
                print("[abyss_align] 重开后未回到准备界面，放弃", flush=True)
                return False

        print(f"[abyss_align] {tries} 档全部失败", flush=True)
        return False

