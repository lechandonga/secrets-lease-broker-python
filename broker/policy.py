"""策略评估：判定主体是否有权对某路径行使某能力，并给出可区分原因。

判定顺序（每种拒绝都有独立原因，且不回泄机密是否存在）：
1. 主体未知        -> unknown_principal
2. 主体无任何策略  -> no_matching_policy
3. 有策略但路径不匹配 -> path_not_allowed
4. 路径匹配但能力不含 -> capability_not_granted
"""
from __future__ import annotations

from .models import Capability, Decision, DenialReason, Principal, Policy


def evaluate(
    principal: Principal | None,
    policies: list[Policy],
    path: str,
    capability: Capability,
) -> Decision:
    if principal is None:
        return Decision.deny(DenialReason.UNKNOWN_PRINCIPAL.value,
                             "principal is not registered")

    own = [p for p in policies if p.role in principal.roles]
    if not own:
        return Decision.deny(DenialReason.NO_MATCHING_POLICY.value,
                             f"no policy for roles {sorted(principal.roles)}")

    path_ok = [p for p in own if path.startswith(p.path_prefix)]
    if not path_ok:
        return Decision.deny(DenialReason.PATH_NOT_ALLOWED.value,
                             f"no policy covers path {path!r}")

    if not any(capability in p.capabilities for p in path_ok):
        return Decision.deny(DenialReason.CAPABILITY_NOT_GRANTED.value,
                             f"capability {capability.value!r} not granted for {path!r}")

    return Decision.allow()
