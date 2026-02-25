"""Bosch POINTTAPI OAuth helpers: code exchange and token refresh.

Uses the same endpoints and constants as the deric POINTTAPI connector.
Tokens are stored in the config entry only; never logged or written to external files.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import ACCESS_TOKEN

_LOGGER = logging.getLogger(__name__)

TOKEN_URL = "https://singlekey-id.com/auth/connect/token"
CLIENT_ID = "762162C0-FA2D-4540-AE66-6489F189FADC"
REDIRECT_URI = "com.bosch.tt.dashtt.pointt://app/login"
CODE_VERIFIER = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklm"
SCOPES = [
    "openid",
    "email",
    "profile",
    "offline_access",
    "pointt.gateway.claiming",
    "pointt.gateway.removal",
    "pointt.gateway.list",
    "pointt.gateway.users",
    "pointt.gateway.resource.dashapp",
    "pointt.castt.flow.token-exchange",
    "bacon",
]


def build_auth_url() -> str:
    """Build the Bosch POINTTAPI OAuth authorization URL (login page).

    Same structure as deric connector build_auth_url. User opens this URL
    in a browser to log in; after redirect they copy the callback URL and paste it in HA.
    """
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(CODE_VERIFIER.encode("utf-8")).digest()
    ).decode("utf-8").rstrip("=")
    query_params = {
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
    query_params_encoded = unquote(urlencode(query_params))
    query = urllib.parse.quote(query_params_encoded)
    return_url_part = urllib.parse.quote_plus("/auth/connect/authorize/callback?")
    query_full = "ReturnUrl=" + return_url_part + query
    return f"https://singlekey-id.com/auth/en-us/login?{query_full}"


def extract_code_from_callback_url(url: str) -> str | None:
    """Extract authorization code from OAuth callback URL."""
    url = (url or "").strip()
    if "code=" not in url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        codes = params.get("code", [None])
        return codes[0] if codes else None
    except Exception:  # pylint: disable=broad-except
        _LOGGER.debug("Failed to parse callback URL")
        return None


async def exchange_code_for_tokens(session, code: str) -> dict[str, Any]:
    """Exchange authorization code for access and refresh tokens.

    Returns:
        Dict with access_token, refresh_token, expires_at (ISO string).
    """
    data = {
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": CODE_VERIFIER,
    }
    async with session.post(TOKEN_URL, data=data) as resp:
        if resp.status != 200:
            _LOGGER.warning("Token exchange failed: status=%s body=%s", resp.status, await resp.text())
            raise ConfigEntryAuthFailed(
                "OAuth token exchange failed. Try the callback URL again."
            ) from None
        out = await resp.json()
    if "access_token" not in out or "refresh_token" not in out:
        _LOGGER.warning("Token response missing access_token or refresh_token")
        raise ConfigEntryAuthFailed(
            "OAuth response incomplete. Try the login step again."
        ) from None
    expires_in = out.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return {
        "access_token": out["access_token"],
        "refresh_token": out["refresh_token"],
        "expires_at": expires_at.isoformat(),
    }


async def refresh_access_token(session, refresh_token: str) -> dict[str, Any]:
    """Refresh access token using refresh_token. Raises ConfigEntryAuthFailed on failure."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": " ".join(SCOPES),
        "client_id": CLIENT_ID,
    }
    async with session.post(TOKEN_URL, data=data) as resp:
        if resp.status in (401, 400):
            _LOGGER.warning("Token refresh failed: status=%s", resp.status)
            raise ConfigEntryAuthFailed(
                "Token expired or revoked. Please re-authenticate."
            ) from None
        if resp.status != 200:
            _LOGGER.warning("Token refresh failed: status=%s body=%s", resp.status, await resp.text())
            raise ConfigEntryAuthFailed(
                "Token refresh failed. Please re-authenticate."
            ) from None
        out = await resp.json()
    if "access_token" not in out:
        raise ConfigEntryAuthFailed(
            "Token refresh response invalid. Please re-authenticate."
        ) from None
    expires_in = out.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    result = {
        "access_token": out["access_token"],
        "refresh_token": out.get("refresh_token") or refresh_token,
        "expires_at": expires_at.isoformat(),
    }
    return result


def is_token_expired(expires_at: str | None, margin_seconds: int = 300) -> bool:
    """Return True if token is expired or within margin_seconds of expiry."""
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) >= (expiry - timedelta(seconds=margin_seconds))
    except (TypeError, ValueError):
        return True


async def ensure_valid_token(
    hass: HomeAssistant, entry: ConfigEntry, session
) -> str:
    """Ensure entry has a valid access token; refresh if needed. Updates entry.data. Returns access_token. Raises ConfigEntryAuthFailed on refresh failure."""
    data = entry.data
    access_token = data.get(ACCESS_TOKEN)
    refresh_token = data.get("refresh_token")
    expires_at = data.get("expires_at")
    if not refresh_token:
        raise ConfigEntryAuthFailed("No refresh token; please re-authenticate.")
    if not is_token_expired(expires_at):
        return access_token or ""
    new_tokens = await refresh_access_token(session, refresh_token)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **data,
            ACCESS_TOKEN: new_tokens["access_token"],
            "refresh_token": new_tokens["refresh_token"],
            "expires_at": new_tokens["expires_at"],
        },
    )
    return new_tokens["access_token"]
