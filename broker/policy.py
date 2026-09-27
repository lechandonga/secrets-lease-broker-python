"""策略判定：根据主体角色与策略决定是否允许发放。

判定顺序固定，四种拒绝原因彼此可区分：
1. 主体未知            -> UNKNOWN_PRINCIPAL
2. 主体角色没有任何策略 -> NO_MATCHING_POLICY
3. 策略未覆盖该路径     -> PATH_NOT_ALLOWED（机密不存在也归并到这里，不泄露存在性）
4. 路径覆盖但能力不够   -> CAPABILITY_DENIED

机密存在性只在策略完全放行之后才检查；对未被策略覆盖的路径，
无论机密是否存在都返回相同的 PATH_NOT_ALLOWED，
因此无法从拒绝结果反推机密是否存在。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from broker.models import Capability, DenyReason
from broker.store import Store


@dataclass(frozen=True)
class Decision:
    """一次判定结果。allowed 为 False 时 reason 必非 None。"""

    allowed: bool
    reason: DenyReason | None = None
    granted: frozenset[Capability] = field(default_factory=frozenset)


def evaluate(
    store: Store,
    principal_name: str,
    path: str,
    requested: frozenset[Capability],
) -> Decision:
    """对一次访问请求做策略判定。调用方需持有 store.lock。"""
    principal = store.get_principal(principal_name)
    if principal is None:
        return Decision(allowed=False, reason=DenyReason.UNKNOWN_PRINCIPAL)

    role_policies = [p for p in store.list_policies() if p.role in principal.roles]
    if not role_policies:
        return Decision(allowed=False, reason=DenyReason.NO_MATCHING_POLICY)

    matching = [p for p in role_policies if p.matches_path(path)]
    if not matching:
        # 机密是否存在不影响此结果：存在性检查在放行之后。
        return Decision(allowed=False, reason=DenyReason.PATH_NOT_ALLOWED)

    granted = frozenset().union(*(p.capabilities for p in matching))
    if not requested <= granted:
        return Decision(allowed=False, reason=DenyReason.CAPABILITY_DENIED, granted=granted)

    if store.get_secret(path) is None:
        # 策略放行但机密不存在：与“路径不允许”同等对待，不泄露存在性。
        return Decision(allowed=False, reason=DenyReason.PATH_NOT_ALLOWED)

    return Decision(allowed=True, granted=granted)
