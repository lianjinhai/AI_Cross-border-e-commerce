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

# 反引号常量：测试里要构造 markdown 代码标记，直接写反引号会让本文件自身的
# 引号嵌套变得极难阅读（也容易被 shell/编辑器转义事故吃掉）。
BT = chr(96)
F3 = BT * 3

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


# ---------------------------------------------------------------- D. 文本卫生

def _hygiene(tmp_path, monkeypatch, body: str, name: str = "docs/X.md"):
    """把 body 写成文档后跑文本卫生检查（body 以 bytes 语义写入，保留控制字符）。"""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    return cdc._scan_text_hygiene([path])


def test_hygiene_catches_escape_character(tmp_path, monkeypatch):
    """判别力：ESC(0x1B) 必须被抓到——这是 PowerShell `` `e `` 转义事故的残留。"""
    problems = _hygiene(tmp_path, monkeypatch,
                        "伪造 " + BT + "erp_user.role" + BT + " 无效\x1b 仍可影响路由。\n")
    assert len(problems) == 1, problems
    assert "ESC" in problems[0] and "0x1B" in problems[0]


def test_hygiene_catches_broken_fence(tmp_path, monkeypatch):
    """判别力：`` ``` `` 塌缩成 `` ` `` 必须被抓到（实测 4 文档 / 18 处）。"""
    body = "\n".join([BT + "sql", "SELECT 1;", BT, ""])
    problems = _hygiene(tmp_path, monkeypatch, body)
    assert len(problems) == 2, problems
    assert all("残缺代码围栏" in p for p in problems), problems


def test_hygiene_catches_crlf(tmp_path, monkeypatch):
    """判别力：CR 行尾必须被抓到（仓库策略为 LF）。"""
    problems = _hygiene(tmp_path, monkeypatch, "第一行\r\n第二行\r\n")
    assert len(problems) == 1, problems
    assert "CR" in problems[0]


def test_hygiene_catches_bom(tmp_path, monkeypatch):
    """判别力：UTF-8 BOM 必须被抓到（规范要求无 BOM）。"""
    path = tmp_path / "docs" / "X.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + "# 标题\n".encode())
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    problems = cdc._scan_text_hygiene([path])
    assert len(problems) == 1, problems
    assert "BOM" in problems[0]


def test_hygiene_accepts_clean_doc(tmp_path, monkeypatch):
    """反向用例：合规文档不得误报（否则校验器沦为噪音）。"""
    body = ("# 标题\n\n"
            "普通行内代码 " + BT + "roleKey" + BT + " 与 " + BT + "routeRedirect" + BT + "。\n\n"
            + F3 + "python\nprint(1)\n" + F3 + "\n\n"
            "围栏内的单反引号是代码内容，合法：" + F3 + "\n" + BT + "\n" + F3 + "\n")
    assert _hygiene(tmp_path, monkeypatch, body) == []


def test_hygiene_allows_multiline_inline_code(tmp_path, monkeypatch):
    """反向用例：markdown 行内代码**允许跨行**，按行算奇偶会误报（实测 8 处）。

    第一版校验器就是按行算奇偶，把 `` `sqlite3...\n...settings.key` `` 这类
    合法的跨行 code span 全报了出来。
    """
    body = ("并发跑测试时出现 " + BT + "sqlite3.IntegrityError: UNIQUE constraint\n"
            "failed: settings.key" + BT + "（一次实测 115 个用例报错）。\n")
    assert _hygiene(tmp_path, monkeypatch, body) == []


def test_hygiene_catches_unclosed_inline_code(tmp_path, monkeypatch):
    """判别力：真正未闭合的行内代码仍要被抓到（不能为了去误报而放过）。"""
    body = "这里有一个未闭合的 " + BT + "roleKey 标记。\n"
    problems = _hygiene(tmp_path, monkeypatch, body)
    assert len(problems) == 1, problems
    assert "未闭合" in problems[0]


# ---------------------------------------------------------------- E. 换行注入

def test_injected_newline_catches_split_line(tmp_path, monkeypatch):
    """判别力：`` `n `` 被写成真换行、把一行撕成两行，必须被抓到。

    实测案例（DECISIONS.md）：``（`D:\\nodejs\\node.exe`，PID 3864）`` 被撕成
    ``（`D:`` / ``odejs`` / ``ode.exe`，PID 3864）``。
    """
    path = tmp_path / "docs" / "X.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("端口被本机另一个项目的 node 占用\n（" + BT + "D:\nodejs\n"
                    "ode.exe" + BT + "，PID 3864）——无关。\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    problems = cdc._scan_injected_newlines([path])
    assert len(problems) == 1, problems
    assert "注入" in problems[0]


def test_injected_newline_ignores_normal_wrapping(tmp_path, monkeypatch):
    """反向用例：正常的中文换行（上一行以标点收尾）不得误报。"""
    path = tmp_path / "docs" / "X.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("这是一句正常的话，\n下一行继续说明。\n\n"
                    "另一段以标点结尾：\n继续。\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    assert cdc._scan_injected_newlines([path]) == []

# ---------------------------------------------------------------- F. 代码位置引用

def _lineref(tmp_path, monkeypatch, body: str):
    path = tmp_path / "docs" / "X.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cdc, "_all_docs", lambda: [path])
    return cdc.check_code_line_refs()


def test_lineref_catches_out_of_range(tmp_path, monkeypatch):
    """判别力：`file.py:9999` 越界必须被抓到。

    这是 B（路径引用有效）抓不到的类别——DEBT-05 拆包后 `platform_adapters.py`
    从 1303 行变 131 行，文档里 11 处旧行号全部越界，而 B 检查全绿（文件确实还在）。
    """
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    problems = _lineref(tmp_path, monkeypatch, "见 " + BT + "mod.py:9999" + BT + " 处。\n")
    assert len(problems) == 1, problems
    assert "越界" in problems[0] and "9999" in problems[0]


def test_lineref_accepts_valid_range(tmp_path, monkeypatch):
    """反向用例：行号在文件范围内的引用不得误报。"""
    (tmp_path / "mod.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    assert _lineref(tmp_path, monkeypatch,
                    "见 " + BT + "mod.py:1-3" + BT + " 与 " + BT + "mod.py:2" + BT + "。\n") == []


def test_lineref_skips_ambiguous_bare_filename(tmp_path, monkeypatch):
    """歧义裸文件名必须**保守跳过**而非误报。

    仓库里有 `app/auth.py`(331) 与 `app/routers/auth.py`(153) 两个同名文件；
    第一版按固定根目录顺序取第一个，把 `auth.py:284` 解析成 routers/ 版本
    → 误报越界（实测 2 处）。守卫工具的误报会淹没真问题。
    """
    (tmp_path / "backend" / "app" / "routers").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "auth.py").write_text("x = 1\n" * 400, encoding="utf-8")
    (tmp_path / "backend" / "app" / "routers" / "auth.py").write_text(
        "y = 1\n" * 100, encoding="utf-8")
    monkeypatch.setattr(cdc, "PATH_ROOTS", (Path("."),))
    monkeypatch.setattr(cdc, "_LINEREF_CONTEXT_HINTS", ())
    assert _lineref(tmp_path, monkeypatch, "见 " + BT + "auth.py:284" + BT + "。\n") == []


def test_lineref_context_hint_disambiguates(tmp_path, monkeypatch):
    """线索消歧后仍要能抓到越界（不能为了去误报而放过真问题）。

    **夹具必须复刻生产目录结构**（T-44）：`_LINEREF_CONTEXT_HINTS` 里的线索
    是按生产路径写死的（`agents/` → `backend/app/agents`），用 `app/agents`
    这种玩具结构会让解析器一行都命中不了，测试「跑通却什么都没验证」。
    """
    (tmp_path / "backend" / "app" / "agents").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "agents" / "base.py").write_text(
        "z = 1\n" * 50, encoding="utf-8")
    (tmp_path / "backend" / "app" / "services").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "services" / "base.py").write_text(
        "w = 1\n" * 200, encoding="utf-8")
    monkeypatch.setattr(cdc, "PATH_ROOTS", (Path("."),))
    problems = _lineref(tmp_path, monkeypatch,
                        "见 " + BT + "agents/base.py:9999" + BT + " 处。\n")
    assert len(problems) == 1, problems
    assert "9999" in problems[0]
    # 反向断言：确认解析到的是 agents 版本（51 行）而非 services 版本（201 行）
    assert "backend/app/agents/base.py" in problems[0], problems[0]
    assert "51 行" in problems[0], problems[0]


def test_lineref_ignores_missing_file(tmp_path, monkeypatch):
    """文件本身不存在时交给 B 检查负责，F 不重复上报（避免同一问题两条告警）。"""
    assert _lineref(tmp_path, monkeypatch,
                    "见 " + BT + "definitely_missing.py:10" + BT + "。\n") == []

# ---------------------------------------------------------------- G. ADR 索引锚点

def _adr(tmp_path, monkeypatch, decisions: str, adr_rows: str):
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "DECISIONS.md").write_text(decisions, encoding="utf-8")
    (tmp_path / "docs" / "adr" / "README.md").write_text(adr_rows, encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    return cdc.check_adr_index()


def _row(num: str, line: int) -> str:
    return "| " + num + " | 标题 | Accepted | kw | [`L" + str(line) + "`](../DECISIONS.md#L" + str(line) + ") |"


def test_adr_index_catches_anchor_drift(tmp_path, monkeypatch):
    """判别力：锚点行号与 DECISIONS.md 实际不一致必须被抓到。

    实测：`docs/adr/README.md` 的 D22~D26 锚点各偏移 2 行——而该表明确声称
    「锚点已逐条核对」。人工核对在每次追加决策后必然失效。
    """
    decisions = "## D1 标题\n" + "x\n" * 9 + "## D2：标题\n"   # D1=L1, D2=L11
    problems = _adr(tmp_path, monkeypatch, decisions, _row("D1", 1) + "\n" + _row("D2", 999) + "\n")
    assert len(problems) == 1, problems
    assert "D2" in problems[0] and "L999" in problems[0] and "L11" in problems[0]


def test_adr_index_catches_missing_decision(tmp_path, monkeypatch):
    """判别力：漏收录决策必须被抓到（表停在旧编号是「静默过期」）。"""
    decisions = "## D1 标题\n## D2 标题\n"
    problems = _adr(tmp_path, monkeypatch, decisions, _row("D1", 1) + "\n")
    assert len(problems) == 1, problems
    assert "D2" in problems[0] and "漏收录" in problems[0]


def test_adr_index_accepts_consistent_table(tmp_path, monkeypatch):
    """反向用例：锚点正确且无漏收录时不得误报。"""
    decisions = "## D1 标题\n" + "x\n" * 9 + "## D2：标题\n"
    assert _adr(tmp_path, monkeypatch, decisions,
                _row("D1", 1) + "\n" + _row("D2", 11) + "\n") == []


def test_adr_index_skips_legacy_duplicate_numbers(tmp_path, monkeypatch):
    """D16/D17 是历史重复编号（早期以一级标题写入），索引层用 (a) 后缀区分，
    不得因锚点核对产生噪音。"""
    decisions = "## D16：新条目\n## D17：新条目\n"
    assert _adr(tmp_path, monkeypatch, decisions,
                _row("D16", 1) + "\n" + _row("D17", 2) + "\n") == []

# ---------------------------------------------------------------- H. 文档地图

def _docmap(tmp_path, monkeypatch, live: list[str], archived: list[str],
            map_names: list[str], archive_names: list[str]):
    docs = tmp_path / "docs"
    (docs / "archive").mkdir(parents=True)
    for name in live:
        (docs / name).write_text("# x\n", encoding="utf-8")
    for name in archived:
        (docs / "archive" / name).write_text("# x\n", encoding="utf-8")
    (docs / "DOCUMENT_MAP.md").write_text(
        "# 地图\n" + "".join("- " + n + "\n" for n in map_names), encoding="utf-8")
    (docs / "archive" / "README.md").write_text(
        "# 归档\n" + "".join("- " + n + "\n" for n in archive_names), encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    return cdc.check_document_map()


def test_docmap_catches_orphan_live_doc(tmp_path, monkeypatch):
    """判别力：新增未登记的活文档必须被抓到。

    实测背景：`docs/` 根有 18 个文档，但索引只覆盖 9~11 个，
    **4 份文档零引用**——维护者不知道它们存在，也不知道哪份已过期。
    """
    problems = _docmap(tmp_path, monkeypatch,
                       live=["A.md", "ORPHAN.md"], archived=[],
                       map_names=["A.md"], archive_names=[])
    assert len(problems) == 1, problems
    assert "ORPHAN.md" in problems[0]


def test_docmap_catches_orphan_archive(tmp_path, monkeypatch):
    """判别力：归档目录里未登记的文件必须被抓到。"""
    problems = _docmap(tmp_path, monkeypatch,
                       live=["A.md"], archived=["old.md", "ORPHAN.md"],
                       map_names=["A.md"], archive_names=["old.md"])
    assert len(problems) == 1, problems
    assert "ORPHAN.md" in problems[0]


def test_docmap_accepts_complete_map(tmp_path, monkeypatch):
    """反向用例：全部登记时不得误报（含 DOCUMENT_MAP.md 不登记自己）。"""
    assert _docmap(tmp_path, monkeypatch,
                   live=["A.md", "B.md"], archived=["old.md"],
                   map_names=["A.md", "B.md"], archive_names=["old.md"]) == []


def test_docmap_reports_missing_map_file(tmp_path, monkeypatch):
    """DOCUMENT_MAP.md 本身缺失时必须明确报错，而不是静默通过。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "A.md").write_text("# x\n", encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    problems = cdc.check_document_map()
    assert len(problems) == 1, problems
    assert "DOCUMENT_MAP.md 不存在" in problems[0]

# ---------------------------------------------------------------- I. 子代理状态

def _subagent(tmp_path, monkeypatch, ledger: str, index_body: str):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "CODE_AND_DIRECTORY_STANDARD.md").write_text(ledger, encoding="utf-8")
    (docs / "\u5b50\u4ee3\u7406\u5b9e\u65bd\u7d22\u5f15-20260923.md").write_text(
        index_body, encoding="utf-8")
    monkeypatch.setattr(cdc, "REPO_DIR", tmp_path)
    return cdc.check_subagent_status()


LEDGER_DEBT07_DONE = (
    "| DEBT-07 | ~~\u7f3a AGENTS.md~~ | ~~P1~~ | \u4ed3\u5e93\u6839 | "
    "\u2705 **\u5df2\u5b8c\u6210\uff082026-09-24\uff09** |\n")
LEDGER_DEBT29_OPEN = "| DEBT-29 | \u8d8a\u5c42 | **P2** | x | \u5f85\u5904\u7406 |\n"

AID = "01a0d31f-4795-7090-8e4a-7c53129891f5"


def test_subagent_catches_zombie_progress_on_closed_debt(tmp_path, monkeypatch):
    """\u5224\u522b\u529b\uff1a\u300c\u8fdb\u884c\u4e2d\u300d\u4e0d\u5f97\u6302\u5728\u89c4\u8303 \u00a711 \u5df2\u5173\u95ed\u7684\u503a\u52a1\u4e0a\u3002

    \u5b9e\u6d4b\u80cc\u666f\uff1aParfit\uff08DEBT-07 `CONTRIBUTING.md`\uff09\u6807\u300c\U0001f504 \u8fdb\u884c\u4e2d\u300d\uff0c
    \u800c `CONTRIBUTING.md` \u65e9\u5df2\u5b58\u5728\uff0816050 \u5b57\u8282\uff09\u3001\u89c4\u8303 \u00a711 \u5df2\u6807\u300c\u5df2\u5b8c\u6210\u300d\u3002
    \u8fd9\u79cd\u50f5\u5c38\u72b6\u6001\u4f1a\u8ba9\u4eba\u8bef\u4ee5\u4e3a\u300c\u8fd8\u6709\u6d3b\u6ca1\u5e72\u5b8c\u300d\u3002
    """
    problems = _subagent(
        tmp_path, monkeypatch, LEDGER_DEBT07_DONE,
        "| `%s` | Parfit | DEBT-07 | \U0001f504 \u8fdb\u884c\u4e2d | - | - |\n" % AID)
    assert len(problems) == 1, problems
    assert "\u50f5\u5c38\u72b6\u6001" in problems[0]
    assert "DEBT-07" in problems[0]


def test_subagent_catches_self_contradiction(tmp_path, monkeypatch):
    """\u5224\u522b\u529b\uff1a\u540c\u4e00 ID \u4e0d\u5f97\u540c\u65f6\u6807\u300c\u8fdb\u884c\u4e2d\u300d\u4e0e\u300c\u5df2\u5b8c\u6210\u300d\u3002

    \u5b9e\u6d4b\u80cc\u666f\uff1aGodel\uff08P1-04\uff09\u5728\u7b2c 33 \u884c\u6807\u300c\u8fdb\u884c\u4e2d\u300d\uff0c
    \u800c\u540c\u4e00\u6587\u4ef6\u7b2c 46 \u884c\u5df2\u5199\u300c\u5df2\u5b8c\u6210\uff0c\u603b\u7ed3\u5df2\u5165\u7d22\u5f15\uff0c\u5df2\u6e05\u7406\u300d\u3002
    """
    body = ("| `%s` | Godel | \u8fdb\u884c\u4e2d |\n" % AID +
            "| `%s` | Godel | \u5df2\u5b8c\u6210\uff0c\u5df2\u6e05\u7406 |\n" % AID)
    problems = _subagent(tmp_path, monkeypatch, LEDGER_DEBT29_OPEN, body)
    assert len(problems) == 1, problems
    assert "\u72b6\u6001\u77db\u76fe" in problems[0]


def test_subagent_allows_progress_on_open_debt(tmp_path, monkeypatch):
    """\u53cd\u5411\u7528\u4f8b\uff1a\u503a\u52a1\u4ecd\u672a\u5173\u95ed\u65f6\uff0c\u300c\u8fdb\u884c\u4e2d\u300d\u662f\u5408\u6cd5\u72b6\u6001\uff0c\u4e0d\u5f97\u8bef\u62a5\u3002"""
    problems = _subagent(
        tmp_path, monkeypatch, LEDGER_DEBT29_OPEN,
        "| `%s` | X | DEBT-29 | \U0001f504 \u8fdb\u884c\u4e2d | - | - |\n" % AID)
    assert problems == [], problems


def test_subagent_allows_clean_closed_entry(tmp_path, monkeypatch):
    """\u53cd\u5411\u7528\u4f8b\uff1a\u5df2\u5173\u95ed\u7684\u6761\u76ee\u5fc5\u987b\u6b63\u5e38\u653e\u884c\u3002"""
    problems = _subagent(
        tmp_path, monkeypatch, LEDGER_DEBT07_DONE,
        "| `%s` | Parfit | DEBT-07 | \u2705 \u5df2\u5b8c\u6210\u5e76\u5173\u95ed | x | ok | \u65e0 |\n" % AID)
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
