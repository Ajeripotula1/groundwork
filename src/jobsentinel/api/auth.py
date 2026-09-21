"""
FastAPI auth dependency: verifies a Clerk-issued session token and returns
the authenticated user's Clerk ID.

How this fits the architecture: Clerk is the user directory - JobSentinel
keeps no local `users` table (per CLAUDE.md's stack table: "Auth | Clerk |
Drop-in React + ~15 lines JWKS verify"). Anywhere a request needs to know
"which user is this," it depends on get_current_user_id below and gets back
the Clerk `sub` claim (a stable string like "user_2abc...") - that string is
what jobsentinel.db.profile scopes rows by, and what the Job Agent uses as
its AgentCore Memory actor_id (see jobsentinel.agent.shared.memory).

The flow, end to end: the frontend (Slice 7 - not built yet) drops in
Clerk's React SDK; a user signs in there, and Clerk hands the frontend a
short-lived signed JWT (a "session token") it attaches to every API call as
`Authorization: Bearer <token>`. This module never calls Clerk's servers to
check that token - it verifies the signature locally against Clerk's
*public* signing key, which is the actual point of JWTs: anyone holding the
public key can confirm a token was minted by the holder of the matching
private key (Clerk), with no network round-trip per request.

Where the public key comes from: a JWT's header names which key signed it
(`kid`, "key ID"). Clerk publishes all of its current public keys, indexed
by `kid`, at a fixed per-application URL (a JWKS - "JSON Web Key Set"):
`{issuer}/.well-known/jwks.json`. PyJWT's PyJWKClient fetches that URL,
caches the result, and picks out the right key for a given token
automatically - this is the whole "~15 lines" from CLAUDE.md, not a
hand-rolled key-fetching/caching layer.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jobsentinel.config import get_settings

_bearer_scheme = HTTPBearer(
    description="Clerk session token - the frontend's `getToken()` result."
)

# Built lazily, not at import time: constructing it doesn't hit the network
# yet (PyJWKClient fetches lazily too, on first verification), but reading
# settings.clerk_issuer here at import time would make every process that
# imports this module (including ones that never serve an authenticated
# request) require CLERK_ISSUER to be set - see Settings.clerk_issuer's
# docstring for why that's deliberately not a required field.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        if not settings.clerk_issuer:
            raise RuntimeError(
                "CLERK_ISSUER is not set - see .env.example for where to find "
                "it (Clerk dashboard -> your app -> Configure -> API Keys)."
            )
        # cache_keys=True: PyJWKClient caches the fetched JWKS in-process, so
        # a verification only refetches Clerk's public keys when a token
        # names a `kid` this process hasn't cached yet (e.g. after Clerk
        # rotates its signing key), not on every single request.
        _jwks_client = jwt.PyJWKClient(
            f"{settings.clerk_issuer}/.well-known/jwks.json", cache_keys=True
        )
    return _jwks_client


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: verify the request's bearer token and return the
    authenticated user's Clerk ID (the JWT `sub` claim).

    Add `current_user_id: str = Depends(get_current_user_id)` to any route
    that should require sign-in - FastAPI resolves this before the route
    body runs, so a missing/malformed/expired/wrongly-signed token
    short-circuits with a 401 before any of the route's own code executes.

    Two claims are checked explicitly:
      - `iss` (issuer): proves this token was minted by *your* Clerk
        application, not a different Clerk instance's user presenting a
        validly-signed-but-foreign token.
      - `exp` (expiry): checked automatically by jwt.decode; PyJWTError
        below covers an expired token the same as any other invalid one.
    `aud` (audience) is deliberately NOT checked - Clerk only sets one if
    you've configured a JWT template with an explicit audience, which this
    project doesn't use.

    Raises:
        HTTPException: 401, for any missing/invalid/expired/mis-signed
        token. RuntimeError (uncaught, surfaces as a 500): CLERK_ISSUER
        isn't configured at all - a server misconfiguration, not a client
        auth failure, so it deliberately isn't folded into the 401 case.
    """
    settings = get_settings()
    token = credentials.credentials
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=f"invalid or expired token: {exc}"
        ) from exc

    return claims["sub"]
