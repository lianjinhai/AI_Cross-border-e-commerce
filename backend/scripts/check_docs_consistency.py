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

    4. **文档内容被静默损坏**——`WORKSPACE_MIGRATION_PROGRESS.md` 里
       `roleKey` / `routeRedirect` / `erp_user.role` 三个词的首字符被吃掉，
       变成 `oleKey` / `outeRedirect` / `rp_user.role`，并残留一个 ESC(0x1B)
       控制字符。根因是 **PowerShell 反引号转义**：markdown 的反引号在
       PowerShell 双引号字符串里是转义符，`` `r `` 变成回车、`` `e `` 变成 ESC。
       该损坏从首次提交（6215d49）就存在，历经 20 轮评审未被发现——
       因为**损坏后的文本仍然「读得通」**。这类问题必须由机器检查。

    7. **孤儿文档**——`docs/` 根目录有 18 个文档，但 `AGENTS.md` §11 只索引 9 个，
       `docs/archive/README.md` 的「活文档清单」列了 11 个（漏 7 个），实测
       **4 份文档零引用**（`M4客服知识自进化方案与论证.md`、
       `权限体系问题排查与专家探讨.md`、`角色权限体系梳理方案.md`、
       `角色界面差异化设计方案.md`）——维护者不知道它们存在，也不知道哪份已过期。
    6. **ADR 索引锚点漂移**——`docs/adr/README.md` 声称「覆盖全部 D 编号、锚点已逐条
       核对」，实测 **D22~D26 锚点各偏移 2 行**、**D27~D31 完全未收录**（索引表停在
       D26 却写「总计 28 条」）。人工核对锚点在每次追加决策后必然失效。
    5. **代码位置引用越界**——DEBT-05 把 `platform_adapters.py` 从 1303 行拆成
       12 模块后，`项目介绍与功能地图.md` 仍有 11 处引用旧行号（如
       `platform_adapters.py:71-539`，而门面文件只剩 131 行）。检查 B 只验证
       「文件存在」，**行号越界它抓不到**——拆包/删函数后这类引用必然失效。

检查项
    A. 基线数字一致：活文档中出现的 `N passed` 必须与 `docs/baseline.json` 一致。
    B. 路径引用有效：反引号里的文件路径必须能在仓库中解析。
    C. 台账状态自洽：规范 §11 中标记「已完成」的债务，不得在其它活文档里
       仍被描述为「未完成」。
    D. 文本卫生：文档不得含控制字符、BOM，行尾必须 LF，且行内代码标记
       （反引号）必须成对——这些是**内容损坏**，肉眼看不出来但会污染阅读与检索。
    E. 换行注入：字面量 \\n 被写成真换行（把一行撕成两行）。
    F. 代码位置引用有效：`file.py:123` 形式的行号必须在文件实际范围内——
       代码重构（拆包/删函数）后行号必然失效，而「文件存在」检查抓不到。
    G. ADR 索引锚点有效：`docs/adr/README.md` 的 `[L123](../DECISIONS.md#L123)`
       锚点必须与该决策标题的实际行号一致，且不得漏收录新决策。
    H. 文档地图完整：`docs/` 根下每个活文档都必须在 `docs/DOCUMENT_MAP.md`
       登记，且归档目录每个文件都要在 `docs/archive/README.md` 登记——
       否则新增文档会成为「没人知道它存在」的孤儿。

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


def _is_historical(rel: str) -> bool:
    """该文档是否为「历史记录」类（其行号/数字是史实，不可改写）。"""
    return any(rel.startswith(prefix) for prefix in HISTORICAL_DOCS)


def _all_docs() -> list[Path]:
    """文本卫生检查的覆盖面：**所有**文档（含历史文档）。

    与 A/B/C 不同，控制字符 / BOM / 行尾 / 反引号配对是「文件本身的损坏」，
    与内容是否属于历史记录无关——历史记录也不该含 ESC 控制字符。
    因此这里不区分 HISTORICAL_DOCS。
    """
    docs = {p.resolve() for p in (REPO_DIR / "docs").rglob("*.md")}
    docs |= {p.resolve() for p in _live_docs()}
    for name in ("README.md",):
        path = REPO_DIR / name
        if path.exists():
            docs.add(path.resolve())
    return sorted(docs)


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


# 允许出现的控制字符（换行、制表）；其余（ESC/NUL/BEL/BS/VT/FF/SO/SI...）
# 一律视为内容损坏——它们通常来自编辑器或 shell 转义事故，肉眼不可见。
_ALLOWED_CTRL = {"\n", "\t"}

# 正规代码围栏（3 个及以上反引号）。
_FENCE = re.compile(r"^\s*`{3,}")

# **残缺围栏**：`` ``` `` 被 PowerShell 反引号转义塌缩成 `` ` `` 或 `` `` ``，
# 或 `` ```python `` 塌缩成 `` `python ``。这是本仓库实测发生过的真实损坏
# （4 个文档 / 18 处），肉眼看上去像行内代码，极易漏过。
_BROKEN_FENCE = re.compile(
    r"^\s*`{1,2}\s*(?:sql|python|bash|json|text|sh|js|yaml|powershell|vue|ini|"
    r"toml|http|diff|ts|html|css|md)?\s*$")

# 疑似 `` `n `` 注入：文档里本应是字面量 \n 的地方被写成了真换行，
# 特征是「上一行以 `X: 之类未完成片段结尾」+「下一行以孤立小写词开头」。
_LONE_FRAGMENT = re.compile(r"^[a-z][a-z0-9_]{1,9}$")


def _scan_text_hygiene(docs: list[Path]) -> list[str]:
    """D：文档文本卫生——控制字符 / BOM / 行尾 / 残缺围栏 / 未闭合行内代码。

    实现要点（每一条都是实测踩出来的）：
    1. **CR 只由行尾检查上报一次**。第一版把 CR 同时当作「控制字符」再报一遍，
       同一问题重复 3 次，让报告可信度崩塌（T-46 同类问题）。
    2. **行内代码允许跨行**，必须用状态机而非按行算反引号奇偶——按行算会把
       `` `sqlite3...\n...settings.key` `` 这类合法跨行 code span 全部误报（实测 8 处）。
    3. **残缺围栏只在「不在行内代码内」时才判定**。行内 code span 里的单反引号
       是合法内容，误报会淹没真损坏。
    """
    problems = []
    for doc in docs:
        rel = doc.relative_to(REPO_DIR).as_posix()
        raw = doc.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append("%s:1 含 UTF-8 BOM（规范要求 UTF-8 无 BOM）" % rel)
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        if b"\r" in body:
            problems.append(
                "%s:1 含 CR 行尾（%d 处）；仓库行尾策略为 LF（见 .gitattributes）"
                % (rel, body.count(b"\r")))
        text = body.decode("utf-8", errors="replace")
        in_fence = False
        inline_len = 0          # 已开启但未闭合的行内代码反引号个数
        inline_line = 0
        for lineno, line in enumerate(text.split("\n"), 1):
            if _FENCE.match(line):
                in_fence = not in_fence
                inline_len = 0
                continue
            if in_fence:
                continue
            # 控制字符（CR 已由行尾检查负责，不在此重复上报）
            for ch in line:
                if ord(ch) < 32 and ch not in _ALLOWED_CTRL and ch != "\r":
                    problems.append(
                        "%s:%d 含控制字符 %s(0x%02X)：%s"
                        % (rel, lineno, _ctrl_name(ord(ch)), ord(ch), line[:90]))
                    break
            # 残缺围栏：仅在「不在行内代码内」时判定。
            # 判定为残缺后**不喂给行内状态机**——否则塌缩的开栏 `` `sql `` 会被
            # 当成 code span 开启、与塌缩的闭栏 `` ` `` 配成一对，于是只报 1 处
            # （实测：真实损坏 18 处 = 开栏 + 闭栏都要报）。
            if inline_len == 0 and _BROKEN_FENCE.match(line):
                problems.append(
                    "%s:%d 残缺代码围栏（%r，应为 3 个反引号）：%s"
                    % (rel, lineno, line.strip(), line[:80]))
                continue
            # 更新行内代码状态（同长反引号配对）
            for match in re.finditer(r"`+", line):
                run_len = len(match.group(0))
                if inline_len == 0:
                    inline_len, inline_line = run_len, lineno
                elif run_len == inline_len:
                    inline_len = 0
        if inline_len:
            problems.append(
                "%s:%d 行内代码标记未闭合（%d 个反引号，直到文末无同长闭合）：%s"
                % (rel, inline_line, inline_len, _line_at(text, inline_line)[:80]))
    return problems


def _ctrl_name(code: int) -> str:
    return {0x00: "NUL", 0x07: "BEL", 0x08: "BS", 0x0B: "VT", 0x0C: "FF",
            0x0E: "SO", 0x0F: "SI", 0x1A: "SUB", 0x1B: "ESC"}.get(code, "CTRL")


def _line_at(text: str, lineno: int) -> str:
    lines = text.split("\n")
    return lines[lineno - 1] if 0 < lineno <= len(lines) else ""


def _scan_injected_newlines(docs: list[Path]) -> list[str]:
    """E：疑似 `` `n `` 注入——字面量被写成了真换行，把一行撕成两行。

    实测案例（DECISIONS.md）：``（`D:\nodejs\node.exe`，PID 3864）`` 被撕成
    ``（`D:`` / ``odejs`` / ``ode.exe`，PID 3864）`` 三行。这类损坏在渲染后
    「读起来仍然通顺」，只有机器能发现。
    """
    problems = []
    for doc in docs:
        rel = doc.relative_to(REPO_DIR).as_posix()
        lines = doc.read_text(encoding="utf-8", errors="replace").split("\n")
        in_fence = False
        for i in range(len(lines) - 1):
            if _FENCE.match(lines[i]):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            cur, nxt = lines[i], lines[i + 1]
            if not cur.strip() or not nxt.strip():
                continue
            if not _LONE_FRAGMENT.match(nxt):
                continue
            # 上一行必须「未完成」：不以标点收尾、不以表格/引用/标题开头。
            # 注意 ASCII 冒号 `:` 不算收尾标点——实测损坏样本正是 `（`D:` 这种「路径写到一半被撕开」的形态（全角「：」保留为收尾）。
            if len(cur) > 60 or cur.rstrip()[-1] in "。：；、）)》】」』.!?;)]}\"'|*~,，-—>":
                continue
            if cur.lstrip().startswith(("|", ">", "#", "-", "*", "`")):
                continue
            problems.append(
                "%s:%d 疑似 `n 注入（行被撕开）：%r + %r"
                % (rel, i + 1, cur[-40:], nxt[:40]))
    return problems


# `file.py:123` / `file.py:123-145` 形式的代码位置引用。
_LINEREF = re.compile(
    r"([A-Za-z0-9_./\-]+\.(?:py|js|vue|json))[:：](\d+)(?:\s*[-–~]\s*(\d+))?")

# 文档里指向「同名文件」时的消歧前缀：文档常写裸文件名（如 `base.py`），
# 而仓库里有多个 base.py（agents/base.py 80 行、adapters/base.py 110 行）。
# 用文档上下文里的目录线索消歧，避免把正确引用误判为越界（实测踩过）。
_LINEREF_CONTEXT_HINTS = (
    ("adapters/", "backend/app/services/adapters"),
    ("services/adapters", "backend/app/services/adapters"),
    ("agents/", "backend/app/agents"),
    ("routers/", "backend/app/routers"),
    ("services/", "backend/app/services"),
    ("tests/", "backend/tests"),
    ("scripts/", "backend/scripts"),
    ("views/", "frontend/src/views"),
)


def _resolve_code_ref(ref: str, context: str) -> Path | None:
    """把文档里的文件引用解析成仓库内的真实文件。

    **歧义必须保守处理**：文档常写裸文件名（`auth.py`、`compliance.py`、`base.py`），
    而仓库里有多个同名文件（`app/auth.py` 331 行 vs `app/routers/auth.py` 153 行；
    `agents/compliance.py` 135 行 vs `routers/compliance.py` 72 行）。

    实测踩坑：第一版按固定根目录顺序取「第一个存在」，把 `auth.py:284`
    （实指 `app/auth.py`）解析成 `routers/auth.py`（仅 153 行）→ **误报越界**；
    把 `compliance.py:82`（实指 `agents/compliance.py`）解析成 `routers/compliance.py`
    → 同样误报。守卫型工具的误报会淹没真问题，因此：

    ① 若按文件名能找到**多个**候选，且文档上下文无线索 → 返回 None（不判定）；
    ② 上下文线索（`agents/`、`routers/` 等）优先于固定根目录顺序；
    ③ 仅当**唯一命中**或线索明确时才判定越界。
    """
    # 线索可能出现在**引用内部**（`agents/base.py`）或**引用之前的紧邻上下文**
    # （`…由 agents 的 base.py 实现…`），两者都要认。
    # 实测踩坑：第一版只看 context，导致 `agents/base.py:9999` 这种「线索就在
    # ref 里」的写法被判为歧义而跳过——真越界反而漏报。
    probe = ref + " " + context
    for hint, root in _LINEREF_CONTEXT_HINTS:
        if hint not in probe:
            continue
        candidate = REPO_DIR / root / Path(ref).name
        if candidate.is_file():
            return candidate
    # 带路径分隔符的引用：直接按常见根目录解析
    if "/" in ref or "\\" in ref:
        for root in PATH_ROOTS:
            candidate = REPO_DIR / root / ref
            if candidate.is_file():
                return candidate
    # 裸文件名：全局搜索，**唯一命中才接受**
    matches = [f for f in REPO_DIR.rglob(Path(ref).name)
               if f.is_file() and ".git" not in f.parts
               and "node_modules" not in f.parts and "__pycache__" not in f.parts]
    return matches[0] if len(matches) == 1 else None


def check_code_line_refs() -> list[str]:
    """F：`file.py:123` 形式的代码位置引用必须在文件实际行数内。

    为什么需要：检查 B（路径引用有效）只验证「文件存在」。DEBT-05 把
    `platform_adapters.py` 从 1303 行拆成 12 模块后，文档里 11 处旧行号
    （如 `platform_adapters.py:71-539`）**全部越界**，但 B 检查全绿——
    因为文件确实还在（131 行的兼容门面）。行号引用必须单独检查。
    """
    problems = []
    # **作用域与 B（路径引用）一致：只查「描述当前状态」的文档**。
    # 历史文档（DECISIONS.md / archive/ / 子代理索引）本就要记录「当时引用的是
    # 哪些行号」——例如 D32 的「旧行号 → 新位置」对照表。把它们纳入 F 会让
    # 每条讨论重构的决策记录都变成永久红灯（实测：D32 一写入就报 7 处）。
    # 这不是「放宽断言」，而是**判定职责的边界**：历史记录的正确性由 C（台账
    # 状态自洽）与人工评审负责，不由行号有效性负责。
    targets = {p.resolve() for p in _live_docs()}
    targets |= {p.resolve() for p in (REPO_DIR / "docs").glob("*.md")}
    targets = {t for t in targets
               if not _is_historical(t.relative_to(REPO_DIR).as_posix())}
    for doc in sorted(targets):
        rel = doc.relative_to(REPO_DIR).as_posix()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            if "docs-ok" in line:
                continue
            for match in _LINEREF.finditer(line):
                ref, start, end = match.group(1), int(match.group(2)), match.group(3)
                if ref.startswith(("http", "docs/")) or "://" in ref:
                    continue
                # 只传紧邻引用前的片段：整行上下文会让 `routers/bi.py` 这种
                # 兄弟引用把 `auth.py` 误导到 routers/ 下（实测误报 2 处）。
                target = _resolve_code_ref(ref, line[max(0, match.start() - 24):match.start()])
                if target is None:
                    continue        # 文件本身由检查 B 负责；歧义则不判定
                total = len(target.read_text(encoding="utf-8", errors="replace").split("\n"))
                high = int(end) if end else start
                if start > total or high > total:
                    problems.append(
                        "%s:%d 代码位置引用越界：%s:%s%s（%s 实际仅 %d 行）"
                        % (rel, lineno, ref, start,
                           "-" + end if end else "",
                           target.relative_to(REPO_DIR).as_posix(), total))
    return problems


# `docs/adr/README.md` 索引行的锚点：`| D27 | ... | [`L1567`](../DECISIONS.md#L1567) |`
_ADR_ROW = re.compile(r"^\|\s*\*{0,2}(D\d+)(?:\(a\))?\*{0,2}\s*\|.*?\[`L(\d+)`\]\([^)]*#L\d+\)")
# `DECISIONS.md` 里决策标题的两种历史格式：`## D1 标题` 与 `## D17：标题`
_DECISION_HEAD = re.compile(r"^## (D\d+)[\s：]")


def check_adr_index() -> list[str]:
    """G：ADR 索引表的锚点行号必须与 `DECISIONS.md` 实际行号一致。

    为什么需要：`docs/adr/README.md` 是**面向外部的可独立引用层**，其索引表明确
    声称「覆盖全部 D 编号、锚点已逐条核对」。实测该声称已失效：
    D22~D26 锚点各偏移 2 行、D27~D31 完全未收录（表停在 D26 却写「总计 28 条」）。
    锚点在**每次追加决策后**都可能漂移，人工核对不可持续。
    """
    decisions = REPO_DIR / "docs" / "DECISIONS.md"
    adr = REPO_DIR / "docs" / "adr" / "README.md"
    if not decisions.exists() or not adr.exists():
        return []

    actual: dict[str, int] = {}
    for lineno, line in enumerate(decisions.read_text(encoding="utf-8").split("\n"), 1):
        match = _DECISION_HEAD.match(line)
        if match:
            actual.setdefault(match.group(1), lineno)   # 取正篇（首个）标题
    if not actual:
        return []

    indexed: set[str] = set()
    problems = []
    for lineno, line in enumerate(adr.read_text(encoding="utf-8").split("\n"), 1):
        match = _ADR_ROW.match(line)
        if not match:
            continue
        num, claimed = match.group(1), int(match.group(2))
        indexed.add(num)
        if num in ("D16", "D17"):
            # 早期重复编号：索引层用 (a) 后缀区分早期条目，不做精确锚点核对
            continue
        real = actual.get(num)
        if real is None:
            problems.append("docs/adr/README.md:%d 索引了不存在的 %s" % (lineno, num))
        elif real != claimed:
            problems.append(
                "docs/adr/README.md:%d %s 锚点漂移：写 L%d，DECISIONS.md 实际 L%d"
                % (lineno, num, claimed, real))

    missing = sorted(set(actual) - indexed - {"D16", "D17"}, key=lambda s: int(s[1:]))
    if missing:
        problems.append(
            "docs/adr/README.md 索引表漏收录 %d 条决策：%s"
            % (len(missing), ", ".join(missing)))
    return problems


def check_document_map() -> list[str]:
    """H：`docs/` 根下每个活文档都必须登记进 `docs/DOCUMENT_MAP.md`。

    为什么需要：实测 `docs/` 根有 18 个文档，但 `AGENTS.md` §11 只索引 9 个、
    `docs/archive/README.md` 的「活文档清单」列了 11 个（漏 7 个），
    **4 份文档零引用**——维护者不知道它们存在、也不知道哪份已过期。
    「人记得同步索引」不可持续，因此把「登记」变成硬门禁。

    豁免：本检查自身与其索引对象（`DOCUMENT_MAP.md` 不登记自己）。
    """
    docs_dir = REPO_DIR / "docs"
    doc_map = docs_dir / "DOCUMENT_MAP.md"
    if not doc_map.exists():
        return ["docs/DOCUMENT_MAP.md 不存在——docs/ 下的活文档需要一个总索引"]
    map_text = doc_map.read_text(encoding="utf-8")

    problems = []
    for doc in sorted(docs_dir.glob("*.md")):
        if doc.name == "DOCUMENT_MAP.md":
            continue
        if doc.name not in map_text:
            problems.append(
                "docs/%s 未登记进 docs/DOCUMENT_MAP.md（新增文档必须登记，"
                "否则会成为没人知道它存在的孤儿）" % doc.name)

    archive = docs_dir / "archive"
    archive_readme = archive / "README.md"
    if archive.is_dir() and archive_readme.exists():
        archive_text = archive_readme.read_text(encoding="utf-8")
        for item in sorted(archive.glob("*.md")):
            if item.name == "README.md":
                continue
            if item.name not in archive_text:
                problems.append(
                    "docs/archive/%s 未登记进 docs/archive/README.md" % item.name)
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
        "text_hygiene": _scan_text_hygiene(_all_docs()),
        "injected_newlines": _scan_injected_newlines(_all_docs()),
        "code_line_refs": check_code_line_refs(),
        "adr_index": check_adr_index(),
        "document_map": check_document_map(),
        "baseline": {"backend": baseline["backend"]["tests"],
                     "frontend": baseline["frontend"]["tests"]},
    }
    total = sum(len(report[key]) for key in
                ("baseline_numbers", "path_refs", "ledger_status", "text_hygiene",
                 "injected_newlines", "code_line_refs", "adr_index", "document_map"))
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
                           ("ledger_status", "C. 台账状态自洽"),
                           ("text_hygiene", "D. 文本卫生（控制字符/BOM/行尾/围栏）"),
                           ("injected_newlines", "E. 换行注入（字面量 \\n 被写成真换行）"),
                           ("code_line_refs", "F. 代码位置引用有效（file.py:123 未越界）"),
                           ("adr_index", "G. ADR 索引锚点有效（行号一致 + 无漏收录）"),
                           ("document_map", "H. 文档地图完整（活文档 + 归档均已登记）")):
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
