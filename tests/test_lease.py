"""续租边界、过期与撤销。"""
import logging

from broker.lease_manager import LeaseManager
from broker.models import Capability
from broker.store import Store

log = logging.getLogger(__name__)


def make_manager() -> LeaseManager:
    return LeaseManager(Store.seeded(), ttl=60.0, max_ttl=150.0)


def issue_alice(mgr, now=1000.0):
    decision, lease = mgr.issue("alice", "db/password", Capability.READ, now)
    assert decision.allowed
    return lease


def test_renew_extends_within_window():
    mgr = make_manager()
    lease = issue_alice(mgr)
    decision, renewed = mgr.renew(lease.id, now=1030.0)
    log.info("renew at=1030 expires_at was 1060 -> %s", renewed.expires_at)
    assert decision.allowed and renewed.expires_at == 1090.0


def test_renew_capped_at_max_ttl():
    mgr = make_manager()
    lease = issue_alice(mgr)
    decision, renewed = mgr.renew(lease.id, now=1050.0)
    assert decision.allowed and renewed.expires_at == 1110.0
    # 1100 + 60 = 1160 超过 max 1150，应被截断到 1150
    decision, renewed = mgr.renew(lease.id, now=1100.0)
    log.info("renew at=1100 -> expires_at=%s max=%s", renewed.expires_at, renewed.max_expires_at)
    assert decision.allowed and renewed.expires_at == 1150.0
    # 已到上限，再次续租必须拒绝且原因可区分
    decision, _ = mgr.renew(lease.id, now=1110.0)
    log.info("renew at max -> allowed=%s reason=%s", decision.allowed, decision.reason)
    assert not decision.allowed and decision.reason == "max_ttl_exceeded"


def test_renew_does_not_change_content():
    mgr = make_manager()
    lease = issue_alice(mgr)
    before = (lease.secret_version, lease.secret_path)
    mgr.renew(lease.id, now=1030.0)
    _, value = mgr.use(lease.id, now=1040.0)
    log.info("after renew version=%s value=%r", lease.secret_version, value)
    assert (lease.secret_version, lease.secret_path) == before
    assert value == "s3cret-pw"


def test_use_after_expiry_rejected():
    mgr = make_manager()
    lease = issue_alice(mgr)
    decision, _ = mgr.use(lease.id, now=1060.0)  # expires_at == 1060，到期即失效
    log.info("use after expiry -> reason=%s", decision.reason)
    assert not decision.allowed and decision.reason == "lease_expired"
    # 过期后续租同样拒绝
    decision, _ = mgr.renew(lease.id, now=1061.0)
    assert not decision.allowed and decision.reason == "lease_expired"


def test_use_after_revoke_rejected():
    mgr = make_manager()
    lease = issue_alice(mgr)
    assert mgr.revoke(lease.id, now=1010.0).allowed
    decision, _ = mgr.use(lease.id, now=1020.0)
    log.info("use after revoke -> reason=%s", decision.reason)
    assert not decision.allowed and decision.reason == "lease_revoked"
    decision, _ = mgr.renew(lease.id, now=1020.0)
    assert not decision.allowed and decision.reason == "lease_revoked"


def test_unknown_lease():
    mgr = make_manager()
    for op in (mgr.use, mgr.renew):
        decision, _ = op("no-such-lease", now=1000.0)
        log.info("%s unknown lease -> reason=%s", op.__name__, decision.reason)
        assert not decision.allowed and decision.reason == "lease_not_found"
