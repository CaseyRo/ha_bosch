#!/usr/bin/env python3
"""Standalone POINTTAPI OAuth debug script.

Walks through the full login flow and tests the resulting token against
the Bosch API. No Home Assistant dependency.

Run with:
  uv run --with aiohttp python test_pointtapi_oauth.py
"""
import asyncio
import base64
import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

import aiohttp

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# Quieten noisy libs
for noisy in ("aiohttp", "asyncio", "charset_normalizer"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("pointtapi_debug")

# ── OAuth constants (must match pointtapi_oauth.py exactly) ──────────────────
TOKEN_URL = "https://singlekey-id.com/auth/connect/token"
CLIENT_ID = "762162C0-FA2D-4540-AE66-6489F189FADC"
REDIRECT_URI = "com.bosch.tt.dashtt.pointt://app/login"
CODE_VERIFIER = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklm"
SCOPES = [
    "openid", "email", "profile", "offline_access",
    "pointt.gateway.claiming", "pointt.gateway.removal",
    "pointt.gateway.list", "pointt.gateway.users",
    "pointt.gateway.resource.dashapp",
    "pointt.castt.flow.token-exchange", "bacon",
]

# ── Device ────────────────────────────────────────────────────────────────────
DEVICE_ID = input("Enter device serial (no dashes, e.g. 101506113): ").strip()

POINTTAPI_BASE = (
    f"https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/"
    f"{DEVICE_ID}/resource/"
)


def build_auth_url() -> str:
    code_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(CODE_VERIFIER.encode()).digest()
        )
        .decode()
        .rstrip("=")
    )
    params = {
        "redirect_uri": urllib.parse.quote_plus(REDIRECT_URI),
        "client_id": CLIENT_ID,
        "response_type": "code",
        "prompt": "login",
        "state": "_yUmSV3AjUTXfn6DSZQZ-g",
        "nonce": "5iiIvx5_9goDrYwxxUEorQ",
        "scope": urllib.parse.quote(" ".join(SCOPES)),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "style_id": "tt_bsch",
        "suppressed_prompt": "login",
    }
    query = unquote(urlencode(params))
    encoded_query = urllib.parse.quote(query)
    return_url = urllib.parse.quote_plus("/auth/connect/authorize/callback?")
    return f"https://singlekey-id.com/auth/en-us/login?ReturnUrl={return_url}{encoded_query}"


async def exchange_code(session: aiohttp.ClientSession, code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": CODE_VERIFIER,
    }
    log.debug("POST %s  body=%s", TOKEN_URL, {k: v for k, v in data.items() if k != "code"})
    async with session.post(TOKEN_URL, data=data) as resp:
        body = await resp.text()
        log.debug("Token exchange response: status=%s body=%s", resp.status, body[:500])
        if resp.status != 200:
            print(f"\n[FAIL] Token exchange returned HTTP {resp.status}")
            print(f"       Body: {body[:500]}")
            return {}
        return await resp.json(content_type=None)


async def test_api(session: aiohttp.ClientSession, access_token: str, path: str) -> None:
    url = POINTTAPI_BASE + path.lstrip("/")
    headers = {"Authorization": f"Bearer {access_token}"}
    log.debug("GET %s", url)
    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        body = await resp.text()
        status_str = f"HTTP {resp.status}"
        if resp.status == 200:
            print(f"  [OK]   {path}  →  {status_str}  |  {body[:200]}")
        else:
            print(f"  [FAIL] {path}  →  {status_str}  |  {body[:200]}")


async def main() -> None:
    # Step 1: show login URL
    auth_url = build_auth_url()
    print("\n" + "=" * 70)
    print("STEP 1 — Open this URL in a browser and log in with your Bosch account:")
    print("=" * 70)
    print(auth_url)
    print()
    print("After logging in your browser will show 'Cannot open page' — that is expected.")
    print("Copy the FULL URL from the address bar of that tab.")
    print()

    # Step 2: get callback URL from user
    callback_url = input("Paste callback URL here: ").strip()
    parsed = urllib.parse.urlparse(callback_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = (params.get("code") or [None])[0]
    if not code:
        print(f"\n[FAIL] No 'code=' parameter found in: {callback_url}")
        return
    print(f"\n[OK] Extracted code: {code[:20]}...")

    async with aiohttp.ClientSession() as session:
        # Step 3: exchange code for tokens
        print("\nSTEP 3 — Exchanging code for tokens...")
        tokens = await exchange_code(session, code)
        if not tokens:
            return

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 0)
        print(f"[OK] access_token: {access_token[:30]}...")
        print(f"[OK] refresh_token present: {bool(refresh_token)}")
        print(f"[OK] expires_in: {expires_in}s")

        # Step 4: test the access token against the API
        print(f"\nSTEP 4 — Testing token against POINTTAPI for device {DEVICE_ID}...")
        for path in ["/gateway", "/gateway/DateTime", "/heatingCircuits/hc1", "/system/sensors"]:
            await test_api(session, access_token, path)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
