"""测试公共夹具：让每个用例都打印请求输入与判定依据。"""
from __future__ import annotations

import logging

import pytest

from broker.broker import Broker
from broker.seed import build_store


class FakeClock:
    """可手动推进的时钟，便于构造过期/续租边界。"""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def broker(clock: FakeClock) -> Broker:
    return Broker(build_store(), clock=clock)


@pytest.fixture(autouse=True)
def _log_requests() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
    )
