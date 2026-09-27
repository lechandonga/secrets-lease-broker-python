"""数据模型：主体、角色、策略、机密、租约及判定原因枚举。"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Capability(str, enum.Enum):
    """机密路径上可被授予的能力。"""

    READ = "read"
    WRITE = "write"
    ROTATE = "rotate"


class DenyReason(str, enum.Enum):
    """发放/使用被拒绝的原因，彼此可区分。

    注意：路径不允许与机密不存在对外不可区分，
    避免由拒绝结果反推出机密是否存在。
    """

    UNKNOWN_PRINCIPAL = "unknown_principal"      # 主体未知
    NO_MATCHING_POLICY = "no_matching_policy"    # 角色没有任何匹配该路径的策略
    PATH_NOT_ALLOWED = "path_not_allowed"        # 策略未覆盖该路径（含机密不存在）
    CAPABILITY_DENIED = "capability_denied"      # 路径允许但能力不够
    LEASE_NOT_FOUND = "lease_not_found"          # 租约不存在
    LEASE_EXPIRED = "lease_expired"              # 租约已过期
    LEASE_REVOKED = "lease_revoked"              # 租约已被撤销
    RENEWAL_WINDOW_EXCEEDED = "renewal_window_exceeded"  # 续租超出最大窗口


@dataclass(frozen=True)
class Principal:
    """请求主体，隶属若干角色。"""

    name: str
    roles: frozenset[str]


@dataclass(frozen=True)
class Policy:
    """一条策略：某角色对某路径前缀授予一组能力。"""

    role: str
    path_prefix: str
    capabilities: frozenset[Capability]

    def matches_path(self, path: str) -> bool:
        return path == self.path_prefix or path.startswith(self.path_prefix.rstrip("/") + "/")


@dataclass
class SecretVersion:
    """机密的一个版本。"""

    version: int
    value: str
    created_at: float


@dataclass
class Secret:
    """一份机密：按版本保存内容，轮换即追加新版本。"""

    path: str
    versions: list[SecretVersion] = field(default_factory=list)

    @property
    def current_version(self) -> int:
        return self.versions[-1].version

    def value_at(self, version: int) -> str | None:
        for v in self.versions:
            if v.version == version:
                return v.value
        return None


@dataclass
class Lease:
    """一次发放产生的租约。

    凭据内容（secret_value / secret_version）在发放时固定，
    续租只延长 expires_at，不改变内容。
    """

    lease_id: str
    principal: str
    path: str
    capabilities: frozenset[Capability]
    secret_version: int
    secret_value: str
    issued_at: float
    expires_at: float
    max_expires_at: float  # 续租可延长到的上限：issued_at + max_ttl
    revoked: bool = False
