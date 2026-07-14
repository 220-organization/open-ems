"""Ubetter multi-tenant account config (cabinettest + dedicated 220km)."""

from app.ubetter_api import configured_ubetter_accounts, ubetter_configured, ubetter_missing_env_names


def test_configured_accounts_include_220km_when_password_set(monkeypatch):
    monkeypatch.setattr("app.settings.UBETTER_ENABLED", True)
    monkeypatch.setattr("app.settings.UBETTER_PASSWORD", "")
    monkeypatch.setattr("app.settings.UBETTER_220KM_PASSWORD", "secret-220km")
    monkeypatch.setattr("app.settings.UBETTER_USERNAME", "cabinettest")
    monkeypatch.setattr("app.settings.UBETTER_TENANT_USERNAME", "cabinettest")
    monkeypatch.setattr("app.settings.UBETTER_220KM_USERNAME", "220km")
    monkeypatch.setattr("app.settings.UBETTER_220KM_TENANT_USERNAME", "220km")
    monkeypatch.setattr("app.settings.UBETTER_BASE_URL", "https://eur.ubetter.com.cn/ems-open-api")

    accounts = configured_ubetter_accounts()
    assert ubetter_configured() is True
    assert [a.key for a in accounts] == ["220km"]
    assert accounts[0].username == "220km"
    assert accounts[0].password == "secret-220km"
    assert ubetter_missing_env_names() == []


def test_configured_accounts_parallel_when_both_passwords_set(monkeypatch):
    monkeypatch.setattr("app.settings.UBETTER_ENABLED", True)
    monkeypatch.setattr("app.settings.UBETTER_PASSWORD", "secret-lab")
    monkeypatch.setattr("app.settings.UBETTER_220KM_PASSWORD", "secret-220km")
    monkeypatch.setattr("app.settings.UBETTER_USERNAME", "cabinettest")
    monkeypatch.setattr("app.settings.UBETTER_TENANT_USERNAME", "cabinettest")
    monkeypatch.setattr("app.settings.UBETTER_220KM_USERNAME", "220km")
    monkeypatch.setattr("app.settings.UBETTER_220KM_TENANT_USERNAME", "220km")
    monkeypatch.setattr("app.settings.UBETTER_BASE_URL", "https://eur.ubetter.com.cn/ems-open-api")

    accounts = configured_ubetter_accounts()
    assert [a.key for a in accounts] == ["default", "220km"]
    assert accounts[0].username == "cabinettest"
    assert accounts[1].username == "220km"


def test_not_configured_when_no_passwords(monkeypatch):
    monkeypatch.setattr("app.settings.UBETTER_ENABLED", True)
    monkeypatch.setattr("app.settings.UBETTER_PASSWORD", "")
    monkeypatch.setattr("app.settings.UBETTER_220KM_PASSWORD", "")
    assert ubetter_configured() is False
    missing = ubetter_missing_env_names()
    assert "UBETTER_PASSWORD or UBETTER_220KM_PASSWORD" in missing
