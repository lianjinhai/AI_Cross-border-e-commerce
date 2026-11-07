"""素材上传服务（M2-D）：哈希只能由服务端算；未接存储时一律拒绝。

为什么要单独一个服务
--------------------
登记接口（`POST /api/products/{id}/assets`）收的是客户端给的 `content_hash`，
而 `AssetRegistration` 只能校验它是 64 位十六进制——任何人都能编一个「看起来像
sha256」的串。这样一来「图片权利证据」就成了一张没人能复核的空头承诺，正是
R3-1B 里「不得生成假哈希」要挡的东西。

本模块把哈希的产生收回到服务端：文件先落存储，服务端读字节算 sha256，客户端
只能引用这个结果（`asset://<sha256>/<文件名>`）。登记时再按引用重算一次比对，
改了哈希或换了文件都会露。

能力开关
--------
`settings.asset_upload_dir`（环境变量 `ERP_ASSET_UPLOAD_DIR`）为空 = 上传服务
**未接入**。此时 `save()` 直接抛 `UploadUnavailable`，**不落盘、不写库**；调用方
必须把它翻成明确错误码，不许降级成「先登记再说」或「用客户端哈希凑合」。

边界（写在这里，避免以后被当成云存储）
    * 本地目录只保证单机持久与可回读；多副本 / 对象存储 / 防盗链 / CDN 仍在
      B03–B09，未接入。
    * 只接受位图（jpeg/png/webp）且限制大小；这是**门禁**不是存储策略，
      超限是明确拒绝，不静默截断。
"""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from ..config import settings

#: 单文件上限（8 MiB）。够商品主图/细节图用，同时避免一次请求把内存打满。
MAX_BYTES = 8 * 1024 * 1024

#: 白名单：content-type → 落盘扩展名。不在表里的一律拒绝。
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_SCHEME = "asset"
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadUnavailable(RuntimeError):
    """上传服务未接入（未配置存储）。调用方必须翻成显式错误码，不得降级。"""

    code = "ASSET_UPLOAD_UNAVAILABLE"

    def __init__(self, message: str = "素材上传服务未接入（未配置 ERP_ASSET_UPLOAD_DIR）"):
        super().__init__(message)


class UploadRejected(ValueError):
    """文件本身不合规（空文件 / 类型不在白名单 / 超过大小上限）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def storage_dir() -> Path | None:
    """当前配置的存储根目录；未配置返回 None（= 上传服务未接入）。"""
    raw = str(getattr(settings, "asset_upload_dir", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def capability() -> dict:
    """上传能力快照，供接口与前端如实展示「能不能传」。"""
    configured = storage_dir() is not None
    return {
        "connected": configured,
        "reason": "" if configured else "素材上传服务未接入（未配置 ERP_ASSET_UPLOAD_DIR）",
        "max_bytes": MAX_BYTES,
        "content_types": sorted(ALLOWED_CONTENT_TYPES),
    }


def _safe_name(filename: str, suffix: str) -> str:
    base = _NAME_RE.sub("_", str(filename or "").strip())[-80:].strip("._")
    if not base:
        base = "asset"
    if not base.lower().endswith(suffix):
        base = base + suffix
    return base


def _path_for(root: Path, content_sha: str, name: str) -> Path:
    """按内容哈希分桶存；同一份字节无论传几次都落同一个文件。"""
    return root / content_sha[:2] / (content_sha + Path(name).suffix)


def save(data: bytes, content_type: str, filename: str = "") -> dict:
    """落盘并返回服务端算出的哈希与引用。

    :raises UploadUnavailable: 未配置存储（未接入）；此时什么都没写。
    :raises UploadRejected: 空文件 / 类型不在白名单 / 超过大小上限。
    """
    root = storage_dir()
    if root is None:
        raise UploadUnavailable()
    normalized = str(content_type or "").split(";")[0].strip().lower()
    suffix = ALLOWED_CONTENT_TYPES.get(normalized)
    if suffix is None:
        raise UploadRejected("ASSET_TYPE_UNSUPPORTED",
                             "只接受 image/jpeg、image/png、image/webp，收到：" + (normalized or "空"))
    if not data:
        raise UploadRejected("ASSET_EMPTY", "上传内容为空")
    if len(data) > MAX_BYTES:
        raise UploadRejected("ASSET_TOO_LARGE",
                             "单个素材不能超过 %d 字节（收到 %d）" % (MAX_BYTES, len(data)))
    content_sha = hashlib.sha256(data).hexdigest()
    name = _safe_name(filename, suffix)
    target = _path_for(root, content_sha, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != len(data):
        # 先写临时文件再改名：进程中途挂掉不会留下半截文件被后续请求当成「已存在」。
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
    return {
        "uri": "%s://%s/%s" % (_SCHEME, content_sha, name),
        "content_hash": content_sha,
        "size": len(data),
        "content_type": normalized,
        "stored": True,
    }


def verify_reference(uri: str) -> str:
    """按 `asset://<sha256>/<name>` 引用回读文件并**重算**哈希。

    用于登记时校验：客户端声明的 `content_hash` 必须与存储里的字节一致，否则
    就是假哈希或换了文件。

    :raises UploadUnavailable: 未配置存储（此时任何 asset:// 引用都不可信）。
    :raises UploadRejected: 引用格式不对、文件不存在、或哈希对不上。
    """
    root = storage_dir()
    if root is None:
        raise UploadUnavailable()
    parts = urlsplit(uri)
    if parts.scheme != _SCHEME:
        raise UploadRejected("ASSET_REFERENCE_INVALID", "不支持的上传引用协议：" + str(parts.scheme))
    content_sha = (parts.netloc or "").strip()
    if not _HASH_RE.match(content_sha):
        raise UploadRejected("ASSET_REFERENCE_INVALID", "上传引用里的哈希不是 64 位 sha256")
    name = _safe_name(Path(parts.path or "").name, "")
    if not name:
        raise UploadRejected("ASSET_REFERENCE_INVALID", "上传引用缺少文件名")
    target = _path_for(root, content_sha, name)
    if not target.is_file():
        raise UploadRejected("ASSET_FILE_MISSING", "存储中找不到该素材文件，请重新上传")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != content_sha:
        raise UploadRejected("ASSET_HASH_MISMATCH", "存储文件与引用哈希不一致，素材不可信")
    return actual
