"""拒绝原因区分：主体未知 / 无匹配策略 / 路径不允许 / 能力不够。

另验证被拒绝的请求无法反推出机密是否存在：
对未被策略覆盖的路径，机密存在与否返回原因完全一致。
"""
from __future__ import annotations

import logging

from broker.models import Capability, DenyReason

log = logging.getLogger("test_policy")


def _issue(broker, principal, path, caps):
    log.info("发放请求 input principal=%s path=%s caps=%s", principal, path, sorted(c.value for c in caps))
    result = broker.issue(principal, path, caps)
    log.info("判定依据 result ok=%s reason=%s", result.ok, result.reason)
    return result


def test_allow_reader_read_existing_secret(broker):
    r = _issue(broker, "alice", "app/db-password", frozenset({Capability.READ}))
    assert r.ok
    assert r.reason is None


def test_unknown_principal(broker):
    r = _issue(broker, "nobody", "app/db-password", frozenset({Capability.READ}))
    assert not r.ok
    assert r.reason is DenyReason.UNKNOWN_PRINCIPAL


def test_no_matching_policy_role_has_no_rules(broker):
    # carol 的 auditor 角色没有挂任何策略
    r = _issue(broker, "carol", "app/db-password", frozenset({Capability.READ}))
    assert not r.ok
    assert r.reason is DenyReason.NO_MATCHING_POLICY


def test_path_not_allowed_other_prefix(broker):
    # app 角色访问 infra 前缀：路径不允许
    r = _issue(broker, "alice", "infra/root-token", frozenset({Capability.READ}))
    assert not r.ok
    assert r.reason is DenyReason.PATH_NOT_ALLOWED


def test_path_not_allowed_nonexistent_secret(broker):
    # 同前缀但机密不存在：仍为路径不允许，不能泄露存在性
    r = _issue(broker, "alice", "app/does-not-exist", frozenset({Capability.READ}))
    assert not r.ok
    assert r.reason is DenyReason.PATH_NOT_ALLOWED


def test_path_decision_independent_of_secret_existence(broker):
    # 核心不泄露性：同一条不被策略覆盖的请求，机密存在与不存在原因一致
    existing = _issue(broker, "alice", "infra/root-token", frozenset({Capability.READ}))
    missing = _issue(broker, "alice", "infra/no-such-thing", frozenset({Capability.READ}))
    assert existing.reason == missing.reason == DenyReason.PATH_NOT_ALLOWED


def test_capability_denied(broker):
    # reader 只有 read，申请 write 必须被区分
    r = _issue(broker, "alice", "app/db-password", frozenset({Capability.WRITE}))
    assert not r.ok
    assert r.reason is DenyReason.CAPABILITY_DENIED


def test_capability_denied_even_when_read_granted(broker):
    r = _issue(broker, "alice", "app/db-password",
               frozenset({Capability.READ, Capability.WRITE}))
    assert not r.ok
    assert r.reason is DenyReason.CAPABILITY_DENIED


def test_admin_can_write(broker):
    r = _issue(broker, "bob", "app/db-password", frozenset({Capability.WRITE}))
    assert r.ok
