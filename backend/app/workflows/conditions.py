"""受限条件 DSL：三值逻辑，未知事实不当作通过；不执行表达式代码。"""

import math
import re

PREDICATES = frozenset({"verified_artifact", "asset_rights_allowed", "cost_snapshot_current",
                        "capability_available", "dependency_completed"})
PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)*$")


def validate_condition(condition, depth=0, budget=None):
    budget = [512] if budget is None else budget
    budget[0] -= 1
    if depth > 12 or budget[0] < 0:
        raise ValueError("条件超过深度或节点限制")
    if type(condition) is bool:
        return condition
    if not isinstance(condition, dict) or len(condition) != 1:
        raise ValueError("条件必须是单操作符对象或布尔常量")
    operator, operand = next(iter(condition.items()))
    if operator in {"all", "any"}:
        if not isinstance(operand, list):
            raise ValueError("all/any 必须接收条件列表")
        for child in operand:
            validate_condition(child, depth + 1, budget)
    elif operator == "not":
        validate_condition(operand, depth + 1, budget)
    elif operator in {"eq", "in"}:
        if not isinstance(operand, dict) or set(operand) != {"field", "value"}:
            raise ValueError("比较条件需要 field 与 value")
        _path(operand["field"])
        values = operand["value"] if operator == "in" else [operand["value"]]
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("in 的 value 必须为有界列表")
        if any(type(value) not in {str, int, float, bool, type(None)} for value in values):
            raise ValueError("条件仅允许标量比较值")
        if any(type(value) is float and not math.isfinite(value) for value in values):
            raise ValueError("条件数值必须有限")
    elif operator == "present":
        _path(operand)
    elif operator in PREDICATES:
        if not isinstance(operand, str) or not operand or len(operand) > 128:
            raise ValueError("业务谓词需要非空事实标识")
    else:
        raise ValueError("未注册的条件操作符：" + str(operator))
    return condition


def _path(path):
    if not isinstance(path, str) or len(path) > 128 or not PATH.fullmatch(path):
        raise ValueError("条件字段路径无效")


def evaluate_condition(condition, facts, predicates=None):
    """facts/predicates 仅由服务端构造；None 表示 UNKNOWN，不能据此跳过步骤。"""
    validate_condition(condition)
    return _evaluate(condition, facts, predicates or {})


def _evaluate(condition, facts, predicates):
    if type(condition) is bool:
        return condition
    operator, operand = next(iter(condition.items()))
    if operator in {"all", "any"}:
        values = [_evaluate(child, facts, predicates) for child in operand]
        decisive = operator == "any"
        if any(value is decisive for value in values):
            return decisive
        return None if any(value is None for value in values) else not decisive
    if operator == "not":
        value = _evaluate(operand, facts, predicates)
        return None if value is None else not value
    if operator in PREDICATES:
        value = predicates.get(operator, {}).get(operand)
        return value if type(value) is bool else None
    path = operand if operator == "present" else operand["field"]
    value = facts
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if operator == "present":
        return value is not None and value != "" and value != [] and value != {}
    if value is None:
        return None
    options = operand["value"] if operator == "in" else [operand["value"]]
    # bool 不是价格/数量；避免 Python 的 True == 1 扩大条件含义。
    return any(type(value) is type(option) and value == option for option in options)
