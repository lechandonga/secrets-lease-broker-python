"""拒绝原因可区分、且不泄露机密存在性。"""
import logging

from broker.lease_manager import LeaseManager
from broker.models import Capability
from broker.store import Store

log = logging.getLogger(__name__)


def make_manager() -> LeaseManager:
    return LeaseManager(Store.seeded(), ttl=60.0, max_ttl=300.0)


def check(mgr, principal, path, cap, expect_reason):
    decision, lease = mgr.issue(principal, path, cap, now=1000.0)
    log.info("issue principal=%r path=%r cap=%s -> allowed=%s reason=%s detail=%s",
             principal, path, cap.value, decision.allowed, decision.reason, decision.detail)
    assert not decision.allowed and lease is None
    assert decision.reason == expect_reason


def test_unknown_principal():
    check(make_manager(), "nobody", "db/password", Capability.READ, "unknown_principal")


def test_no_matching_policy():
    # dave 已注册但没有任何角色
    check(make_manager(), "dave", "db/password", Capability.READ, "no_matching_policy")


def test_path_not_allowed():
    # carol 的策略只覆盖 kv/，请求 db/ 下的路径
    check(make_manager(), "carol", "db/password", Capability.READ, "path_not_allowed")


def test_capability_not_granted():
    # alice 只有 read，请求 write
    check(make_manager(), "alice", "db/password", Capability.WRITE, "capability_not_granted")


def test_nonexistent_secret_does_not_leak_existence():
    mgr = make_manager()
    # alice 的策略允许 db/ 前缀，但 db/ghost 不存在：
    # 拒绝原因必须与"路径不允许"完全一致，无法反推机密是否存在
    d1, _ = mgr.issue("alice", "db/ghost", Capability.READ, now=1000.0)
    d2, _ = mgr.issue("carol", "db/password", Capability.READ, now=1000.0)
    log.info("nonexistent -> %s / %s ; disallowed-path -> %s / %s",
             d1.reason, d1.detail, d2.reason, d2.detail)
    assert d1.reason == d2.reason == "path_not_allowed"
    # 拒绝文案不得包含任何关于机密是否存在的信息
    assert "exist" not in d1.detail.lower()


def test_allowed_issue():
    mgr = make_manager()
    decision, lease = mgr.issue("alice", "db/password", Capability.READ, now=1000.0)
    log.info("issue alice db/password read -> allowed=%s lease=%s", decision.allowed, lease)
    assert decision.allowed and lease is not None
    assert lease.secret_version == 1 and lease.expires_at == 1060.0
