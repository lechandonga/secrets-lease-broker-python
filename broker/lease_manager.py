"""租赁管理：发放、续租、撤销、轮换。

并发与一致性约定：
- 所有操作都在 store.lock（可重入锁）内完成，检查与状态修改是原子的，
  不会出现半截状态；同一机密上的发放/续租/轮换按锁的获取顺序串行化。
- 轮换规则（与并发顺序无关）：rotate 使路径版本 +1，并撤销该路径上
  所有指向旧版本的现存租赁；此后新租赁只针对当前版本。
- 续租只延长 expires_at（不超过 max_expires_at），不改动机密内容与版本。
- 策略允许但路径下无机密时，以 path_not_allowed 拒绝，避免回泄机密是否存在。
"""
from __future__ import annotations

import uuid

from .models import Capability, Decision, DenialReason, Lease
from .policy import evaluate
from .store import Store


class LeaseManager:
    def __init__(self, store: Store, ttl: float, max_ttl: float) -> None:
        self.store = store
        self.ttl = ttl
        self.max_ttl = max_ttl

    def issue(self, principal_id: str, path: str, capability: Capability,
              now: float) -> tuple[Decision, Lease | None]:
        with self.store.lock:
            decision = evaluate(self.store.principals.get(principal_id),
                                self.store.policies, path, capability)
            if not decision.allowed:
                return decision, None
            secret = self.store.secrets.get(path)
            if secret is None:
                # 不暴露机密是否存在：与路径不允许使用同一拒绝原因
                return Decision.deny(DenialReason.PATH_NOT_ALLOWED.value,
                                     f"no policy covers path {path!r}"), None
            lease = Lease(
                id=uuid.uuid4().hex,
                secret_path=path,
                secret_version=secret.current_version,
                principal_id=principal_id,
                issued_at=now,
                expires_at=now + self.ttl,
                max_expires_at=now + self.max_ttl,
            )
            self.store.leases[lease.id] = lease
            return Decision.allow(), lease

    def renew(self, lease_id: str, now: float) -> tuple[Decision, Lease | None]:
        with self.store.lock:
            lease = self.store.leases.get(lease_id)
            if lease is None:
                return Decision.deny(DenialReason.LEASE_NOT_FOUND.value), None
            if lease.revoked:
                return Decision.deny(DenialReason.LEASE_REVOKED.value), None
            if lease.is_expired(now):
                return Decision.deny(DenialReason.LEASE_EXPIRED.value), None
            if lease.expires_at >= lease.max_expires_at:
                return Decision.deny(DenialReason.MAX_TTL_EXCEEDED.value,
                                     "lease already at max lifetime"), None
            # 只延长有效期，内容与版本不变
            lease.expires_at = min(now + self.ttl, lease.max_expires_at)
            return Decision.allow(), lease

    def revoke(self, lease_id: str, now: float) -> Decision:
        with self.store.lock:
            lease = self.store.leases.get(lease_id)
            if lease is None:
                return Decision.deny(DenialReason.LEASE_NOT_FOUND.value)
            lease.revoked = True
            return Decision.allow()

    def use(self, lease_id: str, now: float) -> tuple[Decision, str | None]:
        """凭租赁读取机密内容；不存在/撤销/过期分别给出原因。"""
        with self.store.lock:
            lease = self.store.leases.get(lease_id)
            if lease is None:
                return Decision.deny(DenialReason.LEASE_NOT_FOUND.value), None
            if lease.revoked:
                return Decision.deny(DenialReason.LEASE_REVOKED.value), None
            if lease.is_expired(now):
                return Decision.deny(DenialReason.LEASE_EXPIRED.value), None
            secret = self.store.secrets[lease.secret_path]
            return Decision.allow(), secret.versions[lease.secret_version]

    def rotate(self, principal_id: str, path: str, new_value: str,
               now: float) -> tuple[Decision, int | None]:
        """轮换机密：版本 +1，撤销该路径上所有旧版本租赁。"""
        with self.store.lock:
            decision = evaluate(self.store.principals.get(principal_id),
                                self.store.policies, path, Capability.WRITE)
            if not decision.allowed:
                return decision, None
            secret = self.store.secrets.get(path)
            if secret is None:
                return Decision.deny(DenialReason.PATH_NOT_ALLOWED.value,
                                     f"no policy covers path {path!r}"), None
            secret.current_version += 1
            secret.versions[secret.current_version] = new_value
            for lease in self.store.leases.values():
                if lease.secret_path == path and not lease.revoked:
                    lease.revoked = True
            return Decision.allow(), secret.current_version
