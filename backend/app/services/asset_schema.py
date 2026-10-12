"""素材登记契约：URI 是来源引用，不触发网络下载，核验状态由服务端决定。"""

import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .regions import store_market

RIGHTS_ALLOWED = frozenset({"OWNED", "SUPPLIER_AUTHORIZED", "LICENSED"})
IMAGE_TYPES = frozenset({"ORIGINAL_IMAGE", "MAIN_IMAGE", "DETAIL_IMAGE", "SIZE_IMAGE", "PHYSICAL_PHOTO"})


class AssetRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    expected_version: int = Field(ge=0, strict=True)
    asset_type: Literal["ORIGINAL_IMAGE", "MAIN_IMAGE", "DETAIL_IMAGE", "SIZE_IMAGE", "PHYSICAL_PHOTO",
                        "RIGHTS_EVIDENCE", "VIDEO", "LABEL", "BARCODE", "COMPLIANCE_ATTACHMENT"]
    uri: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rights_status: Literal["OWNED", "SUPPLIER_AUTHORIZED", "LICENSED", "UNKNOWN", "RESTRICTED"]
    source: str = Field(min_length=1, max_length=256)
    rights_evidence_ref: str = Field(default="", max_length=2048)
    market: str = Field(min_length=2, max_length=8)
    platform: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    manifest: dict = Field(default_factory=dict)

    @field_validator("uri", "rights_evidence_ref")
    @classmethod
    def safe_reference(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "asset", "evidence"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("素材与证据引用须使用 https/asset/evidence，禁止本地文件路径或含凭证 URL")
        return value

    @field_validator("market")
    @classmethod
    def market_code(cls, value):
        result = store_market(value)
        if not result:
            raise ValueError("素材适用市场必须是明确国家")
        return result

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc_dates(cls, value):
        return value.astimezone(UTC).replace(tzinfo=None) if value and value.tzinfo else value

    @model_validator(mode="after")
    def trusted_fields(self):
        if not self.source.strip() or (self.rights_status in {"SUPPLIER_AUTHORIZED", "LICENSED"} and not self.rights_evidence_ref):
            raise ValueError("素材必须提供来源，授权/许可素材还需权利证据引用")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("有效期终点必须晚于起点")
        encoded = json.dumps(self.manifest, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 32000 or any(str(key).startswith("_") for key in self.manifest):
            raise ValueError("manifest 超限或包含服务端保留字段")
        return self
