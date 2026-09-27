"""本地短时凭据租赁服务的 HTTP 入口。

底层语义见 broker 包与 README；这里只做薄薄的 HTTP 适配。
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from broker.broker import Broker
from broker.models import Capability
from broker.seed import build_store

app = FastAPI(title="secrets-lease-broker")
broker = Broker(build_store())


class IssueRequest(BaseModel):
    principal: str
    path: str
    capabilities: list[str]
    ttl: float = 60.0
    max_ttl: float = 300.0


class RenewRequest(BaseModel):
    extend_by: float


class RotateRequest(BaseModel):
    path: str
    new_value: str


@app.post("/leases")
def issue(req: IssueRequest):
    caps = frozenset(Capability(c) for c in req.capabilities)
    r = broker.issue(req.principal, req.path, caps, ttl=req.ttl, max_ttl=req.max_ttl)
    if not r.ok:
        return {"ok": False, "reason": r.reason.value}
    return {"ok": True, "lease_id": r.lease_id,
            "expires_at": r.expires_at, "max_expires_at": r.max_expires_at}


@app.post("/leases/{lease_id}/renew")
def renew(lease_id: str, req: RenewRequest):
    r = broker.renew(lease_id, req.extend_by)
    if not r.ok:
        return {"ok": False, "reason": r.reason.value}
    return {"ok": True, "expires_at": r.lease.expires_at,
            "max_expires_at": r.lease.max_expires_at}


@app.post("/leases/{lease_id}/revoke")
def revoke(lease_id: str):
    r = broker.revoke(lease_id)
    return {"ok": r.ok, "reason": r.reason.value if r.reason else None}


@app.get("/leases/{lease_id}/secret")
def use(lease_id: str, capability: str = "read"):
    u = broker.use(lease_id, Capability(capability))
    if not u.ok:
        return {"ok": False, "reason": u.reason.value}
    return {"ok": True, "value": u.value, "version": u.version}


@app.post("/rotate")
def rotate(req: RotateRequest):
    version = broker.rotate(req.path, req.new_value)
    if version is None:
        return {"ok": False, "reason": "path_not_allowed"}
    return {"ok": True, "version": version}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
