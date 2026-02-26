"""Tests for admin JWT authentication (RS256 via JWKS)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import pytest
from fastapi import HTTPException

from app.services.spark.admin_auth import verify_admin_jwt

# ---------------------------------------------------------------------------
# Test RSA key pair (generated once for the test module)
# ---------------------------------------------------------------------------

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()

_CLIENT_ROW = {
    "id": str(uuid4()),
    "name": "Test Co",
    "slug": "test-co",
    "api_key_hash": "abc",
    "settling_config": {},
    "max_turns": 20,
    "rate_limit_rpm": 30,
    "active": True,
}


def _make_token(
    sub: str = "user-123",
    exp: int | None = None,
    aud: str = "authenticated",
    headers: dict[str, str] | None = None,
) -> str:
    """Create a test JWT signed with our test RSA private key."""
    payload: dict[str, Any] = {"sub": sub, "aud": aud}
    if exp is not None:
        payload["exp"] = exp
    else:
        payload["exp"] = int(time.time()) + 3600
    return jwt.encode(
        payload,
        _private_key,
        algorithm="RS256",
        headers=headers or {"kid": "test-key-id"},
    )


def _mock_request(token: str | None = None) -> MagicMock:
    """Create a mock request with optional Authorization header."""
    request = MagicMock()
    if token:
        request.headers = {"Authorization": f"Bearer {token}"}
    else:
        request.headers = {}
    return request


def _mock_jwks_client() -> MagicMock:
    """Mock PyJWKClient that returns our test public key."""
    mock_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = _public_key
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    return mock_client


def _patch_db(row: dict[str, Any] | None = None):
    """Patch helpers that return (jwks_patch, sb_patch, db_patch)."""
    mock_sb = MagicMock()
    return (
        patch(
            "app.services.spark.admin_auth._get_jwks_client",
            return_value=_mock_jwks_client(),
        ),
        patch(
            "app.services.spark.admin_auth.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ),
        patch(
            "app.services.spark.admin_auth.get_first_or_none",
            new_callable=AsyncMock,
            return_value=row,
        ),
    )


# ── Missing / malformed token ──────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_auth_header() -> None:
    request = _mock_request(token=None)
    with pytest.raises(HTTPException) as exc_info:
        await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401
    assert "Missing" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_non_bearer_header() -> None:
    request = MagicMock()
    request.headers = {"Authorization": "Basic abc123"}
    with pytest.raises(HTTPException) as exc_info:
        await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401


# ── Invalid tokens ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_token() -> None:
    token = _make_token(exp=int(time.time()) - 3600)
    request = _mock_request(token)

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=_mock_jwks_client(),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401
    assert "expired" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_wrong_signing_key() -> None:
    """Token signed with a different key than what JWKS returns."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(
        payload, other_key, algorithm="RS256", headers={"kid": "other-key"}
    )
    request = _mock_request(token)

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=_mock_jwks_client(),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience() -> None:
    token = _make_token(aud="anon")
    request = _mock_request(token)

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=_mock_jwks_client(),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_token_without_sub() -> None:
    payload = {"aud": "authenticated", "exp": int(time.time()) + 3600}
    token = jwt.encode(
        payload, _private_key, algorithm="RS256", headers={"kid": "test-key-id"}
    )
    request = _mock_request(token)

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=_mock_jwks_client(),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401
    assert "subject" in str(exc_info.value.detail).lower()


# ── No matching client ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_matching_client() -> None:
    token = _make_token(sub="no-client-user")
    request = _mock_request(token)
    p1, p2, p3 = _patch_db(row=None)

    with p1, p2, p3:
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 403
    assert "No Spark client" in str(exc_info.value.detail)


# ── Inactive client ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_client() -> None:
    token = _make_token(sub="user-123")
    request = _mock_request(token)
    inactive_row = {**_CLIENT_ROW, "active": False}
    p1, p2, p3 = _patch_db(row=inactive_row)

    with p1, p2, p3:
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 403
    assert "deactivated" in str(exc_info.value.detail).lower()


# ── Happy path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_returns_client() -> None:
    token = _make_token(sub="user-123")
    request = _mock_request(token)
    p1, p2, p3 = _patch_db(row=_CLIENT_ROW)

    with p1, p2, p3:
        client = await verify_admin_jwt(request)

    assert str(client.id) == _CLIENT_ROW["id"]
    assert client.name == "Test Co"
    assert client.active is True


# ── Database error ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_database_error() -> None:
    token = _make_token(sub="user-123")
    request = _mock_request(token)

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=_mock_jwks_client(),
    ), patch(
        "app.services.spark.admin_auth.get_supabase_client",
        new_callable=AsyncMock,
        side_effect=Exception("DB down"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 500


# ── JWKS endpoint failure ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_jwks_fetch_failure() -> None:
    token = _make_token(sub="user-123")
    request = _mock_request(token)

    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.side_effect = Exception("JWKS unreachable")

    with patch(
        "app.services.spark.admin_auth._get_jwks_client",
        return_value=mock_client,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_jwt(request)
    assert exc_info.value.status_code == 401
    assert "verification failed" in str(exc_info.value.detail).lower()
