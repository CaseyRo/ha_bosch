# POINTTAPI dependency

For **EasyControl via POINTTAPI** (cloud JSON API), the integration uses the same OAuth endpoints as the deric POINTTAPI client. The upstream `bosch-thermostat-client` does not support POINTTAPI.

- **Source (reference):** [deric/bosch-thermostat-client-python](https://github.com/deric/bosch-thermostat-client-python), branch **k30**.
- **Usage:** OAuth (paste callback URL) + device ID (serial without dashes). Tokens are stored in the config entry and refreshed automatically.

## Callback URL (OAuth)

After logging in at the Bosch page, the browser redirects to a URL like:

`com.bosch.tt.dashtt.pointt://app/login?code=...`

- **On desktop:** Copy the **entire URL** from the address bar (the page may show "Cannot open page" — that’s normal).
- **On mobile:** If the app doesn’t open, copy the full URL from the in-app browser or from the system browser if it opened there.
- Paste that full URL into the integration’s "Callback URL" field. The integration extracts the `code` and exchanges it for tokens; the URL itself is not stored.
