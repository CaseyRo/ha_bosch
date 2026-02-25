# PoinTTAPI OAuth — Setup & Testing

## Setting up in Home Assistant

When setting up the Bosch EasyControl integration via the **Cloud / Bosch Account** option in HA, the final step asks you to paste a callback URL.

Getting that URL manually (opening the auth link, logging in, copying from the "Cannot open page" error screen) is unreliable — some browsers don't show it clearly.

**Use the helper script instead:**

```bash
./run_playwright_ha.sh
```

It opens a browser, you log in once, and it prints the callback URL:

```
============================================================
Paste this into Home Assistant:

com.bosch.tt.dashtt.pointt://app/login?code=ABC123...

============================================================
```

Copy that URL, paste it into the HA config flow field. The code is NOT consumed by the script — it stays valid for HA to use.

**First-time setup** (once only, on the machine running this script):
```bash
uv run --with playwright python -m playwright install chromium
```

---

## Testing tokens & API (development)

To test the full OAuth flow end-to-end (exchange code, test API paths):

```bash
./run_playwright.sh
```

This does everything: captures the callback, exchanges the code, and tests the API.
**Don't** use this before pasting into HA — it consumes the authorization code.

## Manual fallback

If the Playwright script breaks (e.g. Bosch changed their login page):

```bash
uv run --with aiohttp python test_pointtapi_oauth.py
```

This prints the auth URL for you to open manually, then asks you to paste the callback URL back.

## Notes

- `.env` — device serial (gitignored); credentials are entered in the browser
- The Bosch login page detects automation — `playwright-stealth` is used to work around this
