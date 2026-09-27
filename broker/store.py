"""内存数据存储：用本地数据模拟主体、角色、策略与机密。

所有读写都经过同一把可重入锁，保证并发下状态一致、
不会出现半截更新或重复轮换。
"""
from __future__ import annotations

import threading

from broker.models import Lease, Policy, Principal, Secret


class Store:
    """进程内数据存储，持有一把全局可重入锁。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.principals: dict[str, Principal] = {}
        self.policies: list[Policy] = []
        self.secrets: dict[str, Secret] = {}
        self.leases: dict[str, Lease] = {}

    # ---- 主体 ----
    def add_principal(self, principal: Principal) -> None:
        with self.lock:
            self.principals[principal.name] = principal

    def get_principal(self, name: str) -> Principal | None:
        with self.lock:
            return self.principals.get(name)

    # ---- 策略 ----
    def add_policy(self, policy: Policy) -> None:
        with self.lock:
            self.policies.append(policy)

    def list_policies(self) -> list[Policy]:
        with self.lock:
            return list(self.policies)

    # ---- 机密 ----
    def put_secret(self, secret: Secret) -> None:
        with self.lock:
            self.secrets[secret.path] = secret

    def get_secret(self, path: str) -> Secret | None:
        with self.lock:
            return self.secrets.get(path)

    # ---- 租约 ----
    def put_lease(self, lease: Lease) -> None:
        with self.lock:
            self.leases[lease.lease_id] = lease

    def get_lease(self, lease_id: str) -> Lease | None:
        with self.lock:
            return self.leases.get(lease_id)
