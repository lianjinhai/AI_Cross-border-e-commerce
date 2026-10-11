"""平台流程定义契约：有界声明式 DAG，不携带任意 Agent 或 Python 调用。"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..services.regions import store_market
from .conditions import validate_condition

BUSINESS_ACTIONS = {
    "DATA_PREPARATION": {"COMPLETE_DATA"},
    "PLATFORM_SUBMISSION": {"SUBMIT_PLATFORM"},
    "PLATFORM_REVIEW": set(),
    "PRICE_REVIEW": {"REPORT_PRICE"},
    "HUMAN_DECISION": {"ACCEPT_PRICE", "COUNTER_PRICE", "ABANDON_PRODUCT", "COMPLETE_DATA"},
    "STOCK_PREPARATION": {"REQUEST_STOCK", "CONFIRM_STOCK"},
    "COMPLIANCE": {"UPLOAD_ARTIFACT", "VERIFY_ARTIFACT"},
    "LABEL": {"GENERATE_LABEL", "REGENERATE_LABEL"},
    "EVIDENCE": {"UPLOAD_PHYSICAL_EVIDENCE", "VERIFY_EVIDENCE"},
    "PLATFORM_ACTIVATION": {"CONFIRM_ACTIVATION"},
    "MONITORING": set(),
}
PLATFORM_STATES = {"UNKNOWN", "NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED",
                   "ACTIVE", "PAUSED", "REJECTED", "OFFLINE"}
FULFILLMENT_MODES = {"DROPSHIP", "PLATFORM_STOCK", "SELF_STOCK", "FACTORY_DIRECT"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TimeoutPolicy(StrictModel):
    notify_after: int | None = Field(default=None, ge=1)
    fail_after: int | None = Field(default=None, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retryable_errors: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def chronological(self):
        if self.notify_after and self.fail_after and self.notify_after > self.fail_after:
            raise ValueError("提醒时间不能晚于失败时间")
        return self


class StepDefinition(StrictModel):
    step_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    step_name: str = Field(min_length=1, max_length=128)
    business_type: str
    execution_mode: Literal["SYSTEM_TASK", "AI_ASSISTED", "ADAPTER_TASK", "MANUAL_TASK", "EXTERNAL_WAIT"]
    actor: Literal["SYSTEM", "AI", "USER", "PLATFORM", "FACTORY", "REVIEWER"]
    sequence: int = Field(ge=0, le=10000)
    required: bool = True
    blocking: bool = True
    applicability_condition: Any = True
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    entry_condition: Any = True
    completion_condition: Any
    evidence_requirements: list[str] = Field(default_factory=list, max_length=32)
    available_actions: list[str] = Field(default_factory=list, max_length=32)
    timeout_policy: TimeoutPolicy = Field(default_factory=TimeoutPolicy)

    @field_validator("applicability_condition", "entry_condition", "completion_condition")
    @classmethod
    def conditions(cls, value):
        return validate_condition(value)

    @model_validator(mode="after")
    def registered_actions(self):
        if self.business_type not in BUSINESS_ACTIONS:
            raise ValueError("未知业务步骤类型")
        if not set(self.available_actions) <= BUSINESS_ACTIONS[self.business_type]:
            raise ValueError("步骤包含未注册或不适用的动作")
        for values in (self.dependencies, self.available_actions, self.evidence_requirements):
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError("步骤引用必须非空且不可重复")
        if self.execution_mode == "MANUAL_TASK" and not self.evidence_requirements:
            raise ValueError("人工节点必须声明完成证据")
        return self


class ProfileDefinition(StrictModel):
    profile_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    environment: Literal["CONTRACT_TEST", "PRODUCTION"]
    verification_status: Literal["UNKNOWN", "UNVERIFIED"] = "UNVERIFIED"
    platform: str = Field(min_length=1, max_length=32)
    market: str = Field(min_length=1, max_length=8)
    store_type: str = Field(default="ANY", min_length=1, max_length=64)
    account_type: str = Field(default="ANY", min_length=1, max_length=64)
    business_mode: str = Field(default="ANY", min_length=1, max_length=64)
    fulfillment_mode: Literal["DROPSHIP", "PLATFORM_STOCK", "SELF_STOCK", "FACTORY_DIRECT", "ANY"]
    category_scope: list[str] = Field(min_length=1, max_length=100)
    schema_version: Literal[1] = 1
    status_mapping: dict = Field(default_factory=lambda: {"unknown": "BLOCK", "statuses": {}})
    steps: list[StepDefinition] = Field(min_length=1, max_length=64)

    @field_validator("market")
    @classmethod
    def concrete_market(cls, value):
        market = "ANY" if value == "ANY" else store_market(value)
        if not market:
            raise ValueError("流程市场必须为具体国家或显式 ANY")
        return market

    @field_validator("status_mapping")
    @classmethod
    def safe_mapping(cls, value):
        if set(value) != {"unknown", "statuses"} or value["unknown"] != "BLOCK":
            raise ValueError("状态映射必须显式阻断未知状态")
        statuses = value["statuses"]
        if not isinstance(statuses, dict) or len(statuses) > 200:
            raise ValueError("状态映射超出限制")
        if any(not isinstance(raw, str) or not raw or len(raw) > 128
               or not isinstance(mapped, str) or mapped not in PLATFORM_STATES
               for raw, mapped in statuses.items()):
            raise ValueError("平台状态映射无效，不能映射核验事实")
        return value

    @model_validator(mode="after")
    def graph(self):
        if "ANY" in self.category_scope and self.category_scope != ["ANY"]:
            raise ValueError("通配类目不能与具体类目混用")
        if len(self.category_scope) != len(set(self.category_scope)) or any(not c.strip() for c in self.category_scope):
            raise ValueError("类目范围必须非空且不可重复")
        _validate_graph(self.steps)
        return self

    def fingerprint(self):
        encoded = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 256_000:
            raise ValueError("流程定义超过大小限制")
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_graph(steps):
    nodes = {step.step_code: step for step in steps}
    if len(nodes) != len(steps):
        raise ValueError("步骤代码不可重复")
    ancestors = {}

    def visit(code, visiting):
        if code not in nodes:
            raise ValueError("依赖步骤不存在：" + code)
        if code in visiting:
            raise ValueError("步骤依赖存在环")
        if code not in ancestors:
            inherited = set()
            for dependency in nodes[code].dependencies:
                inherited.add(dependency)
                inherited.update(visit(dependency, visiting | {code}))
            ancestors[code] = inherited
        return ancestors[code]

    for code in nodes:
        visit(code, set())
    for step in steps:
        for condition in (step.applicability_condition, step.entry_condition, step.completion_condition):
            if not _condition_dependencies(condition) <= ancestors[step.step_code]:
                raise ValueError("条件引用的完成步骤必须声明为上游依赖")
    activation = [s for s in steps if s.business_type == "PLATFORM_ACTIVATION"]
    if len(activation) != 1 or not activation[0].required or activation[0].applicability_condition is not True:
        raise ValueError("流程必须有唯一且始终必需的在售核验节点")
    final = activation[0].step_code
    for step in steps:
        if step.business_type == "MONITORING":
            if final not in ancestors[step.step_code]:
                raise ValueError("经营监控必须依赖在售核验")
        elif step.required and step.step_code != final and step.step_code not in ancestors[final]:
            raise ValueError("必需步骤必须是核验节点的上游")


def _condition_dependencies(condition):
    if type(condition) is bool:
        return set()
    operator, operand = next(iter(condition.items()))
    if operator == "dependency_completed":
        return {operand}
    if operator in {"all", "any"}:
        return set().union(*(_condition_dependencies(child) for child in operand))
    if operator == "not":
        return _condition_dependencies(operand)
    return set()
