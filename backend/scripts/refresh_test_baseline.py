"""刷新测试基线（单一事实源）：采集后端/前端用例数，写入 ``docs/baseline.json``。

为什么需要本脚本
    测试基线数字此前**手工维护在 6 个文档里**（`AGENTS.md` 2 处、
    `CONTRIBUTING.md` 2 处、规范 §8 与 §9.4、`CONTRACT.md`、
    `WORKSPACE_MIGRATION_PROGRESS.md`、`项目介绍与功能地图.md`）。实测结果是
    它们**同时过期且互不一致**：同一时点文档里并存 199 / 257 / 264 / 179 / 165
    五个不同的「当前基线」，而真实值是 291。人工抄写必然漂移，且漂移后
    无人察觉——因为「数字看起来合理」。

    根治办法：把数字收敛到**单一事实源** ``docs/baseline.json``，由本脚本
    从真实测试采集；文档正文改写成不含数字的引用形式。校验由
    ``scripts/check_docs_consistency.py`` 在 CI 里强制执行。

用法（在 backend 目录下执行）
    python scripts/refresh_test_baseline.py            # 采集并写入
    python scripts/refresh_test_baseline.py --check    # 只比对，不写入（CI 用）

退出码
    0 = 一致（或已成功写入）
    2 = ``--check`` 模式下与实测不一致
    3 = 用法错误 / 采集失败

安全性
    只读采集：``pytest --collect-only`` **不执行任何用例**、不建库、不写盘
    （实测确认零新增文件）；前端用 vitest 的 json reporter 写临时文件后立即删除。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.dont_write_bytecode = True

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
BASELINE_PATH = REPO_DIR / "docs" / "baseline.json"


class BaselineError(RuntimeError):
    """采集/环境错误（退出码 3）。"""


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # 子进程必须显式 UTF-8：Windows 默认按本地代码页解码，中文输出会抛
    # UnicodeDecodeError，导致 stdout 变 None、真实报错原因丢失。
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def collect_backend() -> dict:
    """采集后端用例数（只收集不执行，零副作用）。"""
    result = _run([sys.executable, "-m", "pytest", "--collect-only", "-q"], BACKEND_DIR)
    if result.returncode != 0:
        raise BaselineError("pytest --collect-only 失败：\n%s" % (result.stdout or "")[-1500:])
    ids = [line for line in result.stdout.splitlines()
           if line.startswith("tests/") and "::" in line]
    if not ids:
        raise BaselineError("未能从 pytest 输出解析出任何用例；输出片段：\n%s"
                            % (result.stdout or "")[-800:])
    return {"tests": len(ids), "files": len({i.split("::")[0] for i in ids})}


def collect_frontend() -> dict:
    """采集前端用例数（vitest json reporter）。"""
    frontend = REPO_DIR / "frontend"
    if not (frontend / "package.json").exists():
        raise BaselineError("未找到 frontend/package.json")
    # 为什么不用 `npx`：Windows 上 npx 只有 .ps1/.cmd 包装，subprocess 直接调用
    # 会抛 FileNotFoundError（WinError 2，实测）；且 npx 可能联网解析包版本。
    # 改用 `node node_modules/vitest/vitest.mjs`，跨平台一致且完全离线。
    vitest_entry = frontend / "node_modules" / "vitest" / "vitest.mjs"
    if not vitest_entry.exists():
        raise BaselineError(
            "未找到 %s；请先在 frontend/ 执行 `npm ci`" % vitest_entry)
    node = shutil.which("node")
    if not node:
        raise BaselineError("PATH 中找不到 node（前端基线采集需要它）")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "vitest.json"
        result = _run([node, vitest_entry.as_posix(), "run", "--reporter=json",
                       "--outputFile=%s" % out.as_posix()], frontend)
        if not out.exists():
            raise BaselineError("vitest 未生成报告（exit=%d）：\n%s"
                                % (result.returncode, (result.stdout or "")[-1200:]))
        data = json.loads(out.read_text(encoding="utf-8"))
    total = data.get("numTotalTests")
    if not isinstance(total, int) or total <= 0:
        raise BaselineError("vitest 报告的 numTotalTests 异常：%r" % total)
    return {"tests": total, "files": len(data.get("testResults") or [])}


def build() -> dict:
    backend = collect_backend()
    frontend = collect_frontend()
    return {
        "_comment": "测试基线单一事实源。由 backend/scripts/refresh_test_baseline.py 生成，"
                    "禁止手工编辑。文档正文不得再写具体数字（见 CODE_AND_DIRECTORY_STANDARD.md §10）。",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "backend": backend,
        "frontend": frontend,
    }


def _comparable(data: dict) -> dict:
    return {k: data.get(k) for k in ("backend", "frontend")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="刷新/校验测试基线单一事实源。")
    parser.add_argument("--check", action="store_true",
                        help="只比对不写入；不一致时退出码 2（CI 用）")
    args = parser.parse_args(argv)
    try:
        fresh = build()
    except BaselineError as exc:
        print("baseline error: %s" % exc, file=sys.stderr)
        return 3

    if args.check:
        if not BASELINE_PATH.exists():
            print("baseline error: %s 不存在，请先运行 refresh_test_baseline.py"
                  % BASELINE_PATH, file=sys.stderr)
            return 3
        saved = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        if _comparable(saved) == _comparable(fresh):
            print("baseline OK: backend %d / frontend %d"
                  % (fresh["backend"]["tests"], fresh["frontend"]["tests"]))
            return 0
        print("baseline 与实测不一致（请运行 refresh_test_baseline.py 更新）：", file=sys.stderr)
        print("  记录: %s" % json.dumps(_comparable(saved), ensure_ascii=False), file=sys.stderr)
        print("  实测: %s" % json.dumps(_comparable(fresh), ensure_ascii=False), file=sys.stderr)
        return 2

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    print("baseline 已写入 %s" % BASELINE_PATH)
    print("  backend  %d passed / %d 文件" % (fresh["backend"]["tests"], fresh["backend"]["files"]))
    print("  frontend %d passed / %d 文件" % (fresh["frontend"]["tests"], fresh["frontend"]["files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
