"""
Unit tests for jobsentinel.api.auth's JWT verification (the minimal Clerk
pass, BUILD_PLAN.md). Uses a locally-generated RSA keypair standing in for
Clerk's real signing key, rather than hitting Clerk's actual JWKS endpoint -
same "mock the external boundary" pattern as every other test file here
(tests/test_profile_endpoint.py mocks Bedrock/DB, this mocks Clerk).

Every test calls get_current_user_id directly (it's a plain function once
you strip the Depends() wrapper) rather than going through a FastAPI
TestClient/app - this is testing the verification logic itself, not a
router's wiring, so there's no route needed at all.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from jobsentinel.api import auth as auth_module

TEST_ISSUER = "https://test.clerk.accounts.dev"


class _FakeSigningKey:
    """Stands in for jwt.PyJWKClient.get_signing_key_from_jwt's real return
    value (a jwt.PyJWK) - both just need a `.key` attribute holding the key
    material get_current_user_id verifies the token against."""

    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """Stands in for jwt.PyJWKClient without it ever making a network call -
    always hands back the one test public key, regardless of the token's
    `kid`."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._public_key)


@pytest.fixture
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def configure_clerk_issuer(monkeypatch):
    """get_current_user_id reads settings.clerk_issuer to check the token's
    `iss` claim - point it at TEST_ISSUER for every test in this file."""
    settings = auth_module.get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)


def _make_token(private_key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": TEST_ISSUER,
        "sub": "user_test123",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_token_returns_sub_claim(monkeypatch, keypair):
    private_key, public_key = keypair
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda: _FakeJWKSClient(public_key))

    user_id = auth_module.get_current_user_id(_credentials(_make_token(private_key)))

    assert user_id == "user_test123"


def test_expired_token_is_rejected(monkeypatch, keypair):
    private_key, public_key = keypair
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda: _FakeJWKSClient(public_key))
    token = _make_token(
        private_key,
        iat=datetime.now(timezone.utc) - timedelta(hours=1),
        exp=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_module.get_current_user_id(_credentials(token))
    assert exc_info.value.status_code == 401


def test_wrong_issuer_is_rejected(monkeypatch, keypair):
    """A token minted by a *different* Clerk application (a different
    `iss`), even if it happened to be signed by a key that verifies here,
    must not be accepted - this is the check that stops another Clerk
    instance's user from being treated as one of ours."""
    private_key, public_key = keypair
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda: _FakeJWKSClient(public_key))
    token = _make_token(private_key, iss="https://someone-elses-app.clerk.accounts.dev")

    with pytest.raises(HTTPException) as exc_info:
        auth_module.get_current_user_id(_credentials(token))
    assert exc_info.value.status_code == 401


def test_token_signed_by_different_key_is_rejected(monkeypatch, keypair):
    """A forged/tampered token - signed with a private key that doesn't
    match the public key we're checking against - must fail signature
    verification. This is the actual "can't be forged" property a JWT is
    for; every other check here is secondary to this one."""
    _unused_private_key, public_key = keypair
    forging_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth_module, "_get_jwks_client", lambda: _FakeJWKSClient(public_key))

    forged_token = _make_token(forging_key)

    with pytest.raises(HTTPException) as exc_info:
        auth_module.get_current_user_id(_credentials(forged_token))
    assert exc_info.value.status_code == 401


def test_missing_clerk_issuer_raises_runtime_error(monkeypatch, keypair):
    """CLERK_ISSUER unset is a server misconfiguration, not a client auth
    failure - see get_current_user_id's docstring for why this is a
    RuntimeError (surfaces as a 500), not folded into the 401 branch."""
    _private_key, public_key = keypair
    monkeypatch.setattr(auth_module.get_settings(), "clerk_issuer", "")
    monkeypatch.setattr(auth_module, "_jwks_client", None)

    with pytest.raises(RuntimeError, match="CLERK_ISSUER"):
        auth_module._get_jwks_client()
