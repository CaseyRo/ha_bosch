"""Tests for the Bosch EasyControl config flow (EasyControl-only).

These tests run in CI where homeassistant, voluptuous, and
bosch-thermostat-client are installed. The conftest.py shell-package
setup ensures relative imports resolve correctly.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.bosch.config_flow import BoschFlowHandler, OptionsFlowHandler
from custom_components.bosch.const import (
    ACCESS_KEY,
    ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_PROTOCOL,
    POINTTAPI,
    UUID,
)


def _make_flow(hass=None) -> BoschFlowHandler:
    """Create a BoschFlowHandler with a mock hass."""
    flow = BoschFlowHandler()
    flow.hass = hass or MagicMock()
    flow.context = {}
    return flow


# ── POINTTAPI happy path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_step_shows_easycontrol_protocol(mock_hass):
    """async_step_user goes straight to easycontrol_protocol."""
    flow = _make_flow(mock_hass)
    result = await flow.async_step_user(None)
    assert result["type"] == "form"
    assert result["step_id"] == "easycontrol_protocol"


@pytest.mark.asyncio
async def test_pointtapi_protocol_goes_to_oauth(mock_hass):
    """Choosing POINTTAPI goes straight to OAuth (OAuth-first flow)."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    result = await flow.async_step_easycontrol_protocol(
        {CONF_PROTOCOL: POINTTAPI}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_oauth_open"


@pytest.mark.asyncio
async def test_xmpp_protocol_shows_xmpp_config(mock_hass):
    """Choosing XMPP shows xmpp_config form."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    result = await flow.async_step_easycontrol_protocol(
        {CONF_PROTOCOL: "XMPP"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "xmpp_config"


def _prime_tokens(flow):
    """Give a flow OAuth tokens + entry-creation mocks (post-OAuth state)."""
    flow._tokens = {
        "access_token": "at_123",
        "refresh_token": "rt_456",
        "expires_at": "2099-12-31T23:59:59+00:00",
    }
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})


@pytest.mark.asyncio
async def test_pointtapi_device_id_valid(mock_hass):
    """Valid numeric device ID (manual fallback) creates the entry."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)
    result = await flow.async_step_pointtapi_device_id(
        {CONF_DEVICE_ID: "123456789"}
    )
    assert result["type"] == "create_entry"
    assert flow._host == "123456789"


@pytest.mark.asyncio
async def test_pointtapi_device_id_with_dashes(mock_hass):
    """Device ID with dashes is stripped and accepted."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)
    result = await flow.async_step_pointtapi_device_id(
        {CONF_DEVICE_ID: "123-456-789"}
    )
    assert result["type"] == "create_entry"
    assert flow._host == "123456789"


@pytest.mark.asyncio
async def test_pointtapi_invalid_device_id(mock_hass):
    """Non-numeric device ID shows error."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    result = await flow.async_step_pointtapi_device_id(
        {CONF_DEVICE_ID: "abc-xyz"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_device_id"


@pytest.mark.asyncio
async def test_pointtapi_oauth_open_shows_form(mock_hass):
    """oauth_open shows form with auth URL."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    result = await flow.async_step_pointtapi_oauth_open(None)
    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_oauth_open"
    assert "auth_url" in result.get("description_placeholders", {})


@pytest.mark.asyncio
async def test_pointtapi_oauth_open_submit_goes_to_oauth(mock_hass):
    """Submitting oauth_open (empty form) shows oauth paste form."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    result = await flow.async_step_pointtapi_oauth_open({})
    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_oauth"


@pytest.mark.asyncio
async def test_pointtapi_empty_callback(mock_hass):
    """Empty callback URL shows error."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    flow.context = {}
    result = await flow.async_step_pointtapi_oauth(
        {"oauth_callback_url": ""}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "oauth_callback_empty"


@pytest.mark.asyncio
async def test_pointtapi_invalid_callback(mock_hass):
    """Callback URL without valid code shows error."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    flow.context = {}
    with patch(
        "custom_components.bosch.config_flow.extract_code_from_callback_url",
        return_value=None,
    ):
        result = await flow.async_step_pointtapi_oauth(
            {"oauth_callback_url": "https://example.com/no-code"}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "oauth_callback_invalid"


@pytest.mark.asyncio
async def test_pointtapi_token_exchange_failure(mock_hass):
    """Token exchange failure shows error."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    flow.context = {}
    with (
        patch(
            "custom_components.bosch.config_flow.extract_code_from_callback_url",
            return_value="valid_code",
        ),
        patch(
            "custom_components.bosch.config_flow.exchange_code_for_tokens",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ),
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
    ):
        result = await flow.async_step_pointtapi_oauth(
            {"oauth_callback_url": "com.bosch.tt.dashtt.pointt://app/login?code=valid_code"}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "oauth_token_failed"


@pytest.mark.asyncio
async def test_pointtapi_happy_path_creates_entry(mock_hass):
    """Full POINTTAPI flow: OAuth → single-gateway auto-select → entry."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow.context = {}

    fake_tokens = {
        "access_token": "at_123",
        "refresh_token": "rt_456",
        "expires_at": "2099-12-31T23:59:59+00:00",
    }

    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    with (
        patch(
            "custom_components.bosch.config_flow.extract_code_from_callback_url",
            return_value="auth_code_abc",
        ),
        patch(
            "custom_components.bosch.config_flow.exchange_code_for_tokens",
            new_callable=AsyncMock,
            return_value=fake_tokens,
        ),
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.bosch.config_flow.async_list_gateways",
            new_callable=AsyncMock,
            return_value=[{"deviceId": "123456789", "deviceType": "rrc2"}],
        ),
    ):
        result = await flow.async_step_pointtapi_oauth(
            {"oauth_callback_url": "com.bosch.tt.dashtt.pointt://app/login?code=auth_code_abc"}
        )

    assert result["type"] == "create_entry"
    flow.async_set_unique_id.assert_awaited_once_with("123456789")
    flow._abort_if_unique_id_configured.assert_called_once()
    call_kwargs = flow.async_create_entry.call_args
    data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    assert data[CONF_PROTOCOL] == POINTTAPI
    assert data[ACCESS_TOKEN] == "at_123"
    assert data[CONF_DEVICE_ID] == "123456789"
    assert data[UUID] == "123456789"
    assert data[ACCESS_KEY] == ""


# ── Gateway discovery (auto-select / picker / fallback) ─────────────────────


@pytest.mark.asyncio
async def test_gateway_multi_shows_picker(mock_hass):
    """Two gateways → selection form listing id + deviceType."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)
    with (
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.bosch.config_flow.async_list_gateways",
            new_callable=AsyncMock,
            return_value=[
                {"deviceId": "111", "deviceType": "rrc2"},
                {"deviceId": "222", "deviceType": "k40"},
            ],
        ),
    ):
        result = await flow.async_step_pointtapi_gateway(None)

    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_gateway"


@pytest.mark.asyncio
async def test_gateway_picker_selection_creates_entry(mock_hass):
    """Submitting a picker choice creates the entry for that gateway."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)

    result = await flow.async_step_pointtapi_gateway({CONF_DEVICE_ID: "222"})

    assert result["type"] == "create_entry"
    assert flow._host == "222"
    flow.async_set_unique_id.assert_awaited_once_with("222")


@pytest.mark.asyncio
async def test_gateway_listing_failure_falls_back_to_manual(mock_hass):
    """Listing error → manual serial-entry form (v0.33 fallback)."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)
    with (
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.bosch.config_flow.async_list_gateways",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = await flow.async_step_pointtapi_gateway(None)

    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_device_id"


@pytest.mark.asyncio
async def test_gateway_empty_listing_falls_back_to_manual(mock_hass):
    """Zero gateways → manual serial-entry form."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    _prime_tokens(flow)
    with (
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.bosch.config_flow.async_list_gateways",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await flow.async_step_pointtapi_gateway(None)

    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_device_id"


# ── XMPP gateway configuration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xmpp_configure_gateway_success(mock_hass):
    """configure_gateway with valid credentials creates an entry."""
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"

    mock_device = MagicMock()
    mock_device.device_name = "EasyControl CT200"
    mock_device.host = "192.168.1.100"
    mock_device.access_key = "key123"
    mock_device.access_token = "token456"
    mock_device.check_connection = AsyncMock(return_value="uuid-001")

    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    with patch(
        "custom_components.bosch.config_flow.gateway_chooser",
        return_value=MagicMock(return_value=mock_device),
    ):
        mock_hass.async_add_executor_job = AsyncMock(return_value=mock_device)
        result = await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.100",
            access_token="token456",
            password="pass",
        )

    assert result["type"] == "create_entry"
    call_kwargs = flow.async_create_entry.call_args
    data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    assert data[UUID] == "uuid-001"
    assert data[CONF_PROTOCOL] == "XMPP"


@pytest.mark.asyncio
async def test_xmpp_bad_credentials_aborts(mock_hass):
    """configure_gateway with bad credentials aborts with faulty_credentials."""
    from bosch_thermostat_client.exceptions import DeviceException

    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow.async_abort = MagicMock(return_value={"type": "abort", "reason": "faulty_credentials"})

    mock_hass.async_add_executor_job = AsyncMock(side_effect=DeviceException)

    with patch(
        "custom_components.bosch.config_flow.gateway_chooser",
        return_value=MagicMock(),
    ):
        result = await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.100",
            access_token="bad_token",
        )

    assert result["type"] == "abort"
    assert result["reason"] == "faulty_credentials"


# ── Reauth flow ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reauth_pointtapi_goes_to_oauth(mock_hass):
    """Reauth for POINTTAPI entry goes to oauth_open."""
    flow = _make_flow(mock_hass)
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_PROTOCOL: POINTTAPI,
        CONF_DEVICE_ID: "123456789",
        CONF_DEVICE_TYPE: "EASYCONTROL",
        UUID: "123456789",
    }
    flow._get_reauth_entry = MagicMock(return_value=mock_entry)

    result = await flow.async_step_reauth(mock_entry.data)
    assert result["type"] == "form"
    assert result["step_id"] == "pointtapi_oauth_open"


@pytest.mark.asyncio
async def test_reauth_non_pointtapi_aborts(mock_hass):
    """Reauth for non-POINTTAPI entry aborts."""
    flow = _make_flow(mock_hass)
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    mock_entry.data = {CONF_PROTOCOL: "XMPP"}
    flow._get_reauth_entry = MagicMock(return_value=mock_entry)
    flow.async_abort = MagicMock(return_value={"type": "abort", "reason": "reauth_invalid"})

    result = await flow.async_step_reauth(mock_entry.data)
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_invalid"


@pytest.mark.asyncio
async def test_reauth_success_updates_tokens(mock_hass):
    """Reauth with valid code updates tokens and reloads."""
    flow = _make_flow(mock_hass)
    flow.context = {"entry_id": "test_entry"}
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"

    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_PROTOCOL: POINTTAPI,
        CONF_DEVICE_ID: "123456789",
        UUID: "123456789",
    }
    flow._get_reauth_entry = MagicMock(return_value=mock_entry)

    fake_tokens = {
        "access_token": "new_at",
        "refresh_token": "new_rt",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reauth_successful"}
    )

    with (
        patch(
            "custom_components.bosch.config_flow.extract_code_from_callback_url",
            return_value="reauth_code",
        ),
        patch(
            "custom_components.bosch.config_flow.exchange_code_for_tokens",
            new_callable=AsyncMock,
            return_value=fake_tokens,
        ),
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
    ):
        result = await flow.async_step_pointtapi_oauth(
            {"oauth_callback_url": "com.bosch.tt.dashtt.pointt://app/login?code=reauth_code"}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    flow.async_update_reload_and_abort.assert_called_once()
    update_data = flow.async_update_reload_and_abort.call_args
    data_updates = update_data.kwargs.get("data_updates") or update_data[1].get("data_updates")
    assert data_updates[ACCESS_TOKEN] == "new_at"


# ── Duplicate detection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_pointtapi_entry_aborts(mock_hass):
    """Duplicate POINTTAPI device_id aborts with already_configured."""
    from homeassistant.data_entry_flow import AbortFlow

    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._host = "123456789"
    flow.context = {}

    fake_tokens = {
        "access_token": "at",
        "refresh_token": "rt",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }

    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock(
        side_effect=AbortFlow("already_configured")
    )

    with (
        patch(
            "custom_components.bosch.config_flow.extract_code_from_callback_url",
            return_value="code",
        ),
        patch(
            "custom_components.bosch.config_flow.exchange_code_for_tokens",
            new_callable=AsyncMock,
            return_value=fake_tokens,
        ),
        patch(
            "custom_components.bosch.config_flow.async_get_clientsession",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.bosch.config_flow.async_list_gateways",
            new_callable=AsyncMock,
            return_value=[{"deviceId": "123456789", "deviceType": "rrc2"}],
        ),
    ):
        with pytest.raises(AbortFlow, match="already_configured"):
            await flow.async_step_pointtapi_oauth(
                {"oauth_callback_url": "com.bosch.tt.dashtt.pointt://app/login?code=code"}
            )


# ── Remaining legacy and options branches ───────────────────────────────────


@pytest.mark.asyncio
async def test_xmpp_config_local_uses_http_executor_session(mock_hass):
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow.configure_gateway = AsyncMock(return_value={"type": "create_entry"})

    with patch(
        "custom_components.bosch.config_flow.async_get_clientsession",
        return_value="http-session",
    ):
        result = await flow.async_step_xmpp_config(
            {
                "address": "127.0.0.1",
                "access_token": "token",
                "password": "secret",
            }
        )

    assert result["type"] == "create_entry"
    flow.configure_gateway.assert_awaited_once()
    kwargs = flow.configure_gateway.await_args.kwargs
    assert kwargs["session_type"] == "HTTP"
    assert kwargs["host"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_xmpp_config_remote_uses_selected_protocol(mock_hass):
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._protocol = "XMPP"
    flow.configure_gateway = AsyncMock(return_value={"type": "create_entry"})

    result = await flow.async_step_xmpp_config(
        {"address": "192.168.1.20", "access_token": "token"}
    )

    assert result["type"] == "create_entry"
    kwargs = flow.configure_gateway.await_args.kwargs
    assert kwargs["session_type"] == "XMPP"
    assert kwargs["session"] is mock_hass.loop


@pytest.mark.asyncio
async def test_configure_gateway_firmware_error_notifies_and_creates_entry(mock_hass):
    from bosch_thermostat_client.exceptions import FirmwareException

    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    flow._password = "secret"
    device = MagicMock(
        device_name="EasyControl",
        host="192.168.1.20",
        access_key="key",
        access_token="token",
        uuid="uuid-device",
    )
    device.check_connection = AsyncMock(side_effect=FirmwareException("old firmware"))
    mock_hass.async_add_executor_job = AsyncMock(return_value=device)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    with patch("custom_components.bosch.config_flow.gateway_chooser", return_value=MagicMock()), patch(
        "custom_components.bosch.config_flow.create_notification_firmware"
    ) as notify:
        result = await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.20",
            access_token="token",
        )

    assert result["type"] == "create_entry"
    notify.assert_called_once()
    flow.async_set_unique_id.assert_awaited_once_with("uuid-device")


@pytest.mark.asyncio
async def test_configure_gateway_executor_runs_gateway_constructor(mock_hass):
    flow = _make_flow(mock_hass)
    flow._choose_type = "EASYCONTROL"
    device = MagicMock(
        device_name="EasyControl",
        host="192.168.1.20",
        access_key="key",
        access_token="token",
        check_connection=AsyncMock(return_value="uuid-device"),
    )
    gateway_class = MagicMock(return_value=device)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    async def run_in_executor(function):
        return function()

    mock_hass.async_add_executor_job = run_in_executor
    with patch("custom_components.bosch.config_flow.gateway_chooser", return_value=gateway_class):
        result = await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.20",
            access_token="token",
            password="secret",
            session="session",
        )

    assert result["type"] == "create_entry"
    gateway_class.assert_called_once_with(
        session_type="XMPP",
        host="192.168.1.20",
        access_token="token",
        password="secret",
        session="session",
    )


@pytest.mark.asyncio
async def test_configure_gateway_unexpected_error_aborts_unknown(mock_hass):
    flow = _make_flow(mock_hass)
    flow.async_abort = MagicMock(return_value={"type": "abort", "reason": "unknown"})
    mock_hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("custom_components.bosch.config_flow.gateway_chooser", return_value=MagicMock()):
        result = await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.20",
            access_token="token",
        )

    assert result == {"type": "abort", "reason": "unknown"}


@pytest.mark.asyncio
async def test_configure_gateway_abort_flow_is_re_raised(mock_hass):
    from homeassistant.data_entry_flow import AbortFlow

    flow = _make_flow(mock_hass)
    mock_hass.async_add_executor_job = AsyncMock(side_effect=AbortFlow("cancelled"))

    with patch("custom_components.bosch.config_flow.gateway_chooser", return_value=MagicMock()), pytest.raises(AbortFlow):
        await flow.configure_gateway(
            device_type="EASYCONTROL",
            session_type="XMPP",
            host="192.168.1.20",
            access_token="token",
        )


@pytest.mark.asyncio
async def test_options_flow_shows_defaults_and_creates_options():
    entry = MagicMock(options={"new_stats_api": True, "optimistic_mode": False})
    flow = OptionsFlowHandler(entry)
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    assert await flow.async_step_init(None) == {"type": "form"}
    flow.async_show_form.assert_called_once()
    assert await flow.async_step_init({"new_stats_api": False, "optimistic_mode": True}) == {"type": "create_entry"}


@pytest.mark.asyncio
async def test_discovery_step_is_a_noop(mock_hass):
    flow = _make_flow(mock_hass)
    assert await flow.async_step_discovery({"host": "192.168.1.20"}) is None


def test_async_get_options_flow_returns_options_handler():
    entry = MagicMock()
    options_flow = BoschFlowHandler.async_get_options_flow(entry)
    assert isinstance(options_flow, OptionsFlowHandler)
