"""门面：组合策略判定与租约管理，对外提供统一入口。"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from broker import policy
from broker.leases import LeaseManager, LeaseResult, UseResult
from broker.models import Capability, DenyReason
from broker.store import Store

DEFAULT_TTL = 60.0
DEFAULT_MAX_TTL = 300.0


@dataclass(frozen=True)
class IssueResult:
    """发放结果：先过策略，再放租约。"""

    ok: bool
    lease_id: str | None = None
    expires_at: float | None = None
    max_expires_at: float | None = None
    reason: DenyReason | None = None


class Broker:
    """本地短时凭据租赁服务入口。"""

    def __init__(self, store: Store, clock: Callable[[], float] = time.monotonic) -> None:
        self.store = store
        self.leases = LeaseManager(store, clock)

    def issue(
        self,
        principal: str,
        path: str,
        requested: frozenset[Capability],
        ttl: float = DEFAULT_TTL,
        max_ttl: float = DEFAULT_MAX_TTL,
    ) -> IssueResult:
        """按策略判定后发放租约；拒绝原因见 DenyReason。"""
        with self.store.lock:
            decision = policy.evaluate(self.store, principal, path, requested)
            if not decision.allowed:
                return IssueResult(ok=False, reason=decision.reason)
            result: LeaseResult = self.leases.issue(
                principal, path, requested, ttl, max_ttl
            )
            if not result.ok or result.lease is None:
                return IssueResult(ok=False, reason=result.reason)
            return IssueResult(
                ok=True,
                lease_id=result.lease.lease_id,
                expires_at=result.lease.expires_at,
                max_expires_at=result.lease.max_expires_at,
            )

    def renew(self, lease_id: str, extend_by: float) -> LeaseResult:
        return self.leases.renew(lease_id, extend_by)

    def revoke(self, lease_id: str) -> LeaseResult:
        return self.leases.revoke(lease_id)

    def use(self, lease_id: str, capability: Capability = Capability.READ) -> UseResult:
        return self.leases.use(lease_id, capability)

    def rotate(self, path: str, new_value: str) -> int | None:
        return self.leases.rotate(path, new_value)
