# secrets-lease-broker

本地短时凭据租赁服务：用进程内数据模拟主体、角色、策略与机密内容，
按策略鉴权后发放带有效期的租赁（lease），支持续租、撤销与轮换。

## 策略模型

- **主体（Principal）**：`id` + 一组角色。种子数据：`alice`(db-reader)、
  `bob`(db-admin)、`carol`(kv-reader)、`dave`（已注册但无角色）。
- **策略（Policy）**：`(role, path_prefix, capabilities)`，表示某角色可对
  某路径前缀行使某些能力（`read` / `write`）。
- **判定顺序**（`broker/policy.py`，每种拒绝原因可区分）：

  | 顺序 | 条件 | 拒绝原因 |
  |---|---|---|
  | 1 | 主体未注册 | `unknown_principal` |
  | 2 | 主体无任何角色策略 | `no_matching_policy` |
  | 3 | 策略不覆盖该路径前缀 | `path_not_allowed` |
  | 4 | 路径覆盖但能力不含 | `capability_not_granted` |

- **不泄露机密存在性**：策略允许但路径下实际没有机密时，发放请求以与
  `path_not_allowed` 完全相同的原因与文案拒绝，调用方无法反推机密是否存在。

## 租赁语义

- **发放（issue）**：鉴权通过后生成租赁，`expires_at = now + ttl`，
  并记录 `max_expires_at = now + max_ttl` 与当前机密版本。
- **续租（renew）**：`expires_at = min(now + ttl, max_expires_at)`；
  已到上限再续租拒绝 `max_ttl_exceeded`；过期/已撤销/不存在的租赁分别拒绝
  `lease_expired` / `lease_revoked` / `lease_not_found`。
  续租只延长有效期，**不改变**租赁指向的机密内容与版本。
- **使用（use）**：凭租赁读取其绑定版本的机密内容；过期、撤销、不存在
  三种失败原因可区分。

## 轮换语义与并发规则

- **轮换（rotate）**：需要对该路径的 `write` 能力。机密版本 +1 并写入新值，
  同时撤销该路径上**所有现存旧版本租赁**；此后新租赁只指向当前版本。
- **并发一致性**：所有操作（发放/续租/撤销/使用/轮换）都在同一把可重入锁内
  完成"检查 + 修改"，按锁获取顺序串行化，无半截状态；N 次并发轮换后版本
  恰好为 `1 + N`，无重复、无丢失。
- **与顺序无关的不变量**：任意并发交错结束后，`secret_version < 当前版本`
  的租赁必然已撤销（使用/续租一律 `lease_revoked`）；指向当前版本的租赁
  保持可用。续租与轮换并发时，续租要么在轮换前成功，要么以
  `lease_revoked` 失败，不存在第三种结果。

## HTTP 接口

```
POST /leases                  {principal_id, path, capability}  发放
POST /leases/{id}/renew                                           续租
POST /leases/{id}/revoke                                          撤销
GET  /leases/{id}/secret                                          凭租赁读取
POST /secrets/rotate          {principal_id, path, new_value}     轮换
```

运行：`uv run python main.py`（默认 ttl=60s，max_ttl=300s）。

## 如何验证

```bash
python3 -m pytest tests/ -q --log-cli-level=INFO
```

- `tests/test_policy.py`：四种拒绝原因的区分、机密存在性不泄露。
- `tests/test_lease.py`：续租延长/上限截断/超限拒绝、续租不改内容、
  过期与撤销后的使用与续租拒绝。
- `tests/test_concurrency.py`：并发发放唯一性、并发轮换版本恰好 +N、
  发放与轮换交错下的撤销不变量、续租与轮换并发的二值结果。

测试日志会打印每个请求的输入（主体/路径/能力/时间点）与判定依据
（允许与否、拒绝原因、有效期变化）。
