## Purpose

Removes the manual serial-number step from POINTTAPI setup by listing the account's paired gateways after OAuth and selecting one automatically, or offering a picker. Falls back to manual entry whenever the listing is unavailable, so setup can always complete.

## Requirements

### Requirement: Client lists account gateways

`PoinTTAPIClient` (or a flow-level helper sharing its token handling) SHALL expose `list_gateways() -> list[dict]` issuing `GET https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/` (account-level route, no `/resource` suffix and no gateway id) with the standard Bearer token. The call relies on the `pointt.gateway.list` scope already present in the integration's token request. Each returned entry SHALL be surfaced with at least its gateway id and, when present, its `deviceType`.

#### Scenario: Account with one CT200

- **WHEN** `list_gateways()` is called with a valid token for an account holding one paired EasyControl
- **THEN** it SHALL return a single-entry list whose gateway id equals the device serial used by the existing resource API

### Requirement: POINTTAPI config flow runs OAuth before device selection

The POINTTAPI branch of the config flow SHALL be reordered to: `choose_type` → `easycontrol_protocol` → `pointtapi_oauth_open` (show login URL) → `pointtapi_oauth` (paste callback URL, exchange code for tokens) → gateway selection → `create_entry`. The authorization URL SHALL remain device-independent so no information is lost by the reorder. The data keys stored on the created entry (device id, tokens, protocol) SHALL remain exactly those of v0.33 so existing entries, reauth, and diagnostics are unaffected.

#### Scenario: Fresh setup happy path

- **WHEN** a user completes OAuth and the account lists exactly one gateway
- **THEN** the flow SHALL create the entry without ever showing a device-id form, and the entry data SHALL contain the same keys as a v0.33 entry

#### Scenario: Existing entries untouched

- **WHEN** the integration upgrades from v0.33 with an existing POINTTAPI entry
- **THEN** the entry SHALL load without migration and the reauth flow SHALL behave exactly as before (tokens refreshed, no device re-selection)

### Requirement: Gateway selection auto-selects, offers a picker, or falls back to manual entry

After token exchange the flow SHALL call `list_gateways()` and: with exactly one gateway, select it automatically; with more than one, show a selection form listing gateway id and device type; with zero gateways or on any listing error (network, 4xx/5xx, unexpected shape), show the existing manual serial-entry form from v0.33 as fallback. The listing call SHALL NOT be able to abort the flow.

#### Scenario: Two gateways on one account

- **WHEN** the account lists two gateways
- **THEN** the flow SHALL present both (id + device type) and create the entry with the user's choice

#### Scenario: Listing endpoint fails

- **WHEN** `list_gateways()` raises or returns an unexpected payload
- **THEN** the flow SHALL log the error at debug level and present the manual serial-entry form, allowing setup to complete exactly as in v0.33
