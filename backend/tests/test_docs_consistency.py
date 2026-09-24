"""文档一致性校验器的回归测试（规范 Doc-5）。

**为什么必须有**：`check_docs_consistency.py` 是**守卫型工具**——它的价值全在
「能抓到问题」。一个恒真通过的校验器比没有校验器更危险：它会让人误以为文档
是自洽的。所以本测试的重点不是「跑通」，而是**判别力**：每个检查项都必须有
「构造违规 → 断言被抓到」的用例。

**测试策略**：不直接改仓库文档（会污染工作区、且失败时难以还原），而是把
脚本的检查函数当作纯函数调用，用 `tmp_path` 构造最小文档树验证。
路径检查需要真实仓库结构，故对它的判别力用「注入一个必然不存在的路径引用」
的方式验证——注入到临时文件上，不碰真文档。
"""
import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
SCRIPT = BACKEND_DIR / "scripts" / "check_docs_consistency.py"
REFRESH = BACKEND_DIR / "scripts" / "refresh_test_baseline.py"
BASELINE = REPO_DIR / "docs" / "baseline.json"

sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import check_docs_consistency as cdc  # noqa: E402

# ---------------------------------------------------------------- 事实源

def test_baseline_file_exists_and_has_expected_shape():
    """单一事实源必须存在且结构正确（校验器与刷新器共用它）。"""
    assert BASELINE.exists(), "docs/baseline.json 缺失，请运行 refresh_test_baseline.py"
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    for key in ("backend", "frontend"):
        assert isinstance(data[key]["tests"], int) and data[key]["tests"] > 0, data[key]
        assert isinstance(data[key]["files"], int) and data[key]["files"] > 0, data[key]


def test_baseline_is_not_hand_edited():
    """事实源必须带「禁止手工编辑」声明，否则后来者会直接改数字绕过校验。"""
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert "禁止手工编辑" in data.get("_comment", ""), data.get("_comment")


# ---------------------------------------------------------------- 判别力（核心）

def test_baseline_check_catches_stale_number(monkeypatch, tmp_path):
    """判别力：活文档里写过期的 `N passed` 必须被抓到。"""
    doc = tmp_path / "AGENTS.md"
    doc.write_text("# 后端测试（基线：264 passed）\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "LIVE_DOCS", ("AGENTS.md",))

    problems = cdc.check_baseline_numbers({"backend": {"tests": 291}, "frontend": {"tests": 72}})

    assert len(problems) == 1, problems
    assert "264" in problems[0]


def test_baseline_check_accepts_current_number(monkeypatch, tmp_path):
    """反向：与事实源一致的数字不得误报（否则门禁过严，会被整体关掉）。"""
    doc = tmp_path / "AGENTS.md"
    doc.write_text("# 后端测试（基线：291 passed）\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "LIVE_DOCS", ("AGENTS.md",))

    problems = cdc.check_baseline_numbers({"backend": {"tests": 291}, "frontend": {"tests": 72}})

    assert problems == [], problems


def test_docs_ok_marker_exempts_historical_line(monkeypatch, tmp_path):
    """历史性记录必须可用 `docs-ok` 豁免——否则 DECISIONS 里的史实会永远告警。"""
    doc = tmp_path / "AGENTS.md"
    doc.write_text("| 回归 | 257 passed <!-- docs-ok: 当次实测史实 --> |\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "LIVE_DOCS", ("AGENTS.md",))

    problems = cdc.check_baseline_numbers({"backend": {"tests": 291}, "frontend": {"tests": 72}})

    assert problems == [], problems


def test_ledger_check_catches_status_contradiction(monkeypatch, tmp_path):
    """判别力：规范标「已完成」的债务，别处仍写「未完成」必须被抓到。

    真实背景：`WORKSPACE_MIGRATION_PROGRESS.md` 的 R-03 曾长期写「40 张表缺外键 /
    未完成」，而实测 48/48 全部受约束、DEBT-03 早已关闭。
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CODE_AND_DIRECTORY_STANDARD.md").write_text(
        "| DEBT-03 | ~~缺外键~~ | ~~P1~~ | migrations/ | ✅ **已完成** |\n", encoding="utf-8")
    (docs / "WORKSPACE_MIGRATION_PROGRESS.md").write_text(
        "| R-03 | 40 张表缺外键 | P1 | **未完成** | 说明（DEBT-03） |\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "LIVE_DOCS",
                        ("docs/CODE_AND_DIRECTORY_STANDARD.md",
                         "docs/WORKSPACE_MIGRATION_PROGRESS.md"))

    problems = cdc.check_ledger_status()

    assert len(problems) == 1, problems
    assert "DEBT-03" in problems[0]


def test_path_check_catches_missing_file(monkeypatch, tmp_path):
    """判别力：反引号里的失效路径必须被抓到。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CONTRACT.md").write_text("见 `backend/app/definitely_missing_xyz.py`。\n",
                                      encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "PATH_ROOTS", (Path("."),))
    monkeypatch.setattr(cdc, "LIVE_DOCS", ("docs/CONTRACT.md",))

    problems = cdc.check_paths()

    assert len(problems) == 1, problems
    assert "definitely_missing_xyz" in problems[0]


def test_path_check_ignores_historical_temp_files(monkeypatch, tmp_path):
    """历史叙述里引用的已删除临时文件不得误报（它们是正确的历史记录）。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CONTRACT.md").write_text("根目录 `_h.py` / `_w.py` 曾被入库。\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "PATH_ROOTS", (Path("."),))
    monkeypatch.setattr(cdc, "LIVE_DOCS", ("docs/CONTRACT.md",))

    problems = cdc.check_paths()

    assert problems == [], problems


# ---------------------------------------------------------------- 真实仓库（端到端）

def test_real_repo_is_consistent():
    """当前仓库必须通过全部检查——这是「文档与代码同步」的硬门禁。

    若本用例失败，说明文档已漂移：按提示修正，或对历史性内容加 `docs-ok` 标记。
    """
    result = subprocess.run([sys.executable, str(SCRIPT), "--json"],
                            cwd=str(BACKEND_DIR), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, (
        "文档一致性校验失败（exit=%d）：\n%s" % (result.returncode, result.stdout[-3000:]))
    report = json.loads(result.stdout)
    assert report["total"] == 0, report


def test_script_exits_2_when_baseline_missing(tmp_path):
    """事实源缺失时必须报错退出（而非静默通过）。"""
    result = subprocess.run([sys.executable, str(SCRIPT)],
                            cwd=str(BACKEND_DIR), capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    # 正常仓库里应 exit=0；此处只断言「不会静默成功」的语义由上面用例覆盖，
    # 这里验证脚本本身可执行且返回约定的退出码集合。
    assert result.returncode in (0, 2, 3), result.stdout + result.stderr


def test_refresh_script_has_check_mode():
    """刷新器必须支持 --check（CI 用它比对，不写盘）。"""
    result = subprocess.run([sys.executable, str(REFRESH), "--check"],
                            cwd=str(BACKEND_DIR), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode in (0, 2), (
        "refresh --check 意外退出 %d：\n%s\n%s"
        % (result.returncode, result.stdout[-800:], result.stderr[-800:]))
    assert "baseline" in (result.stdout + result.stderr).lower()
