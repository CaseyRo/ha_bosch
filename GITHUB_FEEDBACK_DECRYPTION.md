# Feedback for bosch-thermostat-client (EasyControl XMPP decryption)

Copy or adapt the sections below into a **new issue** at:  
https://github.com/bosch-thermostat/bosch-thermostat-client-python/issues

Use the title: **EasyControl XMPP: SASL succeeds but all API responses fail to decrypt**

---

## Summary

With EasyControl (CT200) over XMPP, authentication succeeds when using serial **without** dashes and the app password. The device then returns encrypted HTTP 200 responses for `/gateway/uuid`, `/system/interfaces`, etc., but **decryption fails** for every path. The failure points to the derived AES key not matching what the device uses to encrypt.

Related: [home-assistant-bosch-custom-component#531](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/531) (same symptom: "Can't decrypt for /gateway/uuid", "Your device is unknown null").

---

## Environment

- **Library:** bosch-thermostat-client 0.28.2
- **Device:** Bosch EasyControl (CT200)
- **Protocol:** XMPP only (local HTTP to device IP not available / not tested successfully)
- **Python:** 3.x

---

## Credentials / serial format that get past auth

- **Serial:** Must be entered **without dashes** (e.g. `101506113`). With dashes (e.g. `101-506-113`) the XMPP server returns `<not-authorized />`.
- **Access token:** From device sticker; we use it as-is (library strips dashes internally).
- **Password:** The password set in the Bosch/Buderus mobile app is **required**. Without it, SASL fails. With it, SASL succeeds.

So the combination that reaches the decryption step is: **serial no dashes + access token + app password**.

---

## What happens after auth

1. Client sends GETs (e.g. `GET /gateway/uuid HTTP/1.1`, `GET /system/interfaces HTTP/1.1`, etc.) over XMPP.
2. Device responds with `HTTP/1.1 200 OK` and a base64-encoded body (encrypted payload).
3. Library tries to decrypt and fails every time.

**Log output:**

```
WARNING [bosch_thermostat_client.connectors.xmpp] Can't decrypt for /gateway/uuid
DEBUG  [bosch_thermostat_client.connectors.xmpp] Response to GET request /gateway/uuid: null
DEBUG  [bosch_thermostat_client.encryption.base] Unable to decrypt: b'...' with error: 'utf-8' codec can't decode byte 0xe9 in position 0: invalid continuation byte
```

Same pattern for `/system/interfaces`, `/gateway/versionFirmware`, `/gateway/productID`, `/gateway/DateTime`. End result: `UnknownDevice Your device is unknown null` because no gateway info can be read.

---

## Hypothesis that might help maintainers

- **Key derivation:** EasyControl uses `EasycontrolEncryption` (MAGIC_EASYCONTROL) and `BaseEncryption`: key from `MD5(access_key + magic)` + `MD5(magic + password)` where `access_key` is the token with dashes stripped. For our device/firmware, that derived key does not decrypt the device responses (garbage → UTF-8 decode error).
- Possibilities that might be worth checking:
  - Different **magic** or key-derivation formula for this EasyControl variant/firmware.
  - **Password** encoding (encoding, normalization, or order with token) different from what the device expects.
  - **Token:** device might expect token with dashes included in key derivation (library currently strips them).

---

## Reproduce with bosch_cli

```bash
# Auth succeeds; decryption then fails when the library fetches gateway info
bosch_cli scan --host 101506113 --token "YOUR_TOKEN" --password "YOUR_APP_PASSWORD" --protocol XMPP --device EASYCONTROL
```

(Replace with your real serial-no-dashes, token, and app password. Don’t post real credentials in the public issue.)

---

## Willing to help

Happy to run debug builds, try different token/password formats, or provide more log snippets. I can share a redacted raw response (base64 body) if that’s useful; I prefer not to post full credentials in the issue.

---

*Generated from local testing with the integration and a small Python script using bosch_thermostat_client 0.28.2.*
