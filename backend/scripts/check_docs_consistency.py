"""文档一致性校验器：拦住「文档与代码脱节」（规范 Doc-5）。

为什么需要本脚本
    规范 Doc-5 要求「文档中引用的路径、字段名、状态值必须可被检索验证」，
    但此前**没有任何工具执行它**，只能靠人工记忆。实测后果：

    1. **基线数字同时过期且互不一致**——同一时点 6 个文档里并存
       199 / 257 / 264 / 179 / 165 五个不同的「当前基线」，真实值是 291。
    2. **已完成的事项仍标「未完成」**——`WORKSPACE_MIGRATION_PROGRESS.md` 的
       R-03 写「40 张表缺外键 / 未完成」，实测 48/48 全部受约束（DEBT-03 早已关闭）。
    3. **失效路径引用**——文档里指向已删除/改名的文件。

    这类漂移的共同特征是「数字/状态看起来合理」，人工评审必然漏掉。

检查项
    A. 基线数字一致：活文档中出现的 `N passed` 必须与 `docs/baseline.json` 一致。
    B. 路径引用有效：反引号里的文件路径必须能在仓库中解析。
    C. 台账状态自洽：规范 §11 中标记「已完成」的债务，不得在其它活文档里
       仍被描述为「未完成」。

豁免机制（防止校验器变成噪音后被整体关掉）
    - 行内标记 ``docs-ok``：该行豁免（用于**历史性**记录，如 DECISIONS 里
      「当时实测 257 passed」这类不可改写的史实）。
    - 文件级豁免 ``HISTORICAL_DOCS``：归档目录与决策记录天然含历史数字。

用法（在 backend 目录下执行）
    python scripts/check_docs_consistency.py          # 全部检查
    python scripts/check_docs_consistency.py --json   # 机器可读输出

退出码
    0 = 无问题
    2 = 存在 P0 问题（基线数字不一致 / 台账状态矛盾）
    3 = 用法错误 / 基线文件缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
BASELINE_PATH = REPO_DIR / "docs" / "baseline.json"

# 天然包含历史数字的文档：决策记录（史实不可改写）与归档目录。
HISTORICAL_DOCS = ("docs/DECISIONS.md", "docs/archive/", "docs/子代理实施索引-",
                   "docs/adr/")
# 活文档：基线数字必须与 baseline.json 一致。
LIVE_DOCS = ("AGENTS.md", "CONTRIBUTING.md", "docs/CODE_AND_DIRECTORY_STANDARD.md",
             "docs/CONTRACT.md", "docs/WORKSPACE_MIGRATION_PROGRESS.md",
             "docs/项目介绍与功能地图.md", "docs/backup_restore_runbook.md",
             "docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md")

# 解析路径引用时尝试的根目录（文档里的相对路径口径不统一）
PATH_ROOTS = (Path("."), Path("backend"), Path("backend/app"), Path("backend/tests"),
              Path("backend/scripts"), Path("backend/migrations/versions"),
              Path("frontend"), Path("frontend/src"), Path("frontend/tests"), Path("docs"))

_PATH_REF = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:py|md|vue|js|json|toml|txt|yml|yaml|sh|css|html))`")
# 匹配「N passed」；允许 `**264 passed**` 这类加粗包裹
_PASSED = re.compile(r"(\d+)\s*passed")

# 历史叙述中引用的**已删除临时文件**：这些引用是正确的历史记录（描述当时
# 存在的问题），不是失效引用。用精确名单而非通配，避免放过真正的新失效引用。
_HISTORICAL_TEMP_REFS = {
    "_h.py", "_w.py", "_chk.py", "_cm.txt", "_commit_msg.txt",
    "test_api.py.orig",
}


def _live_docs() -> list[Path]:
    docs = []
    for rel in LIVE_DOCS:
        path = REPO_DIR / rel
        if path.exists():
            docs.append(path)
    return docs


def check_baseline_numbers(baseline: dict) -> list[str]:
    """A：活文档里出现的 `N passed` 必须与单一事实源一致。"""
    expected = {baseline["backend"]["tests"], baseline["frontend"]["tests"]}
    problems = []
    for doc in _live_docs():
        rel = doc.relative_to(REPO_DIR).as_posix()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "docs-ok" in line:
                continue
            for value in _PASSED.findall(line):
                if int(value) not in expected:
                    problems.append(
                        "%s:%d 基线数字 %s 与 docs/baseline.json 不一致（期望 %s）：%s"
                        % (rel, lineno, value, sorted(expected), line.strip()[:110]))
    return problems


def check_paths() -> list[str]:
    """B：反引号中的文件路径必须能解析。"""
    known = set()
    for path in REPO_DIR.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "node_modules" not in path.parts:
            known.add(path.name)
    problems = []
    # 去重：`LIVE_DOCS` 里已含 docs/*.md 中的若干篇，直接用 `+` 拼接会让这些
    # 文档被扫描两次，同一问题报两遍（实测重复率 100%）。按解析后的绝对路径去重。
    targets = {p.resolve() for p in _live_docs()}
    targets |= {p.resolve() for p in (REPO_DIR / "docs").glob("*.md")}
    for doc in targets:
        rel = doc.relative_to(REPO_DIR).as_posix()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "docs-ok" in line:
                continue
            for ref in sorted(set(_PATH_REF.findall(line))):
                # 跳过示意性路径（示例占位符）
                if any(t in ref for t in ("YYYYmmdd", "a/b/c.py", "a/b/pkg/")):
                    continue
                if ref in _HISTORICAL_TEMP_REFS:
                    continue
                if any((REPO_DIR / root / ref).exists() for root in PATH_ROOTS):
                    continue
                if Path(ref).name in known:
                    continue
                problems.append("%s:%d 路径引用失效：%s" % (rel, lineno, ref))
    return problems


def check_ledger_status() -> list[str]:
    """C：规范 §11 标记「已完成」的债务，不得在其它活文档里仍写「未完成」。"""
    standard = REPO_DIR / "docs" / "CODE_AND_DIRECTORY_STANDARD.md"
    if not standard.exists():
        return []
    done_ids = set()
    for line in standard.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(DEBT-\d+)\s*\|", line)
        if match and "已完成" in line:
            done_ids.add(match.group(1))
    if not done_ids:
        return []
    problems = []
    for doc in _live_docs():
        rel = doc.relative_to(REPO_DIR).as_posix()
        if rel == "docs/CODE_AND_DIRECTORY_STANDARD.md":
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "docs-ok" in line:
                continue
            for debt in sorted(done_ids):
                if debt in line and "未完成" in line:
                    problems.append(
                        "%s:%d 台账状态矛盾：%s 在规范 §11 已标「已完成」，此处仍写「未完成」"
                        % (rel, lineno, debt))
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="文档一致性校验（规范 Doc-5）。")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    if not BASELINE_PATH.exists():
        print("docs error: %s 不存在，请先运行 scripts/refresh_test_baseline.py"
              % BASELINE_PATH, file=sys.stderr)
        return 3
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    report = {
        "baseline_numbers": check_baseline_numbers(baseline),
        "path_refs": check_paths(),
        "ledger_status": check_ledger_status(),
        "baseline": {"backend": baseline["backend"]["tests"],
                     "frontend": baseline["frontend"]["tests"]},
    }
    total = sum(len(report[key]) for key in
                ("baseline_numbers", "path_refs", "ledger_status"))
    report["total"] = total

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("文档一致性校验（基线：后端 %d / 前端 %d）"
              % (report["baseline"]["backend"], report["baseline"]["frontend"]))
        print("=" * 74)
        for key, title in (("baseline_numbers", "A. 基线数字一致"),
                           ("path_refs", "B. 路径引用有效"),
                           ("ledger_status", "C. 台账状态自洽")):
            items = report[key]
            print("\n[%s] %s" % ("PASS" if not items else "FAIL(%d)" % len(items), title))
            for item in items[:40]:
                print("   ", item)
            if len(items) > 40:
                print("    ...（另有 %d 项）" % (len(items) - 40))
        print("\n" + "=" * 74)
        print("exit_code=%d%s" % (2 if total else 0,
                                  "（存在 P0 问题）" if total else ""))
    return 2 if total else 0


if __name__ == "__main__":
    sys.exit(main())
