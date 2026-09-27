"""租约生命周期：发放、续租边界、过期、撤销。"""
from __future__ import annotations

import logging

from broker.models import Capability, DenyReason

log = logging.getLogger("test_lease")

TTL = 60.0
MAX_TTL = 300.0


def _issue(broker, principal="alice", path="app/db-password",
           caps=frozenset({Capability.READ}), ttl=TTL, max_ttl=MAX_TTL):
    log.info("发放请求 input principal=%s path=%s caps=%s ttl=%s max_ttl=%s",
             principal, path, sorted(c.value for c in caps), ttl, max_ttl)
    r = broker.issue(principal, path, caps, ttl=ttl, max_ttl=max_ttl)
    log.info("判定依据 ok=%s reason=%s lease=%s", r.ok, r.reason, r.lease_id)
    return r


def test_use_valid_lease_returns_issued_secret(broker, clock):
    r = _issue(broker)
    assert r.ok
    u = broker.use(r.lease_id, Capability.READ)
    log.info("使用判定 lease=%s -> ok=%s version=%s reason=%s",
             r.lease_id, u.ok, u.version, u.reason)
    assert u.ok
    assert u.value == "s3cret-v1"
    assert u.version == 1


def test_expired_lease_denied_with_distinct_reason(broker, clock):
    r = _issue(broker)
    clock.advance(TTL)
    u = broker.use(r.lease_id, Capability.READ)
    log.info("过期后使用 lease=%s now=%s -> reason=%s", r.lease_id, clock.now, u.reason)
    assert not u.ok
    assert u.reason is DenyReason.LEASE_EXPIRED


def test_renew_extends_within_max_window(broker, clock):
    r = _issue(broker)
    clock.advance(50.0)
    rn = broker.renew(r.lease_id, 100.0)
    log.info("续租 lease=%s extend=100 -> ok=%s expires_at=%s max=%s reason=%s",
             r.lease_id, rn.ok, rn.lease.expires_at, rn.lease.max_expires_at, rn.reason)
    assert rn.ok
    assert rn.lease.expires_at == TTL + 100.0  # 从原 expires_at=60 延长到 160
    assert rn.lease.expires_at <= rn.lease.max_expires_at == MAX_TTL
    clock.advance(90.0)  # now=140，续租后仍有效
    assert broker.use(r.lease_id).ok


def test_renew_capped_at_max_ttl(broker, clock):
    r = _issue(broker)
    clock.advance(50.0)
    rn = broker.renew(r.lease_id, 10_000.0)
    log.info("超窗续租 lease=%s -> expires_at=%s max=%s",
             r.lease_id, rn.lease.expires_at, rn.lease.max_expires_at)
    assert rn.ok
    assert rn.lease.expires_at == MAX_TTL  # 被钳制到最大窗口


def test_renew_after_hitting_max_window_denied(broker, clock):
    r = _issue(broker)
    clock.advance(50.0)
    broker.renew(r.lease_id, 10_000.0)  # expires_at 已顶到 max
    rn = broker.renew(r.lease_id, 1.0)
    log.info("再次续租 lease=%s -> ok=%s reason=%s", r.lease_id, rn.ok, rn.reason)
    assert not rn.ok
    assert rn.reason is DenyReason.RENEWAL_WINDOW_EXCEEDED


def test_renew_expired_lease_denied(broker, clock):
    r = _issue(broker)
    clock.advance(TTL)
    rn = broker.renew(r.lease_id, 60.0)
    log.info("过期后续租 lease=%s -> ok=%s reason=%s", r.lease_id, rn.ok, rn.reason)
    assert not rn.ok
    assert rn.reason is DenyReason.LEASE_EXPIRED


def test_renew_revoked_lease_denied_and_reason_distinct(broker):
    r = _issue(broker)
    broker.revoke(r.lease_id)
    rn = broker.renew(r.lease_id, 60.0)
    log.info("撤销后续租 lease=%s -> ok=%s reason=%s", r.lease_id, rn.ok, rn.reason)
    assert not rn.ok
    assert rn.reason is DenyReason.LEASE_REVOKED


def test_use_revoked_lease_denied(broker):
    r = _issue(broker)
    broker.revoke(r.lease_id)
    u = broker.use(r.lease_id)
    log.info("撤销后使用 lease=%s -> ok=%s reason=%s", r.lease_id, u.ok, u.reason)
    assert not u.ok
    assert u.reason is DenyReason.LEASE_REVOKED


def test_renew_does_not_change_credential_content(broker, clock):
    r = _issue(broker)
    broker.rotate("app/db-password", "s3cret-v2")
    broker.renew(r.lease_id, 120.0)
    u = broker.use(r.lease_id, Capability.READ)
    log.info("轮换后续租旧凭据 lease=%s -> value=%s version=%s",
             r.lease_id, u.value, u.version)
    assert u.ok
    assert u.version == 1 and u.value == "s3cret-v1"  # 内容不随续租改变


def test_use_with_missing_capability_denied(broker):
    r = _issue(broker, caps=frozenset({Capability.READ}))
    u = broker.use(r.lease_id, Capability.WRITE)
    log.info("能力不足使用 lease=%s -> reason=%s", r.lease_id, u.reason)
    assert not u.ok
    assert u.reason is DenyReason.CAPABILITY_DENIED


def test_use_unknown_lease_denied(broker):
    u = broker.use("nope")
    assert u.reason is DenyReason.LEASE_NOT_FOUND
