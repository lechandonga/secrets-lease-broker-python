# secrets-lease-broker-python

本地短时凭据租赁服务。用内存数据模拟主体、角色、策略与机密内容，
按策略决定是否发放带有效期的凭据租约，支持续租、撤销与机密轮换。

## 结构

```
broker/
  models.py   数据模型与 DenyReason 枚举
  store.py    内存存储，一把可重入锁保护全部状态
  policy.py   策略判定（发放前的鉴权）
  leases.py   租约生命周期：发放/续租/撤销/使用/轮换
  broker.py   门面，组合策略判定与租约管理
  seed.py     本地模拟数据
main.py       FastAPI HTTP 入口（薄适配层）
tests/        策略、生命周期、并发三组测试
```

## 策略模型

- **主体（Principal）** 隶属若干角色；**策略（Policy）** 把某个角色绑定到
  一个路径前缀和一组能力（`read` / `write` / `rotate`）。
- 判定顺序固定，四种拒绝原因彼此可区分：

  | 顺序 | 条件 | 原因 |
  |---|---|---|
  | 1 | 主体不存在 | `unknown_principal` |
  | 2 | 主体的角色没有任何策略 | `no_matching_policy` |
  | 3 | 策略未覆盖该路径 | `path_not_allowed` |
  | 4 | 路径覆盖但申请的能力不全 | `capability_denied` |

- **不泄露机密存在性**：机密是否存在只在策略完全放行之后才检查；
  对未被策略覆盖的路径，无论机密是否存在都返回 `path_not_allowed`，
  因此无法从拒绝结果反推某个机密是否存在
  （见 `test_path_decision_independent_of_secret_existence`）。

## 租赁语义

- **发放**：凭据内容（机密版本与值）在发放时固定；租约带
  `expires_at = issued_at + ttl` 与续租上限 `max_expires_at = issued_at + max_ttl`。
- **续租**：只延长 `expires_at`（从原到期时间累加），并被钳制到
  `max_expires_at`；不改变凭据内容。已顶到上限再续租返回
  `renewal_window_exceeded`；已过期返回 `lease_expired`；
  已撤销返回 `lease_revoked`——三种失败原因可区分。
- **撤销**：幂等；撤销后使用返回 `lease_revoked`，与过期
  `lease_expired` 可区分。
- **使用**：校验存在性、撤销、过期、能力，全部通过才返回凭据内容。

## 轮换语义

- 轮换给机密追加一个新版本，版本号以机密自身为准单调递增。
- **规则（与并发顺序无关）**：轮换前已发放的旧版本租约在过期/撤销前
  仍然有效，读到的始终是发放时的旧值；轮换后新发放的租约绑定最新版本。
- 所有状态变更都在 `Store` 的同一把可重入锁内完成：并发发放产生互不
  重复的租约，并发轮换产生连续不重复的版本号，续租永远不会把
  `expires_at` 推过 `max_expires_at`，不存在半截状态。

## 验证

```bash
uv add --dev pytest   # 首次
uv run pytest tests/ -q          # 跑全部测试
uv run pytest tests/ -q -s       # 查看每个用例打印的请求输入与判定依据
```

- `tests/test_policy.py`：四种拒绝原因的区分 + 存在性不泄露。
- `tests/test_lease.py`：续租边界（窗口钳制、顶窗拒续）、过期、撤销、
  续租不改变凭据内容。
- `tests/test_concurrency.py`：并发发放唯一性、并发轮换版本连续、
  发放与轮换并发时“凭据内容 == 其绑定版本的值”、并发续租不超窗、
  撤销与使用并发结果一致。

HTTP 服务：`uv run python main.py`，接口见 `main.py`
（`POST /leases`、`POST /leases/{id}/renew`、`POST /leases/{id}/revoke`、
`GET /leases/{id}/secret`、`POST /rotate`）。
