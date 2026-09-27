"""本地内存数据存储：主体、策略、机密与租赁的种子数据与存取。"""
from __future__ import annotations

import threading

from .models import Capability, Lease, Policy, Principal, Secret


class Store:
    """进程内数据存储，所有共享状态集中在此，配合锁保证并发一致。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.principals: dict[str, Principal] = {}
        self.policies: list[Policy] = []
        self.secrets: dict[str, Secret] = {}
        self.leases: dict[str, Lease] = {}

    @staticmethod
    def seeded() -> "Store":
        """构造带本地模拟数据的存储。

        角色与策略：
        - db-reader : 可读 db/ 前缀
        - db-admin  : 可读写 db/ 前缀
        - kv-reader : 可读 kv/ 前缀
        """
        s = Store()
        s.principals = {
            "alice": Principal("alice", frozenset({"db-reader"})),
            "bob": Principal("bob", frozenset({"db-admin"})),
            "carol": Principal("carol", frozenset({"kv-reader"})),
            "dave": Principal("dave", frozenset()),  # 已注册但无任何角色
        }
        s.policies = [
            Policy("db-reader", "db/", frozenset({Capability.READ})),
            Policy("db-admin", "db/", frozenset({Capability.READ, Capability.WRITE})),
            Policy("kv-reader", "kv/", frozenset({Capability.READ})),
        ]
        s.secrets = {
            "db/password": Secret("db/password", 1, {1: "s3cret-pw"}),
            "db/apikey": Secret("db/apikey", 1, {1: "api-key-1"}),
            "kv/token": Secret("kv/token", 1, {1: "tok-1"}),
        }
        return s
