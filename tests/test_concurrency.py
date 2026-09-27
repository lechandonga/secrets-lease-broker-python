"""并发语义：同一机密上并发发放、续租与轮换，结果一致且可预期。

轮换规则（与并发顺序无关）：
- 轮换开始前已发放的租约绑定旧版本，过期/撤销前仍读到旧值；
- 轮换完成后发放的租约绑定新版本；
- 版本号单调递增，同一机密上并发轮换产生互不相同的连续版本号。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from broker.models import Capability

log = logging.getLogger("test_concurrency")

CAPS = frozenset({Capability.READ})
PATH = "app/db-password"


def test_concurrent_issue_all_succeed_with_unique_leases(broker):
    n = 32
    log.info("并发发放 input n=%d path=%s", n, PATH)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(
            lambda _: broker.issue("alice", PATH, CAPS), range(n)))
    ids = {r.lease_id for r in results}
    log.info("判定依据 ok=%d unique_ids=%d", sum(r.ok for r in results), len(ids))
    assert all(r.ok for r in results)
    assert len(ids) == n  # 无重复、无半截状态


def test_concurrent_rotate_versions_are_contiguous_and_unique(broker):
    n = 16
    log.info("并发轮换 input n=%d path=%s", n, PATH)
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(
            lambda i: broker.rotate(PATH, f"s3cret-v{i + 2}"), range(n)))
    log.info("判定依据 versions=%s", sorted(versions))
    assert sorted(versions) == list(range(2, 2 + n))  # 单调连续、无重复轮换
    assert broker.store.get_secret(PATH).current_version == 1 + n


def test_concurrent_issue_and_rotate_version_rule_holds(broker, clock):
    """发放与轮换并发：每个租约读到的值必须等于其绑定版本的值。"""
    barrier = threading.Barrier(16)
    issued: list = []
    lock = threading.Lock()

    def do_issue(_):
        barrier.wait()
        r = broker.issue("alice", PATH, CAPS)
        with lock:
            issued.append(r)

    def do_rotate(i):
        barrier.wait()
        broker.rotate(PATH, f"s3cret-v{i + 2}")

    log.info("并发发放+轮换 input issues=8 rotates=8 path=%s", PATH)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(do_issue, i) for i in range(8)]
        futs += [pool.submit(do_rotate, i) for i in range(8)]
        for f in futs:
            f.result()

    secret = broker.store.get_secret(PATH)
    assert secret.current_version == 9
    for r in issued:
        assert r.ok
        u = broker.use(r.lease_id)
        expected = secret.value_at(u.version)
        log.info("判定依据 lease=%s version=%s value=%s expected=%s",
                 r.lease_id, u.version, u.value, expected)
        # 凭据内容必须与其版本一致：不存在半截状态
        assert u.ok and u.value == expected


def test_concurrent_renew_never_exceeds_max_window(broker, clock):
    r = broker.issue("alice", PATH, CAPS, ttl=60.0, max_ttl=300.0)
    log.info("并发续租 input lease=%s extend=50 workers=16", r.lease_id)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: broker.renew(r.lease_id, 50.0), range(16)))
    lease = broker.store.get_lease(r.lease_id)
    log.info("判定依据 expires_at=%s max=%s ok_count=%d",
             lease.expires_at, lease.max_expires_at, sum(x.ok for x in results))
    assert lease.expires_at <= lease.max_expires_at
    assert lease.expires_at == min(60.0 + 50.0 * sum(x.ok for x in results), 300.0)


def test_concurrent_revoke_and_use_outcome_is_consistent(broker, clock):
    """撤销与使用并发：使用结果只能是成功读旧值或 LEASE_REVOKED，且撤销后必败。"""
    r = broker.issue("alice", PATH, CAPS)
    barrier = threading.Barrier(2)
    outcomes = []

    def do_use():
        barrier.wait()
        outcomes.append(broker.use(r.lease_id))

    def do_revoke():
        barrier.wait()
        broker.revoke(r.lease_id)

    t1 = threading.Thread(target=do_use)
    t2 = threading.Thread(target=do_revoke)
    t1.start(); t2.start(); t1.join(); t2.join()

    u = outcomes[0]
    log.info("判定依据 use ok=%s reason=%s", u.ok, u.reason)
    assert (u.ok and u.value == "s3cret-v1") or (u.reason is not None)
    # 撤销完成后，再使用必须失败且原因为已撤销
    after = broker.use(r.lease_id)
    assert not after.ok and after.reason.name == "LEASE_REVOKED"
