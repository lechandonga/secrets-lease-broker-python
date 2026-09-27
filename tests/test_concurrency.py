"""并发下发放、续租与轮换的一致性。

不变量（任意并发顺序下都必须成立）：
- 每次成功的 rotate 使版本恰好 +1，N 次并发轮换后版本 == 1 + N，无重复无丢失。
- rotate 撤销当时该路径上所有旧版本租赁；结束后凡是
  secret_version < 当前版本 的租赁都必须处于 revoked 状态。
- 指向当前版本的租赁保持可用；被撤销的租赁 use/renew 一律 lease_revoked。
"""
import logging
import threading

from broker.lease_manager import LeaseManager
from broker.models import Capability
from broker.store import Store

log = logging.getLogger(__name__)
NOW = 1000.0
THREADS = 16


def make_manager() -> LeaseManager:
    return LeaseManager(Store.seeded(), ttl=60.0, max_ttl=300.0)


def run_concurrently(fn, n=THREADS):
    results, errors = [], []

    def worker(i):
        try:
            results.append(fn(i))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    return results


def test_concurrent_issue_all_succeed_unique():
    mgr = make_manager()
    issued = run_concurrently(
        lambda i: mgr.issue("alice", "db/password", Capability.READ, NOW))
    leases = [lease for _, lease in issued]
    ids = {lease.id for lease in leases}
    log.info("concurrent issue: %d leases, unique ids=%d", len(leases), len(ids))
    assert len(ids) == THREADS
    assert all(l.secret_version == 1 for l in leases)


def test_concurrent_rotate_no_duplicate_no_lost():
    mgr = make_manager()
    rotated = run_concurrently(
        lambda i: mgr.rotate("bob", "db/password", f"pw-v{i}", NOW))
    versions = sorted(v for _, v in rotated)
    log.info("concurrent rotate returned versions=%s", versions)
    assert versions == list(range(2, 2 + THREADS))
    assert mgr.store.secrets["db/password"].current_version == 1 + THREADS


def test_concurrent_issue_and_rotate_invariant():
    mgr = make_manager()
    # 先发放一批旧版本租赁
    old_leases = [mgr.issue("alice", "db/password", Capability.READ, NOW)[1]
                  for _ in range(8)]

    def mixed(i):
        if i % 2 == 0:
            return ("rotate", mgr.rotate("bob", "db/password", f"pw-{i}", NOW))
        return ("issue", mgr.issue("alice", "db/password", Capability.READ, NOW))

    run_concurrently(mixed, THREADS)

    secret = mgr.store.secrets["db/password"]
    current = secret.current_version
    log.info("final version=%d, leases=%d", current, len(mgr.store.leases))
    for lease in mgr.store.leases.values():
        if lease.secret_version < current:
            assert lease.revoked, f"stale lease {lease.id} must be revoked"
            decision, _ = mgr.use(lease.id, NOW)
            assert decision.reason == "lease_revoked"
        else:
            assert not lease.revoked
            decision, value = mgr.use(lease.id, NOW)
            assert decision.allowed and value == secret.versions[current]
    # 预先发放的旧租赁必然已被某次轮换撤销
    assert all(l.revoked for l in old_leases)


def test_concurrent_renew_and_rotate_consistent_outcome():
    mgr = make_manager()
    lease = mgr.issue("alice", "db/password", Capability.READ, NOW)[1]

    outcomes = run_concurrently(
        lambda i: ("renew", mgr.renew(lease.id, NOW + 10)) if i % 2 == 0
        else ("rotate", mgr.rotate("bob", "db/password", f"pw-{i}", NOW)),
        THREADS)

    # 无论顺序如何：只要有一次 rotate 成功，该租赁最终必然 revoked
    assert mgr.store.leases[lease.id].revoked
    renew_results = [d for kind, (d, _) in outcomes if kind == "renew"]
    log.info("renew outcomes under rotation: %s",
             [(d.allowed, d.reason) for d in renew_results])
    for d in renew_results:
        # 续租要么在轮换前成功，要么以 lease_revoked 失败，不允许第三种结果
        assert d.allowed or d.reason == "lease_revoked"
    # 最终凭该租赁读取必须被拒绝且原因为 revoked
    decision, _ = mgr.use(lease.id, NOW + 20)
    assert not decision.allowed and decision.reason == "lease_revoked"
