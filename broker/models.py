"""核心类型定义：主体、角色、策略、机密、租赁与判定结果。"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Capability(enum.Enum):
    """对机密路径可请求的能力。"""

    READ = "read"
    WRITE = "write"


class DenialReason(enum.Enum):
    """请求被拒绝的可区分原因。"""

    UNKNOWN_PRINCIPAL = "unknown_principal"
    NO_MATCHING_POLICY = "no_matching_policy"
    PATH_NOT_ALLOWED = "path_not_allowed"
    CAPABILITY_NOT_GRANTED = "capability_not_granted"
    LEASE_NOT_FOUND = "lease_not_found"
    LEASE_EXPIRED = "lease_expired"
    LEASE_REVOKED = "lease_revoked"
    MAX_TTL_EXCEEDED = "max_ttl_exceeded"


@dataclass(frozen=True)
class Principal:
    id: str
    roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Policy:
    """允许某角色对某路径前缀行使某些能力。"""

    role: str
    path_prefix: str
    capabilities: frozenset[Capability]


@dataclass
class Secret:
    path: str
    current_version: int = 0
    versions: dict[int, str] = field(default_factory=dict)


@dataclass
class Lease:
    id: str
    secret_path: str
    secret_version: int
    principal_id: str
    issued_at: float
    expires_at: float
    max_expires_at: float
    revoked: bool = False

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class Decision:
    """鉴权/操作判定结果：允许或带原因的拒绝。"""

    allowed: bool
    reason: str | None = None
    detail: str = ""

    @staticmethod
    def allow() -> "Decision":
        return Decision(allowed=True)

    @staticmethod
    def deny(reason: str, detail: str = "") -> "Decision":
        return Decision(allowed=False, reason=reason, detail=detail)
