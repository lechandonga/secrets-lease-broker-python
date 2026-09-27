"""本地种子数据：模拟主体、角色、策略与机密内容。"""
from __future__ import annotations

from broker.models import Capability, Policy, Principal, Secret, SecretVersion
from broker.store import Store


def build_store(now: float = 0.0) -> Store:
    """构造一份带本地模拟数据的 Store。

    角色与策略：
    - app-reader：可读 app/ 前缀下的机密
    - app-admin：可读写 app/ 前缀下的机密
    - auditor：没有任何策略（用于触发 NO_MATCHING_POLICY）
    """
    store = Store()

    store.add_principal(Principal(name="alice", roles=frozenset({"app-reader"})))
    store.add_principal(Principal(name="bob", roles=frozenset({"app-admin"})))
    store.add_principal(Principal(name="carol", roles=frozenset({"auditor"})))

    store.add_policy(Policy(
        role="app-reader",
        path_prefix="app/",
        capabilities=frozenset({Capability.READ}),
    ))
    store.add_policy(Policy(
        role="app-admin",
        path_prefix="app/",
        capabilities=frozenset({Capability.READ, Capability.WRITE}),
    ))

    store.put_secret(Secret(
        path="app/db-password",
        versions=[SecretVersion(version=1, value="s3cret-v1", created_at=now)],
    ))
    store.put_secret(Secret(
        path="app/api-key",
        versions=[SecretVersion(version=1, value="key-v1", created_at=now)],
    ))
    store.put_secret(Secret(
        path="infra/root-token",
        versions=[SecretVersion(version=1, value="root-v1", created_at=now)],
    ))
    return store
