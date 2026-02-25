#!/usr/bin/env python3
"""POINTTAPI OAuth debug script — fully automated via Playwright.

Logs in to Bosch SingleKey ID, intercepts the OAuth callback URL, exchanges
the code for tokens, and tests them against the API.

First-time setup:
  uv run --with playwright python -m playwright install chromium

Run:
  uv run --with playwright --with aiohttp python test_pointtapi_playwright.py
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import urllib.parse
from pathlib import Path
from urllib.parse import unquote, urlencode

import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
)
log = logging.getLogger("pointtapi")

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
POINTTAPI_BASE = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/{device_id}/resource"

SCREENSHOT_DIR = Path(__file__).parent / "debug_screenshots"


def build_auth_url() -> str:
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(CODE_VERIFIER.encode()).digest())
        .decode().rstrip("=")
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


async def capture_callback_url() -> str | None:
    """Open browser on the Bosch login page; wait for the user to log in and
    the OAuth callback redirect to fire, then return the callback URL."""
    auth_url = build_auth_url()
    captured: list[str] = []
    done = asyncio.Event()

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Intercept the custom-scheme redirect in response headers
        def on_response(response):
            location = response.headers.get("location", "")
            if location.startswith("com.bosch.tt.dashtt.pointt://"):
                log.info("Captured redirect: %s", location[:80])
                captured.append(location)
                done.set()

        # Also catch it if the browser tries to navigate to the custom scheme
        def on_request(request):
            if request.url.startswith("com.bosch.tt.dashtt.pointt://"):
                log.info("Captured navigation: %s", request.url[:80])
                captured.append(request.url)
                done.set()

        page.on("response", on_response)
        page.on("request", on_request)

        log.info("Navigating to Bosch login page...")
        await page.goto(auth_url, wait_until="domcontentloaded", timeout=20_000)

        print()
        print("  Browser is open — please log in with your Bosch account.")
        print("  The script will continue automatically once you're logged in.")
        print()

        # Wait up to 3 minutes for the user to log in
        try:
            await asyncio.wait_for(done.wait(), timeout=180)
        except asyncio.TimeoutError:
            log.error("Timed out waiting for login (3 min). Closing browser.")
        finally:
            await browser.close()

    return captured[0] if captured else None


async def exchange_code(session: aiohttp.ClientSession, code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": CODE_VERIFIER,
    }
    log.info("Exchanging code for tokens...")
    async with session.post(TOKEN_URL, data=data) as resp:
        body = await resp.text()
        log.info("Token exchange: HTTP %s", resp.status)
        if resp.status != 200:
            log.error("Token exchange failed. Body: %s", body[:500])
            return {}
        tokens = json.loads(body)
        return tokens


async def test_api_paths(session: aiohttp.ClientSession, access_token: str, device_id: str) -> None:
    base = POINTTAPI_BASE.format(device_id=device_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    paths = [
        "/gateway",
        "/gateway/DateTime",
        "/heatingCircuits/hc1",
        "/system/sensors",
        "/system/appliance",
    ]
    print()
    print("API test results:")
    print("-" * 60)
    for path in paths:
        url = base + path
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.text()
                status = f"HTTP {resp.status}"
                preview = body[:120].replace("\n", " ")
                marker = "[OK]  " if resp.status == 200 else "[FAIL]"
                print(f"  {marker} {path:<40} {status}  {preview}")
        except Exception as e:
            print(f"  [ERR]  {path:<40} {e}")
    print("-" * 60)


async def main() -> None:
    print()
    device_id = os.environ.get("BOSCH_DEVICE_ID") or input("Device serial (no dashes, e.g. 101506113): ").strip()

    # Step 1: browser login + intercept
    log.info("Launching browser...")
    callback_url = await capture_callback_url()

    if not callback_url:
        print("\n[FAIL] Could not capture the callback URL automatically.")
        print("       Check the screenshots in debug_screenshots/ to see where it stopped.")
        print("       You can run test_pointtapi_oauth.py to do it manually instead.")
        sys.exit(1)

    print(f"\n[OK] Callback URL: {callback_url[:80]}...")

    # Step 2: extract code
    parsed = urllib.parse.urlparse(callback_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = (params.get("code") or [None])[0]
    if not code:
        log.error("No 'code=' parameter in callback URL: %s", callback_url)
        sys.exit(1)
    log.info("Extracted code: %s...", code[:20])

    async with aiohttp.ClientSession() as session:
        # Step 3: exchange code for tokens
        tokens = await exchange_code(session, code)
        if not tokens:
            sys.exit(1)

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 0)
        token_type = tokens.get("token_type", "")

        print(f"\n[OK] access_token:    {access_token[:40]}...")
        print(f"[OK] token_type:      {token_type}")
        print(f"[OK] expires_in:      {expires_in}s")
        print(f"[OK] refresh_token:   {'present' if refresh_token else 'MISSING'}")

        # Step 4: test API
        log.info("Testing access token against POINTTAPI for device %s...", device_id)
        await test_api_paths(session, access_token, device_id)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
