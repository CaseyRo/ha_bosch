## Purpose

Cuts POINTTAPI cloud traffic by discovering the resource path set once via the reference walk and then polling it through the pointt-api bulk endpoint, instead of one GET per path per cycle. Keeps `coordinator.data`'s `{path: response}` shape so entity code is unaffected, and falls back to the sequential walk whenever bulk fails.

## Requirements

### Requirement: Client exposes a bulk read method following the observed pointt-api envelope

`PoinTTAPIClient` SHALL expose `bulk(paths: list[str]) -> dict[str, Any]` that issues `POST https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/bulk` with JSON body `[{"gatewayId": <device_id>, "resourcePaths": [<path>, ...]}]`. Paths SHALL use the same format as `get()` (leading slash, no `/resource` prefix — e.g. `/gateway`, `/zones/zn1/temperatureActual`). Requests SHALL be chunked at 30 paths per call, with chunks issued sequentially (never concurrently). The response SHALL be parsed as `[0].resourcePaths[]`, and a path's payload accepted only when both `serverStatus == 200` and `gatewayResponse.status == 200`; accepted payloads are returned as `{path: gatewayResponse.payload}`. The method's definition site SHALL carry a provenance comment crediting `serbanb11/homecom_alt` as the source of the wire format.

#### Scenario: 45 paths are fetched in two chunks

- **WHEN** `bulk()` is called with 45 paths
- **THEN** the client SHALL issue exactly 2 sequential POSTs (30 + 15 paths) and return a single merged `{path: payload}` dict

#### Scenario: Per-path 403 inside a 200 envelope

- **WHEN** the bulk POST returns HTTP 200 but one entry has `serverStatus: 403` with a null `gatewayResponse`
- **THEN** that path SHALL be omitted from the returned dict and the remaining paths returned normally

#### Scenario: Auth failure on the bulk route

- **WHEN** the bulk POST itself returns HTTP 401 or 403
- **THEN** the client SHALL raise the same auth exception type as `get()` does, so the coordinator's existing `ConfigEntryAuthFailed` handling applies

### Requirement: Coordinator discovers paths by reference walk, then polls via bulk

On the first refresh after setup or reload, `PoinTTAPIDataUpdateCoordinator` SHALL run the existing sequential reference walk (roots + references + refEnum second level) and persist the resulting flat path list as the bulk path set. On subsequent refreshes the coordinator SHALL fetch that path set via `client.bulk()` instead of sequential GETs, while keeping `coordinator.data`'s shape (`{path: response}`) unchanged so no entity code needs modification. The discovery walk SHALL re-run at most once per 24 hours so resources that appear later (e.g. solar enabled by an installer) are picked up without a reload.

#### Scenario: Steady-state poll uses bulk only

- **WHEN** the coordinator refreshes after a successful discovery walk and the path set holds 48 paths
- **THEN** the cycle SHALL issue 2 bulk POSTs (plus the paginated-resource GETs per the pagination requirement) and zero per-path GETs

#### Scenario: Entities read unchanged data shape

- **WHEN** entities call `coordinator.data.get("/system/sensors/temperatures/outdoor_t1")` after the bulk migration
- **THEN** the value SHALL have the same shape as the per-GET response body did in v0.33 (`{"id": ..., "value": ..., ...}`)

#### Scenario: Daily rediscovery picks up new resources

- **WHEN** 24 hours have elapsed since the last discovery walk and a refresh begins
- **THEN** the coordinator SHALL run the reference walk again and replace the bulk path set with the new result

### Requirement: Bulk failure falls back to the sequential GET walk for that cycle

When a bulk call fails wholesale (network error, non-2xx envelope, unparseable body), the coordinator SHALL fall back to the v0.33 sequential GET walk for that refresh cycle. Per-path failures inside a successful envelope SHALL be skipped with a debug log (matching the per-GET skip semantics). Persistent bulk failure SHALL be logged at WARNING level at most once per hour, with subsequent occurrences at DEBUG.

#### Scenario: Bulk endpoint removed by Bosch

- **WHEN** every bulk POST starts returning HTTP 404
- **THEN** every refresh cycle SHALL complete via the sequential GET walk, entities keep updating, and the log shows at most one WARNING per hour about the bulk failure

#### Scenario: Single malformed envelope

- **WHEN** one refresh's bulk response is unparseable but the next refresh's is valid
- **THEN** the first cycle SHALL fall back to sequential GETs and the second cycle SHALL use bulk again — no sticky disable

### Requirement: Paginated resources stay on the sequential GET path

Resources that require query-string pagination — currently `/energy/historyHourly` with its `?next=<cursor>` walk — SHALL continue to be fetched via sequential GETs even in bulk steady state, because the bulk envelope's `resourcePaths` carry no query parameters.

#### Scenario: historyHourly still paginates under bulk polling

- **WHEN** a steady-state refresh runs with bulk polling active
- **THEN** `/energy/historyHourly` SHALL be fetched via the existing `_fetch_history_hourly_all()` GET pagination and its flattened result stored at the same key, while non-paginated paths ride the bulk call
