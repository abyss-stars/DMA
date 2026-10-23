import os
import platform
import sys
from pathlib import Path

# 发布包里的 agent 不自带 maa/bin（省 ~86MB），改用安装目录 runtimes/<rid>/native 下的框架库。
# 必须在 import maa 之前设置，maa/__init__.py 会读这个环境变量决定从哪加载。
_RIDS = {
    ("win32", "AMD64"): "win-x64",
    ("win32", "ARM64"): "win-arm64",
    ("darwin", "x86_64"): "osx-x64",
    ("darwin", "arm64"): "osx-arm64",
    ("linux", "x86_64"): "linux-x64",
    ("linux", "aarch64"): "linux-arm64",
}
_rid = _RIDS.get((sys.platform, platform.machine()))
if _rid and not os.environ.get("MAAFW_BINARY_PATH"):
    _native = Path(__file__).resolve().parent.parent / "runtimes" / _rid / "native"
    if _native.exists():
        os.environ["MAAFW_BINARY_PATH"] = str(_native)

from maa.agent.agent_server import AgentServer  # noqa: E402

import my_action  # noqa: E402,F401
import my_reco  # noqa: E402,F401


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
