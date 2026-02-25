# Home Assistant core docs – implementation improvements (JSON / POINTTAPI flow)

Based on [Home Assistant Developer Docs](https://developers.home-assistant.io/docs/development_index), these are concrete improvements to apply when implementing the **JSON-based (POINTTAPI)** flow. They align with the integration quality scale (Bronze → Silver → Platinum) and current HA best practices.

---

## 1. Manifest

- **Set `integration_type`**  
  Required going forward. Use `"hub"` (gateway to multiple devices/entities).  
  [Integration manifest – Integration type](https://developers.home-assistant.io/docs/creating_integration_manifest#integration-type)
- **IoT class for POINTTAPI**  
  POINTTAPI is cloud + polling → `"cloud_polling"`. Already set in current manifest; keep for POINTTAPI-only or split by protocol in code if both XMPP and POINTTAPI coexist.
- **Optional: `quality_scale`**  
  e.g. `"silver"` in manifest and add `quality_scale.yaml` to track rules when aiming for a tier.

---

## 2. Data fetching – use DataUpdateCoordinator

- **Current:** Custom interval (`async_track_time_interval`) + dispatcher signals; each platform subscribes to a signal and calls its own update. Multiple timers (main, firmware, recording).
- **Recommendation for POINTTAPI:** Use a **single `DataUpdateCoordinator`** that:
  - Polls the JSON API (e.g. full or partial scan) at a fixed interval.
  - Exposes the last successful payload (and optional last error).
  - Entities use `CoordinatorEntity` and `_handle_coordinator_update()` to read from coordinator data (no per-entity network calls).
- **Benefits:** One place for refresh logic, automatic retry/backoff, `ConfigEntryNotReady` on first failure, and less duplicate polling.  
  [Fetching data – Coordinated single API poll](https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities)
- **Optional:** If the API supports it, set `always_update=False` when the new data can be compared with `__eq__` to avoid unnecessary state writes when nothing changed.

---

## 3. Entity naming and device info

- **`has_entity_name = True`**  
  Mandatory for new integrations. Entity `name` should describe the data point (e.g. "Temperature", "Valve position"), not the device name. `friendly_name` is then `"{device_name} {entity_name}"`.  
  [Entity – has_entity_name True](https://developers.home-assistant.io/docs/entity_index#has_entity_name-true-mandatory-for-new-integrations)
- **Translations for names**  
  Prefer `translation_key` (and optionally `translation_placeholders`) in `strings.json` instead of hard-coded English names.  
  [Entity naming](https://developers.home-assistant.io/docs/entity_index#entity-naming)
- **Device registry – identifiers**  
  `DeviceInfo.identifiers` must be a **set of 2-tuples** `(domain, identifier)` (e.g. `{(DOMAIN, unique_id)}`). The codebase currently uses 3-tuples (e.g. `(DOMAIN, parent_id, uuid)`), which does not match the typed `set[tuple[str, str]]`. For POINTTAPI (and ideally fix globally), use a single stable string per device, e.g. `(DOMAIN, f"{entry_uuid}_{circuit_or_zone_id}")` for sub-devices and `(DOMAIN, entry_uuid)` for the gateway.  
  [Device registry – Automatic registration](https://developers.home-assistant.io/docs/device_registry_index#automatic-registration-through-an-entity)

---

## 4. Entity descriptions and diagnostics

- **Sensor / number / select:** Use **entity descriptions** (e.g. `SensorEntityDescription` with `key`, `device_class`, `state_class`, `native_unit_of_measurement`) and a list of descriptions; create one entity per description that applies. Declarative and easier to add the POINTTAPI-only sensors (humidity, valve position, etc.).  
  [Entity – Entity description](https://developers.home-assistant.io/docs/entity_index#entity-description)
- **Diagnostic / rarely-used entities**  
  Set `entity_category = EntityCategory.DIAGNOSTIC` and consider `entity_registry_enabled_default = False` for fast-changing or noisy entities (e.g. RSSI, chip temperature).  
  [Entity – entity_category, entity_registry_enabled_default](https://developers.home-assistant.io/docs/entity_index#registry-properties)

---

## 5. Re-auth and error handling (Silver tier)

- **Auth failures**  
  When the POINTTAPI client gets 401/403 or token expired, raise `ConfigEntryAuthFailed` from the coordinator’s update method. HA will cancel updates and start the config flow with `SOURCE_REAUTH`.
- **Implement reauth**  
  Add `async_step_reauth` in the config flow to re-prompt for token or OAuth without removing the entry.  
  [Fetching data – ConfigEntryAuthFailed](https://developers.home-assistant.io/docs/integration_fetching_data) (coordinator example); [Quality scale – Silver](https://developers.home-assistant.io/docs/core/integration-quality-scale#-silver) (re-authentication).
- **Connection/offline**  
  Set entity `available` to False on persistent failure; recover when the next poll succeeds. Avoid filling logs with repeated errors (e.g. log once and back off or log at debug after the first failure).

---

## 6. Properties and state

- **No I/O in properties**  
  Properties (e.g. `native_value`, `state`) must only return in-memory state. All fetching in `async_update()` or in the coordinator callback.  
  [Entity – Generic properties](https://developers.home-assistant.io/docs/entity_index#generic-properties)
- **Unrecorded attributes**  
  If some attributes are not useful for history (e.g. large or frequently changing JSON), add them to `_unrecorded_attributes` (or the domain’s `_entity_component_unrecorded_attributes`) so the recorder can exclude them.  
  [Entity – Excluding state attributes from recorder history](https://developers.home-assistant.io/docs/entity_index#excluding-state-attributes-from-recorder-history)

---

## 7. Config flow

- **Deprecate `CONNECTION_CLASS`**  
  If present, remove it; it’s deprecated and no longer used.
- **POINTTAPI-specific steps**  
  For POINTTAPI, add steps for: protocol choice (if both XMPP and POINTTAPI), host/serial, then token file or OAuth. Use `vol.In` for protocol; keep address/token validation and clear error messages.
- **Discovery**  
  Zeroconf is already in the manifest. For POINTTAPI-only setups there is no local discovery; discovery stays relevant for HTTP/XMPP. No change required for JSON-only path.

---

## 8. Optional: Icons and translations

- Prefer **icon translations** in `icons.json` (keyed by `translation_key` and state) over setting the `icon` property in code.  
  [Entity – Icons](https://developers.home-assistant.io/docs/entity_index#icons)

---

## 9. Summary checklist (JSON flow only)

| Area | Action |
|------|--------|
| Manifest | Add `integration_type: "hub"`; keep `iot_class: "cloud_polling"` for POINTTAPI. |
| Data | Introduce a single DataUpdateCoordinator for POINTTAPI JSON polling; entities use CoordinatorEntity. |
| Entities | Use `_attr_has_entity_name = True`; entity name = data point; use translation_key where possible. |
| Device | Fix identifiers to 2-tuples `(DOMAIN, unique_id)`; optional suggested_area. |
| Sensors | Prefer SensorEntityDescription (and similar) for POINTTAPI sensors. |
| Diagnostics | entity_category = DIAGNOSTIC; entity_registry_enabled_default = False for noisy/diagnostic-only. |
| Reauth | On auth error raise ConfigEntryAuthFailed; implement async_step_reauth. |
| Errors | Set available = False on failure; avoid log spam. |
| Properties | No I/O in properties; optional _unrecorded_attributes for large/volatile attrs. |
| Config flow | Remove CONNECTION_CLASS; add POINTTAPI/OAuth steps as needed. |

These improvements keep the existing XMPP/HTTP behavior untouched and apply to the new JSON-based (POINTTAPI) implementation path.
