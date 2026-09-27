"""租约管理：发放、续租、撤销、使用校验与机密轮换。

语义约定：
- 发放：凭据内容（机密版本与值）在发放时固定，租约带 expires_at 与
  max_expires_at（= issued_at + max_ttl）。
- 续租：只延长 expires_at，不得超过 max_expires_at；不改变凭据内容。
  已过期或已撤销的租约不可续租，原因可区分。
- 撤销：撤销后使用返回 LEASE_REVOKED，与过期 LEASE_EXPIRED 可区分。
- 轮换：给机密追加新版本。规则——已发放的旧版本租约在过期/撤销前
  仍然有效（读到发放时的旧值），新发放一律使用最新版本。
  该规则不依赖任何并发顺序：所有变更都在同一把锁内完成。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from broker.models import Capability, DenyReason, Lease, SecretVersion
from broker.store import Store


@dataclass(frozen=True)
class LeaseResult:
    """租约操作结果。ok 为 False 时 reason 必非 None。"""

    ok: bool
    lease: Lease | None = None
    reason: DenyReason | None = None


@dataclass(frozen=True)
class UseResult:
    """凭据使用结果。"""

    ok: bool
    value: str | None = None
    version: int | None = None
    reason: DenyReason | None = None


class LeaseManager:
    """租约生命周期管理。所有公开方法都在 store.lock 内完成状态变更。"""

    def __init__(self, store: Store, clock: Callable[[], float]) -> None:
        self._store = store
        self._clock = clock

    def issue(
        self,
        principal: str,
        path: str,
        capabilities: frozenset[Capability],
        ttl: float,
        max_ttl: float,
    ) -> LeaseResult:
        """发放租约。调用前策略必须已放行且机密存在。"""
        with self._store.lock:
            secret = self._store.get_secret(path)
            if secret is None:
                return LeaseResult(ok=False, reason=DenyReason.PATH_NOT_ALLOWED)
            now = self._clock()
            version = secret.current_version
            lease = Lease(
                lease_id=uuid.uuid4().hex,
                principal=principal,
                path=path,
                capabilities=capabilities,
                secret_version=version,
                secret_value=secret.value_at(version) or "",
                issued_at=now,
                expires_at=now + ttl,
                max_expires_at=now + max_ttl,
            )
            self._store.put_lease(lease)
            return LeaseResult(ok=True, lease=lease)

    def renew(self, lease_id: str, extend_by: float) -> LeaseResult:
        """续租：延长 expires_at，上限 max_expires_at，内容不变。"""
        with self._store.lock:
            lease = self._store.get_lease(lease_id)
            if lease is None:
                return LeaseResult(ok=False, reason=DenyReason.LEASE_NOT_FOUND)
            if lease.revoked:
                return LeaseResult(ok=False, reason=DenyReason.LEASE_REVOKED)
            now = self._clock()
            if now >= lease.expires_at:
                return LeaseResult(ok=False, reason=DenyReason.LEASE_EXPIRED)
            if lease.expires_at >= lease.max_expires_at:
                return LeaseResult(ok=False, reason=DenyReason.RENEWAL_WINDOW_EXCEEDED)
            lease.expires_at = min(lease.expires_at + extend_by, lease.max_expires_at)
            return LeaseResult(ok=True, lease=lease)

    def revoke(self, lease_id: str) -> LeaseResult:
        """撤销租约，幂等。"""
        with self._store.lock:
            lease = self._store.get_lease(lease_id)
            if lease is None:
                return LeaseResult(ok=False, reason=DenyReason.LEASE_NOT_FOUND)
            lease.revoked = True
            return LeaseResult(ok=True, lease=lease)

    def use(self, lease_id: str, capability: Capability) -> UseResult:
        """使用凭据读取机密内容。过期与撤销原因可区分。"""
        with self._store.lock:
            lease = self._store.get_lease(lease_id)
            if lease is None:
                return UseResult(ok=False, reason=DenyReason.LEASE_NOT_FOUND)
            if lease.revoked:
                return UseResult(ok=False, reason=DenyReason.LEASE_REVOKED)
            if self._clock() >= lease.expires_at:
                return UseResult(ok=False, reason=DenyReason.LEASE_EXPIRED)
            if capability not in lease.capabilities:
                return UseResult(ok=False, reason=DenyReason.CAPABILITY_DENIED)
            return UseResult(ok=True, value=lease.secret_value, version=lease.secret_version)

    def rotate(self, path: str, new_value: str) -> int | None:
        """轮换机密：追加新版本并返回新版本号。

        在锁内完成，任意并发顺序下版本号单调递增、不会重复轮换；
        旧版本租约按其自身过期/撤销规则继续有效。
        """
        with self._store.lock:
            secret = self._store.get_secret(path)
            if secret is None:
                return None
            version = secret.current_version + 1
            secret.versions.append(
                SecretVersion(version=version, value=new_value, created_at=self._clock())
            )
            return version
