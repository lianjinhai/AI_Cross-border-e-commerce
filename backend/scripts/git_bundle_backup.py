"""Git 单文件归档备份（P0-4）：把整个仓库打成一个可离线恢复的 bundle。

为什么需要它（背景）：本仓库曾发生过一次 ``.git`` 对象库被清空的真实事故——
``refs/heads/`` 丢失、对象只剩 8 个松散对象、无 pack、无远端，最后靠**回收站 +
reflog** 才把 1297 个对象救回来。能救回来属于运气；正确做法是让历史在**仓库之外**
也有一份可验证的副本。

``git bundle`` 把全部引用与对象打包成**单个文件**，可在任意机器上
``git clone <bundle>`` 恢复完整历史，且不需要网络与远端服务。

用法（在 backend 目录下执行）：
    python scripts/git_bundle_backup.py                 # 备份到仓库根 _erp_backups/
    python scripts/git_bundle_backup.py --out D:/gitbak # 指定输出目录（可指向移动盘）
    python scripts/git_bundle_backup.py --verify-only   # 只校验最近一个 bundle
    python scripts/git_bundle_backup.py --keep 14       # 保留最近 14 个（默认保留全部）

安全边界：
    - **只读仓库**：仅执行 ``git bundle create`` / ``git bundle verify`` / ``git rev-parse``，
      不 checkout、不 reset、不改引用、不动工作区。
    - ``--keep`` 是**唯一**的删除入口，且只删除目标目录内匹配 ``erp-*.bundle`` 的文件，
      删除前逐条打印；不带 ``--keep`` 时绝不删除任何文件。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DEFAULT_OUT = REPO_DIR / "_erp_backups"
BUNDLE_GLOB = "erp-*.bundle"
_BUNDLE_NAME = re.compile(r"^erp-\d{8}-\d{6}\.bundle$")


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(REPO_DIR), capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result


def _require_repo() -> str:
    result = _git("rev-parse", "--git-dir", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{REPO_DIR} 不是 Git 仓库（{result.stderr.strip()}）")
    head = _git("rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        raise RuntimeError("HEAD 不可解析：仓库可能已损坏，请先修复再备份")
    return head.stdout.strip()


def create_bundle(out_dir: Path) -> Path:
    _require_repo()   # 先确认仓库与 HEAD 可解析，避免产出不可恢复的空壳 bundle
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"erp-{stamp}.bundle"
    # --all 打包全部引用（含分支与 tag），保证可完整重建历史。
    _git("bundle", "create", str(target), "--all")
    return target


def verify_bundle(path: Path) -> tuple[bool, str]:
    """:returns: (是否通过, 说明)。bundle verify 会校验对象完整性与前置引用。"""
    if not path.exists():
        return False, f"文件不存在：{path}"
    result = _git("bundle", "verify", str(path), check=False)
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail


def latest_bundle(out_dir: Path) -> Path | None:
    if not out_dir.is_dir():
        return None
    items = sorted(p for p in out_dir.glob(BUNDLE_GLOB) if _BUNDLE_NAME.match(p.name))
    return items[-1] if items else None


def prune(out_dir: Path, keep: int) -> list[Path]:
    """删除最旧的 bundle，仅保留最近 ``keep`` 个（唯一删除入口，逐条打印）。"""
    items = sorted(p for p in out_dir.glob(BUNDLE_GLOB) if _BUNDLE_NAME.match(p.name))
    removed = []
    for path in items[:-keep] if keep > 0 else []:
        print(f"[prune] 删除旧备份：{path.name}")
        path.unlink()
        removed.append(path)
    return removed


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Git bundle 单文件归档备份")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认 _erp_backups/）")
    parser.add_argument("--keep", type=int, default=0,
                        help="保留最近 N 个 bundle（默认 0 = 不删除任何文件）")
    parser.add_argument("--verify-only", action="store_true", help="只校验最近一个 bundle")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    out_dir = Path(args.out).expanduser().resolve()
    try:
        if args.verify_only:
            target = latest_bundle(out_dir)
            if target is None:
                print(f"未在 {out_dir} 找到 bundle，无法校验")
                return 2
            ok, detail = verify_bundle(target)
            print(f"{'OK' if ok else 'FAIL'} {target}")
            print(detail)
            return 0 if ok else 2

        target = create_bundle(out_dir)
        size_mb = target.stat().st_size / 1024 / 1024
        ok, detail = verify_bundle(target)
        print(f"已创建 {target}（{size_mb:.1f} MB）")
        print(f"校验：{'通过' if ok else '失败'}——{detail.splitlines()[0] if detail else ''}")
        if not ok:
            return 2
        if args.keep > 0:
            prune(out_dir, args.keep)
        print("提示：bundle 可离线恢复：git clone <bundle> <目标目录>")
        return 0
    except RuntimeError as exc:
        print(f"备份失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
