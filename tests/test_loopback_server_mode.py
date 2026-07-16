"""`require_loopback` gate contract (issue #261).

The gate must stay strict on the desktop build (non-loopback → 403, which is the
PR #81 trust boundary), but become a no-op in the headless Docker server mode,
where Docker's NAT makes the loopback origin unenforceable and exposure is
governed by the port mapping + the share PIN instead.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.dependencies import is_loopback, is_local_host, require_local, require_loopback


def _req(host):
    """Minimal stand-in for a Starlette Request — the gate only reads client.host."""
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None)


@pytest.fixture(autouse=True)
def _clear_loopback_env(monkeypatch):
    # Start each test from the strict desktop default regardless of ambient env.
    monkeypatch.delenv("OMNIVOICE_SERVER_MODE", raising=False)
    monkeypatch.delenv("OMNIVOICE_TRUSTED_NETWORKS", raising=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_always_allowed(host):
    require_loopback(_req(host))  # must not raise


def test_non_loopback_rejected_by_default():
    with pytest.raises(HTTPException) as exc:
        require_loopback(_req("172.17.0.1"))  # Docker bridge gateway
    assert exc.value.status_code == 403
    assert "loopback" in str(exc.value.detail).lower()


def test_missing_client_rejected_by_default():
    with pytest.raises(HTTPException):
        require_loopback(_req(None))


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_server_mode_allows_non_loopback(monkeypatch, val):
    monkeypatch.setenv("OMNIVOICE_SERVER_MODE", val)
    require_loopback(_req("172.17.0.1"))  # must not raise
    require_loopback(_req("127.0.0.1"))   # loopback still fine


@pytest.mark.parametrize("val", ["0", "false", "no", "", "off"])
def test_falsey_server_mode_keeps_gate_strict(monkeypatch, val):
    monkeypatch.setenv("OMNIVOICE_SERVER_MODE", val)
    with pytest.raises(HTTPException):
        require_loopback(_req("10.0.0.5"))


# Trusted local networks (OMNIVOICE_TRUSTED_NETWORKS) — issue #1170.
# A self-hoster can name CIDRs treated as trusted by the CONSUMPTION gates
# (PIN/API-key/WS), so a LAN or reverse proxy is exempted. Admin gates
# (require_loopback) stay true-loopback-only — two-tier privilege model.


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_is_loopback_true_for_loopback_only(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", ["192.168.1.50", "10.0.0.1", "8.8.8.8"])
def test_is_loopback_false_for_non_loopback(monkeypatch, host):
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "192.168.1.0/24")
    assert is_loopback(host) is False  # trusted-network ≠ loopback


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_is_local_host_loopback_always(monkeypatch, host):
    monkeypatch.delenv("OMNIVOICE_TRUSTED_NETWORKS", raising=False)
    assert is_local_host(host) is True


def test_is_local_host_trusts_configured_cidr(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "192.168.1.0/24,10.0.0.0/8")
    assert is_local_host("192.168.1.50") is True
    assert is_local_host("10.5.5.5") is True


def test_is_local_host_rejects_outside_configured_cidr(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "192.168.1.0/24")
    assert is_local_host("8.8.8.8") is False
    assert is_local_host("192.168.2.1") is False  # adjacent subnet


@pytest.mark.parametrize("host", ["192.168.1.5", "example.com"])
def test_is_local_host_untrusted_without_config(monkeypatch, host):
    # No trust configured → no behavior change vs. the desktop default.
    monkeypatch.delenv("OMNIVOICE_TRUSTED_NETWORKS", raising=False)
    assert is_local_host(host) is False


def test_is_local_host_ignores_malformed_cidr(monkeypatch):
    # A garbage entry is skipped, not fatal — the gate must never wedge.
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "not-a-cidr,192.168.1.0/24")
    assert is_local_host("192.168.1.5") is True
    assert is_local_host("8.8.8.8") is False


def test_require_loopback_rejects_trusted_network(monkeypatch):
    # Admin gate stays true-loopback-only: a trusted CIDR exempts consumption
    # (PIN/API-key/WS) but NOT admin routes like /system/set-env (RCE-class).
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "172.16.0.0/12")
    with pytest.raises(HTTPException) as exc:
        require_loopback(_req("172.20.0.9"))
    assert exc.value.status_code == 403


def test_require_loopback_still_rejects_untrusted_non_loopback(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "172.16.0.0/12")
    with pytest.raises(HTTPException) as exc:
        require_loopback(_req("8.8.8.8"))
    assert exc.value.status_code == 403


def test_require_local_allows_trusted_network(monkeypatch):
    # Consumption-tier: a trusted-network client IS exempted (unlike require_loopback).
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "172.16.0.0/12")
    require_local(_req("172.20.0.9"))  # must not raise


def test_require_local_rejects_untrusted_non_loopback(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "172.16.0.0/12")
    with pytest.raises(HTTPException) as exc:
        require_local(_req("8.8.8.8"))
    assert exc.value.status_code == 403


def test_is_local_host_unwraps_ipv4_mapped_ipv6(monkeypatch):
    # Dual-stack proxies (Caddy, Node.js) pass ::ffff:192.168.1.5 — should
    # match an IPv4 CIDR after unwrapping the mapped address.
    monkeypatch.setenv("OMNIVOICE_TRUSTED_NETWORKS", "192.168.1.0/24")
    assert is_local_host("::ffff:192.168.1.5") is True
    assert is_local_host("::ffff:8.8.8.8") is False
