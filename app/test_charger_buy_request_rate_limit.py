import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import charger_buy_request as mod
from app.routers.charger_buy_request import router


@pytest.fixture(autouse=True)
def _reset_limits(monkeypatch):
    mod.reset_buy_request_rate_limits_for_tests()

    async def _ok_telegram(_msg: str) -> bool:
        return True

    monkeypatch.setattr(mod, "send_telegram_message", _ok_telegram)
    yield
    mod.reset_buy_request_rate_limits_for_tests()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _body(**extra):
    data = {
        "catalog": "commercial",
        "phone": "+380501112233",
        "title": "Partner request",
    }
    data.update(extra)
    return data


def test_allows_two_then_blocks_third():
    client = _client()
    for _ in range(2):
        res = client.post("/api/charger-buy-request", json=_body())
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True

    res = client.post("/api/charger-buy-request", json=_body())
    assert res.status_code == 429
    assert "2 per day" in res.json()["detail"]


def test_different_ips_independent():
    client = _client()
    assert (
        client.post(
            "/api/charger-buy-request",
            json=_body(),
            headers={"X-Forwarded-For": "1.1.1.1"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/charger-buy-request",
            json=_body(),
            headers={"X-Forwarded-For": "1.1.1.1"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/charger-buy-request",
            json=_body(),
            headers={"X-Forwarded-For": "1.1.1.1"},
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/charger-buy-request",
            json=_body(),
            headers={"X-Forwarded-For": "8.8.8.8"},
        ).status_code
        == 200
    )


def test_failed_notify_does_not_consume_quota(monkeypatch):
    async def _fail(_msg: str) -> bool:
        return False

    async def _ok(_msg: str) -> bool:
        return True

    monkeypatch.setattr(mod, "send_telegram_message", _fail)
    client = _client()
    assert client.post("/api/charger-buy-request", json=_body()).status_code == 502
    assert client.post("/api/charger-buy-request", json=_body()).status_code == 502

    monkeypatch.setattr(mod, "send_telegram_message", _ok)
    assert client.post("/api/charger-buy-request", json=_body()).status_code == 200
    assert client.post("/api/charger-buy-request", json=_body()).status_code == 200
    assert client.post("/api/charger-buy-request", json=_body()).status_code == 429
