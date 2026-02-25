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
import getpass
import hashlib
import json
import logging
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlencode

import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

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


async def capture_callback_url(email: str, password: str) -> str | None:
    """Launch browser, log in, intercept the OAuth callback URL."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    auth_url = build_auth_url()
    captured: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        context = await browser.new_context()
        page = await context.new_page()

        # ── Intercept 302 redirects to the custom scheme ─────────────────────
        # The OAuth server sends a 302 Location: com.bosch.tt.dashtt.pointt://...
        # We capture it from the response headers before the browser tries to navigate.
        def on_response(response):
            location = response.headers.get("location", "")
            if location.startswith("com.bosch.tt.dashtt.pointt://"):
                log.info("Captured redirect: %s", location[:80])
                captured.append(location)

        page.on("response", on_response)

        # Also catch it if it arrives as a navigation request
        def on_request(request):
            if request.url.startswith("com.bosch.tt.dashtt.pointt://"):
                log.info("Captured request navigation: %s", request.url[:80])
                captured.append(request.url)

        page.on("request", on_request)

        try:
            # Step 1: navigate to auth URL
            log.info("Navigating to Bosch login page...")
            await page.goto(auth_url, wait_until="domcontentloaded", timeout=20_000)
            await page.screenshot(path=str(SCREENSHOT_DIR / "01_login_page.png"))
            log.info("Screenshot: debug_screenshots/01_login_page.png")

            # Step 2: fill email
            log.info("Looking for email field...")
            email_selectors = [
                'input[name="Username"]',
                'input[type="email"]',
                'input[id="Username"]',
                'input[name="email"]',
                'input[placeholder*="mail" i]',
            ]
            email_field = None
            for sel in email_selectors:
                try:
                    email_field = page.locator(sel).first
                    await email_field.wait_for(state="visible", timeout=3_000)
                    log.info("  Found email field: %s", sel)
                    break
                except PlaywrightTimeout:
                    email_field = None

            if email_field is None:
                await page.screenshot(path=str(SCREENSHOT_DIR / "02_no_email_field.png"))
                log.error("Could not find email input. See debug_screenshots/02_no_email_field.png")
                # Print all input elements for diagnosis
                inputs = await page.locator("input").all()
                log.info("Inputs on page: %s", [await i.get_attribute("name") for i in inputs])
                await browser.close()
                return None

            await email_field.fill(email)

            # Step 3: fill password
            log.info("Looking for password field...")
            password_selectors = [
                'input[name="Password"]',
                'input[type="password"]',
                'input[id="Password"]',
            ]
            password_field = None
            for sel in password_selectors:
                try:
                    password_field = page.locator(sel).first
                    await password_field.wait_for(state="visible", timeout=3_000)
                    log.info("  Found password field: %s", sel)
                    break
                except PlaywrightTimeout:
                    password_field = None

            if password_field is None:
                await page.screenshot(path=str(SCREENSHOT_DIR / "03_no_password_field.png"))
                log.error("Could not find password input. See debug_screenshots/03_no_password_field.png")
                await browser.close()
                return None

            await password_field.fill(password)
            await page.screenshot(path=str(SCREENSHOT_DIR / "04_filled_credentials.png"))

            # Step 4: click submit and wait for the redirect
            log.info("Submitting login form...")
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Sign in")',
                'button:has-text("Log in")',
                'button:has-text("Login")',
                '.btn-primary',
            ]
            submit_btn = None
            for sel in submit_selectors:
                try:
                    submit_btn = page.locator(sel).first
                    await submit_btn.wait_for(state="visible", timeout=2_000)
                    log.info("  Found submit button: %s", sel)
                    break
                except PlaywrightTimeout:
                    submit_btn = None

            if submit_btn is None:
                await page.screenshot(path=str(SCREENSHOT_DIR / "05_no_submit.png"))
                log.error("Could not find submit button.")
                await browser.close()
                return None

            # Click submit; the OAuth callback redirect may cause a navigation error — that's fine
            try:
                async with page.expect_navigation(timeout=15_000):
                    await submit_btn.click()
            except PlaywrightTimeout:
                pass  # Timeout is expected if the redirect goes to a custom scheme
            except Exception as e:
                log.debug("Navigation exception (expected for custom scheme): %s", e)

            # Give a moment for any final redirects to fire
            await asyncio.sleep(2)
            await page.screenshot(path=str(SCREENSHOT_DIR / "06_after_submit.png"))
            log.info("Screenshot: debug_screenshots/06_after_submit.png")

        except Exception as e:
            log.error("Browser automation error: %s", e, exc_info=True)
            try:
                await page.screenshot(path=str(SCREENSHOT_DIR / "error.png"))
            except Exception:
                pass
        finally:
            await browser.close()

    if captured:
        return captured[0]

    log.warning("Callback URL not captured — check screenshots in debug_screenshots/")
    return None


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
    device_id = input("Device serial (no dashes, e.g. 101506113): ").strip()
    email = input("Bosch account email: ").strip()
    password = getpass.getpass("Bosch account password: ")

    # Step 1: browser login + intercept
    print()
    log.info("Launching browser to complete Bosch login...")
    callback_url = await capture_callback_url(email, password)

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
