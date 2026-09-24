"""数据库敏感字符串透明加密；兼容读取旧明文，重新写入后自动加密。"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import String, TypeDecorator


def _fernet() -> Fernet:
    raw = os.getenv("ERP_CREDENTIAL_KEY", "")
    if raw:
        try:
            return Fernet(raw.encode())
        except ValueError:
            key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
            return Fernet(key)
    # 仅供开发/测试兼容；生产启动门禁要求显式独立密钥。
    # 复用 config.DEV_JWT_SECRET 常量，避免两处默认值漂移（改常量会使旧密文不可解）。
    from .config import DEV_JWT_SECRET

    seed = os.getenv("ERP_JWT_SECRET", DEV_JWT_SECRET) + ":credential-dev"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))


def encrypt_database_value(value: str) -> str:
    if not value or value.startswith("enc:v1:"):
        return value or ""
    return "enc:v1:" + _fernet().encrypt(value.encode()).decode()


class EncryptedString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value or str(value).startswith("enc:v1:"):
            return value or ""
        return encrypt_database_value(str(value))

    def process_result_value(self, value, dialect):
        if not value or not str(value).startswith("enc:v1:"):
            return value or ""
        try:
            return _fernet().decrypt(str(value)[7:].encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("平台凭证无法解密，请检查 ERP_CREDENTIAL_KEY") from exc
