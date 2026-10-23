"""把可移植的 Python 解释器 + MaaFw 依赖装进 install/，供 AgentServer 使用。

用法：
    python tools/setup_agent_python.py --install-dir install --os win --arch x86_64

说明：
- 解释器来自 astral-sh/python-build-standalone（install_only 包，可整体搬移），版本与发布 tag 都写死在下方常量里；
- MaaFw 只装纯 Python 部分：``maa/bin``（约 86MB 原生库）和 ``MaaAgentBinary``（约 12MB，安装包 libs/ 下已有）
  会被删掉，agent 启动时由 ``agent/main.py`` 把 ``MAAFW_BINARY_PATH`` 指向 ``runtimes/<rid>/native``；
- 最后把 ``interface.json`` 的 ``agent.child_exec`` 改为包内相对路径；
- 目标平台是 android 时整步跳过（安卓包不跑 Agent）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PY_BUILD_RELEASE = "20261021"
PY_VERSION = "3.12.15"
MAAFW_VERSION = "5.14.3"

# (os, arch) -> (standalone triple, wheel platform tag, 解释器相对路径, site-packages 相对路径)
TARGETS = {
    ("win", "x86_64"): (
        "x86_64-pc-windows-msvc",
        ["win_amd64"],
        "python/python.exe",
        "python/Lib/site-packages",
    ),
    ("win", "aarch64"): (
        "aarch64-pc-windows-msvc",
        ["win_arm64"],
        "python/python.exe",
        "python/Lib/site-packages",
    ),
    ("macos", "x86_64"): (
        "x86_64-apple-darwin",
        ["macosx_14_0_x86_64", "macosx_13_0_x86_64", "macosx_12_0_x86_64",
         "macosx_11_0_x86_64", "macosx_10_13_x86_64", "macosx_10_9_x86_64"],
        "python/bin/python3",
        "python/lib/python3.12/site-packages",
    ),
    ("macos", "aarch64"): (
        "aarch64-apple-darwin",
        ["macosx_14_0_arm64", "macosx_13_0_arm64", "macosx_12_0_arm64", "macosx_11_0_arm64"],
        "python/bin/python3",
        "python/lib/python3.12/site-packages",
    ),
    ("linux", "x86_64"): (
        "x86_64-unknown-linux-gnu",
        ["manylinux2014_x86_64", "manylinux_2_28_x86_64", "manylinux_2_27_x86_64",
         "manylinux_2_17_x86_64"],
        "python/bin/python3",
        "python/lib/python3.12/site-packages",
    ),
    ("linux", "aarch64"): (
        "aarch64-unknown-linux-gnu",
        ["manylinux2014_aarch64", "manylinux_2_28_aarch64", "manylinux_2_27_aarch64",
         "manylinux_2_17_aarch64"],
        "python/bin/python3",
        "python/lib/python3.12/site-packages",
    ),
}

# 发布包里用不到的大块头
PRUNE_STDLIB = [
    "Lib/test",
    "Lib/idlelib",
    "Lib/tkinter",
    "Lib/turtledemo",
    "Lib/lib2to3",
    "Lib/ensurepip",
    "Lib/site-packages/pip",
    "Lib/site-packages/pip-*",
    "Lib/site-packages/setuptools",
    "Lib/site-packages/setuptools-*",
    "Lib/site-packages/pkg_resources",
    "include",
    "share",
]
PRUNE_STDLIB_UNIX = [
    "lib/python3.12/test",
    "lib/python3.12/idlelib",
    "lib/python3.12/tkinter",
    "lib/python3.12/turtledemo",
    "lib/python3.12/lib2to3",
    "lib/python3.12/ensurepip",
    "lib/python3.12/site-packages/pip",
    "lib/python3.12/site-packages/pip-*",
    "lib/python3.12/site-packages/setuptools",
    "lib/python3.12/site-packages/setuptools-*",
    "lib/python3.12/site-packages/pkg_resources",
    "include",
    "share",
]


def log(msg: str) -> None:
    print(f"[setup-agent-python] {msg}", flush=True)


def remove(path: Path) -> int:
    """删除文件或目录，返回释放的字节数。"""
    if not path.exists():
        return 0
    if path.is_dir():
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        shutil.rmtree(path)
    else:
        size = path.stat().st_size
        path.unlink()
    return size


def download(url: str, dest: Path) -> None:
    log(f"download {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "dma-setup-agent-python"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def install_python(install_dir: Path, triple: str) -> None:
    target = install_dir / "python"
    if target.exists():
        shutil.rmtree(target)

    url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        f"{PY_BUILD_RELEASE}/cpython-{PY_VERSION}+{PY_BUILD_RELEASE}-{triple}-install_only.tar.gz"
    )
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "python.tar.gz"
        download(url, archive)
        log("extract python")
        with tarfile.open(archive, "r:gz") as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp, filter="data")
            else:  # Python < 3.12
                tf.extractall(tmp)
        extracted = Path(tmp) / "python"
        if not extracted.is_dir():
            raise RuntimeError(f"unexpected archive layout: {extracted} not found")
        shutil.move(str(extracted), str(target))


def install_packages(site_packages: Path, platform_tags: list[str] | None, maafw_version: str) -> None:
    site_packages.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--upgrade",
        "--target",
        str(site_packages),
        "--only-binary=:all:",
        f"MaaFw=={maafw_version}",
    ]
    if platform_tags:
        for tag in platform_tags:
            cmd += ["--platform", tag]
        cmd += [
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--abi",
            "none",
        ]
    log("pip install MaaFw " + " ".join(cmd[3:]))
    subprocess.run(cmd, check=True)


def prune(python_dir: Path, site_packages: Path, unix: bool) -> None:
    freed = 0
    # agent 复用安装包的 runtimes 与 libs，不重复带原生库
    freed += remove(site_packages / "maa" / "bin")
    freed += remove(site_packages / "MaaAgentBinary")
    for d in site_packages.glob("MaaAgentBinary-*.dist-info"):
        freed += remove(d)
    for d in site_packages.glob("bin"):
        freed += remove(d)

    patterns = PRUNE_STDLIB_UNIX if unix else PRUNE_STDLIB
    for pattern in patterns:
        for path in python_dir.glob(pattern):
            freed += remove(path)

    # 调试符号、Tcl/Tk（tkinter 已删）、venv 脚手架、numpy 自带测试
    for pdb in python_dir.rglob("*.pdb"):
        freed += remove(pdb)
    for pattern in (
        "Lib/tcl*",
        "Lib/tk*",
        "Lib/venv",
        "DLLs/tcl*.dll",
        "DLLs/tk*.dll",
        "DLLs/_tkinter.pyd",
    ):
        for path in python_dir.glob(pattern):
            freed += remove(path)
    for tests in (site_packages / "numpy").rglob("tests"):
        freed += remove(tests)

    log(f"pruned {freed / 1024 / 1024:.1f} MB")


def patch_interface(install_dir: Path, python_exec: str) -> None:
    interface_path = install_dir / "interface.json"
    try:
        import jsonc  # type: ignore
    except ModuleNotFoundError:
        raise SystemExit(
            "missing dependency 'json-with-comments'; run:\n"
            "  python -m pip install -r tools/requirements.txt"
        )

    with open(interface_path, "r", encoding="utf-8") as f:
        interface = jsonc.load(f)

    interface["agent"] = {
        "child_exec": "./" + python_exec,
        "child_args": ["./agent/main.py"],
    }
    with open(interface_path, "w", encoding="utf-8") as f:
        jsonc.dump(interface, f, ensure_ascii=False, indent=4)
    log(f"interface.json agent.child_exec -> ./{python_exec}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", default="install")
    parser.add_argument("--os", required=True, dest="os_name")
    parser.add_argument("--arch", required=True)
    parser.add_argument("--maafw-version", default=MAAFW_VERSION)
    parser.add_argument("--skip-python", action="store_true", help="复用已解压的 install/python")
    parser.add_argument("--skip-pip", action="store_true", help="复用已装好的 site-packages")
    args = parser.parse_args()

    if args.os_name == "android":
        log("android: 跳过 Agent Python 打包")
        return

    key = (args.os_name, args.arch)
    if key not in TARGETS:
        raise SystemExit(f"unsupported target: {key}")
    triple, platform_tags, python_exec, site_packages_rel = TARGETS[key]

    install_dir = Path(args.install_dir).resolve()
    if not install_dir.is_dir():
        raise SystemExit(f"install dir not found: {install_dir}")

    if not args.skip_python:
        install_python(install_dir, triple)
    site_packages = install_dir / site_packages_rel
    if not args.skip_pip:
        install_packages(site_packages, platform_tags, args.maafw_version)

    python_dir = install_dir / "python"
    prune(python_dir, site_packages, unix=args.os_name != "win")
    patch_interface(install_dir, python_exec)

    total = sum(f.stat().st_size for f in python_dir.rglob("*") if f.is_file())
    log(f"python bundle: {total / 1024 / 1024:.1f} MB -> {python_dir}")


if __name__ == "__main__":
    main()


