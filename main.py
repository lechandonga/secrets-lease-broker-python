"""本地短时凭据租赁服务的 HTTP 入口。"""
import time

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from broker.lease_manager import LeaseManager
from broker.models import Capability
from broker.store import Store

app = FastAPI(title="secrets-lease-broker")
manager = LeaseManager(Store.seeded(), ttl=60.0, max_ttl=300.0)


class IssueRequest(BaseModel):
    principal_id: str
    path: str
    capability: Capability = Capability.READ


class RotateRequest(BaseModel):
    principal_id: str
    path: str
    new_value: str


def _deny_payload(decision):
    return {"allowed": False, "reason": decision.reason, "detail": decision.detail}


def _lease_payload(lease):
    return {
        "allowed": True,
        "lease_id": lease.id,
        "secret_path": lease.secret_path,
        "secret_version": lease.secret_version,
        "expires_at": lease.expires_at,
        "max_expires_at": lease.max_expires_at,
    }


@app.post("/leases")
def issue(req: IssueRequest):
    decision, lease = manager.issue(req.principal_id, req.path, req.capability, time.time())
    return _lease_payload(lease) if decision.allowed else _deny_payload(decision)


@app.post("/leases/{lease_id}/renew")
def renew(lease_id: str):
    decision, lease = manager.renew(lease_id, time.time())
    return _lease_payload(lease) if decision.allowed else _deny_payload(decision)


@app.post("/leases/{lease_id}/revoke")
def revoke(lease_id: str):
    decision = manager.revoke(lease_id, time.time())
    return {"allowed": True} if decision.allowed else _deny_payload(decision)


@app.get("/leases/{lease_id}/secret")
def use(lease_id: str):
    decision, value = manager.use(lease_id, time.time())
    return {"allowed": True, "value": value} if decision.allowed else _deny_payload(decision)


@app.post("/secrets/rotate")
def rotate(req: RotateRequest):
    decision, version = manager.rotate(req.principal_id, req.path, req.new_value, time.time())
    return {"allowed": True, "version": version} if decision.allowed else _deny_payload(decision)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
