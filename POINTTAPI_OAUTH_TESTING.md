# PoinTTAPI OAuth — Setup & Testing

## Using with Home Assistant

When setting up the Bosch EasyControl integration via the **Cloud / Bosch Account** option in HA, the final step asks you to paste a callback URL that starts with `com.bosch.tt.dashtt.pointt://app/login?code=...`.

Getting that URL manually (opening the auth link in your browser, logging in, then copying the URL from the browser's "Cannot open page" error screen) is unreliable — some browsers don't show it clearly in the address bar.

**Use the Playwright helper script instead:**

```bash
./run_playwright.sh
```

It opens a real browser, you log in once, and it prints the exact callback URL you need:

```
[OK] Callback URL: com.bosch.tt.dashtt.pointt://app/login?code=ABC123...
```

Copy that line and paste it into the HA config flow field. Done.

**First-time setup** (once only, on the machine running this script):
```bash
uv run --with playwright python -m playwright install chromium
```

---

## Testing tokens & API paths

`run_playwright.sh` also exchanges the code for tokens and tests them against the live API, so you can verify everything works end-to-end without touching HA.

## Manual fallback

If the Playwright script breaks (e.g. Bosch changed their login page):

```bash
uv run --with aiohttp python test_pointtapi_oauth.py
```

This prints the auth URL for you to open manually, then asks you to paste the callback URL back.

## Notes

- `.env` — device serial (gitignored); credentials no longer needed by the script
- `debug_screenshots/` — Playwright drops screenshots here when something goes wrong
- The Bosch login page detects automation — `playwright-stealth` is used to work around this
