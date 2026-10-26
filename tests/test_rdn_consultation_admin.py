"""Local admin-tab auth stays closed unless the process is a local run."""

from __future__ import annotations

from app.admin_auth import consultation_admin_open


def test_consultation_admin_closed_by_default(monkeypatch):
    monkeypatch.delenv("RDN_CONSULTATION_ADMIN_OPEN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://openems:openems@db:5432/openems")
    monkeypatch.setenv("OPEN_EMS_SERVE_SPA", "0")
    monkeypatch.setenv("RDN_CONSULTATION_ALLOW_TEST_PAYMENT", "1")
    assert consultation_admin_open() is False


def test_consultation_admin_open_for_local_database(monkeypatch):
    monkeypatch.delenv("RDN_CONSULTATION_ADMIN_OPEN", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems",
    )
    assert consultation_admin_open() is True


def test_consultation_admin_flag_overrides_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://openems:openems@db:5432/openems")
    monkeypatch.setenv("RDN_CONSULTATION_ADMIN_OPEN", "1")
    assert consultation_admin_open() is True
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems",
    )
    monkeypatch.setenv("RDN_CONSULTATION_ADMIN_OPEN", "0")
    assert consultation_admin_open() is False
