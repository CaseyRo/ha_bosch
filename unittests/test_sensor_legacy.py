"""Unit tests for the legacy sensor and statistics helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_UNAVAILABLE

from custom_components.bosch.sensor.base import BoschBaseSensor
from custom_components.bosch.sensor.recording import RecordingSensor
from custom_components.bosch.sensor.statistic_helper import StatisticHelper


class DummyStatistic(StatisticHelper):
    _domain_name = "Dummy"

    @property
    def statistic_id(self):
        return "dummy:statistic"

    async def _upsert_past_statistics(self, start, stop):
        self.upserted = (start, stop)


def _bosch_object(**overrides):
    values = {
        "parent_id": None,
        "id": "sensor1",
        "device_class": None,
        "state_class": None,
        "unit_of_measurement": "C",
        "entity_category": None,
        "state": "fallback",
        "state_message": "warming up",
        "path": "/sensor1",
        "update_initialized": True,
        "name": "Outdoor temperature",
        "unit_of_measurement": "C",
        "device_class": "temperature",
        "state_class": "measurement",
    }
    values.update(overrides)
    obj = SimpleNamespace(**values)
    obj.get_property = MagicMock(return_value={})
    obj.fetch_range = AsyncMock(return_value={})
    return obj


def _base_sensor(**overrides):
    entity = BoschBaseSensor(
        hass="hass",
        uuid="uuid1",
        bosch_object=_bosch_object(**overrides),
        gateway=MagicMock(),
        name="Outdoor temperature",
        attr_uri=overrides.pop("attr_uri", "temperature"),
        domain_name=overrides.pop("domain_name", "Sensors"),
        circuit_type=overrides.pop("circuit_type", None),
    )
    entity.async_schedule_update_ha_state = MagicMock()
    return entity


def _recording(**overrides):
    new_stats_api = overrides.pop("new_stats_api", False)
    recording_values = {
        "id": "recording1",
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total",
    }
    recording_values.update(overrides)
    obj = _bosch_object(**recording_values)
    entity = RecordingSensor(
        new_stats_api=new_stats_api,
        hass=MagicMock(),
        uuid="uuid1",
        bosch_object=obj,
        gateway=MagicMock(),
        name="Energy",
        attr_uri="recording",
    )
    entity.async_schedule_update_ha_state = MagicMock()
    entity._attr_entity_id = "sensor.energy"
    entity._short_id = "energy"
    return entity


class TestBoschBaseSensor:
    def test_initialization_covers_names_ids_and_sensor_metadata(self):
        sensor = _base_sensor()
        assert sensor.name == "Outdoor temperature"
        assert sensor.unique_id == "Sensorssensor1uuid1"
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE
        assert sensor.native_value is None

        named = _base_sensor(domain_name="Climate")
        assert named.name == "Climate Outdoor temperature"

        circuit = _base_sensor(circuit_type="hc", parent_id="hc1")
        assert circuit.name == "hc1 Outdoor temperature"
        assert circuit.unique_id == "Sensorshc1sensor1uuid1"

    def test_unavailable_state_is_exposed_as_none(self):
        sensor = _base_sensor()
        sensor._state = "unavailable"
        assert sensor.native_value is None

    def test_initialization_converts_total_temperature_to_measurement_and_timestamp(self):
        sensor = _base_sensor(
            state_class="total",
            device_class="temperature",
            attr_uri="startTime",
        )
        assert sensor.state_class == "measurement"
        assert sensor.device_class == SensorDeviceClass.TIMESTAMP

    @pytest.mark.asyncio
    async def test_update_reads_value_units_name_and_attributes(self):
        sensor = _base_sensor()
        sensor._bosch_object.get_property.return_value = {
            "value": 12.5,
            "unitOfMeasure": "C",
            "name": "Outside",
        }

        await sensor.async_update()

        assert sensor.native_value == 12.5
        assert sensor.name == "Outside"
        assert sensor.native_unit_of_measurement == "°C"
        assert sensor.extra_state_attributes["stateExtra"] == "fallback"
        assert sensor.extra_state_attributes["path"] == "/sensor1"
        sensor.async_schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [{"invalid": True, "value": 3}, {"value": "invalid"}, {"value": "unavailable"}],
    )
    async def test_update_invalid_values_become_none(self, payload):
        sensor = _base_sensor()
        sensor._bosch_object.get_property.return_value = payload

        await sensor.async_update()

        assert sensor.native_value is None

    @pytest.mark.asyncio
    async def test_update_converts_energy_and_uptime(self):
        energy = _base_sensor(attr_uri="energyConsumption")
        energy._bosch_object.get_property.return_value = {
            "value": 7200,
            "unitOfMeasure": "kJ",
        }
        await energy.async_update()
        assert energy.native_value == 2.0

        uptime = _base_sensor(attr_uri="systemUptime")
        uptime._bosch_object.get_property.return_value = {"value": 3661}
        await uptime.async_update()
        assert uptime.native_value == "1:01:01"
        assert uptime.native_unit_of_measurement is None

        invalid_uptime = _base_sensor(attr_uri="totalSystem")
        invalid_uptime._bosch_object.get_property.return_value = {"value": "bad"}
        await invalid_uptime.async_update()
        assert invalid_uptime.native_value == "bad"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value, expected", [("2026-01-02T03:04:05", True), ("bad", False)])
    async def test_update_parses_timestamp_or_clears_invalid_timestamp(self, value, expected):
        sensor = _base_sensor(attr_uri="startDateTime")
        sensor._bosch_object.get_property.return_value = {"value": value}

        await sensor.async_update()

        assert (sensor.native_value is not None) is expected
        assert sensor.native_unit_of_measurement is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state_class, device_class, expected",
        [("measurement", "temperature", None), ("total", "energy", "fallback")],
    )
    async def test_empty_uninitialized_data_uses_safe_fallback(
        self, state_class, device_class, expected
    ):
        sensor = _base_sensor(
            state_class=state_class,
            device_class=device_class,
            update_initialized=False,
            unit_of_measurement="kWh" if device_class == "energy" else "C",
        )
        sensor._bosch_object.get_property.return_value = {}

        await sensor.async_update()

        assert sensor.native_value == expected
        assert sensor.extra_state_attributes == {"stateExtra": "warming up"}

    def test_attrs_write_updates_units_and_schedule_state(self):
        sensor = _base_sensor()
        sensor.attrs_write({"value": 5}, "°C")

        assert sensor.extra_state_attributes == {"value": 5}
        assert sensor.native_unit_of_measurement == "°C"
        assert sensor._update_init is False
        sensor.async_schedule_update_ha_state.assert_called_once()
        assert sensor.should_poll is False


class TestRecordingSensor:
    def test_statistic_id_derives_from_entity_id(self):
        sensor = _recording()
        sensor._short_id = None
        with patch.object(RecordingSensor, "entity_id", new_callable=PropertyMock) as entity_id:
            entity_id.return_value = "sensor.energy_total"
            assert sensor.statistic_id == "recording:energy_totalexternal"

    def test_temperature_total_recording_is_measurement(self):
        sensor = _recording(device_class="temperature", state_class="total")
        sensor.attrs_write(None)
        assert sensor.state_class == "measurement"
    def test_attrs_write_sets_recording_metadata_and_last_reset(self):
        sensor = _recording()
        reset = datetime(2026, 1, 1, tzinfo=timezone.utc)

        sensor.attrs_write(reset)

        assert sensor.native_unit_of_measurement == "kWh"
        assert sensor.state_class == "total"
        assert sensor.last_reset == reset
        sensor.async_schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_old_gather_uses_previous_full_hour(self):
        now = datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc)
        sensor = _recording()
        sensor._bosch_object.get_property.return_value = {
            "value": [{"d": now.replace(hour=11, minute=0, second=0, microsecond=0), "value": 4.5}]
        }

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor.async_old_gather_update()

        assert sensor.native_value == 4.5

    @pytest.mark.asyncio
    async def test_old_gather_ignores_empty_data_and_missing_hour(self):
        sensor = _recording()
        sensor._bosch_object.get_property.return_value = {"value": []}
        await sensor.async_old_gather_update()
        assert sensor.native_value is None

        sensor._bosch_object.get_property.return_value = {
            "value": [{"d": datetime(2026, 1, 1, tzinfo=timezone.utc)}]
        }
        await sensor.async_old_gather_update()
        assert sensor.native_value is None

    @pytest.mark.asyncio
    async def test_update_selects_new_statistics_api_or_legacy_api(self):
        sensor = _recording(new_stats_api=True)
        sensor._insert_statistics = AsyncMock()
        await sensor.async_update()
        sensor._insert_statistics.assert_awaited_once()

        legacy = _recording(new_stats_api=False)
        legacy.async_old_gather_update = AsyncMock()
        await legacy.async_update()
        legacy.async_old_gather_update.assert_awaited_once()

    def test_append_statistics_skips_zero_and_accumulates_sum(self):
        sensor = _recording()
        now = datetime(2026, 7, 10, tzinfo=timezone.utc)
        stats = [
            {"d": now - timedelta(days=2), "value": 0},
            {"d": now - timedelta(days=1), "value": 2.5},
        ]

        result = sensor.append_statistics(stats, sum=1.0, now=now)

        assert result == 3.5
        assert sensor.native_value == 2.5
        sensor.async_schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_past_statistics_warns_for_today_and_empty_stats(self):
        sensor = _recording()
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        sensor.fetch_past_data = AsyncMock(return_value={})

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor._upsert_past_statistics(now, now + timedelta(hours=1))
            await sensor._upsert_past_statistics(
                now - timedelta(days=2), now - timedelta(days=2) + timedelta(hours=1)
            )

        sensor.fetch_past_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_past_statistics_accepts_old_ranges(self):
        sensor = _recording()
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        sensor.fetch_past_data = AsyncMock(return_value={})

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor._upsert_past_statistics(
                now - timedelta(days=62),
                now - timedelta(days=62) + timedelta(hours=1),
            )

        sensor.fetch_past_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_insert_statistics_fetches_thirty_days_when_database_is_empty(self):
        sensor = _recording(new_stats_api=True)
        sensor.get_last_stat = AsyncMock(return_value={})
        sensor.fetch_past_data = AsyncMock(
            return_value={
                "a": {"d": datetime(2026, 7, 8, tzinfo=timezone.utc), "value": 2.0}
            }
        )
        sensor.append_statistics = MagicMock()
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor._insert_statistics()

        sensor.fetch_past_data.assert_awaited_once()
        sensor.append_statistics.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_statistics_retries_one_day_then_stops_when_empty(self):
        sensor = _recording(new_stats_api=True)
        sensor.get_last_stat = AsyncMock(return_value={})
        sensor.fetch_past_data = AsyncMock(return_value={})

        await sensor._insert_statistics()

        assert sensor.fetch_past_data.await_count == 2

    @pytest.mark.asyncio
    async def test_insert_statistics_uses_recent_database_state(self):
        sensor = _recording(new_stats_api=True)
        sensor.get_last_stat = AsyncMock(
            return_value={sensor.statistic_id: [{"start": 1783728000.0, "state": 1.0, "sum": 4.0}]}
        )
        sensor.get_stats_from_ha_db = AsyncMock(return_value={})
        sensor._bosch_object.state = [
            {"d": datetime(2026, 7, 10, 10, tzinfo=timezone.utc), "value": 2.0}
        ]
        sensor.append_statistics = MagicMock()
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor._insert_statistics()

        sensor.append_statistics.assert_called_once()
        sensor.async_schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_statistics_fetches_missing_old_range(self):
        sensor = _recording(new_stats_api=True)
        old_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
        sensor.get_last_stat = AsyncMock(
            return_value={sensor.statistic_id: [{"start": old_start.timestamp(), "state": 1.0, "sum": 4.0}]}
        )
        sensor.get_stats_from_ha_db = AsyncMock(return_value={})
        sensor.fetch_past_data = AsyncMock(
            return_value={
                "a": {"d": old_start + timedelta(hours=1), "value": 2.0},
                "b": {"d": old_start - timedelta(hours=1), "value": 9.0},
            }
        )
        sensor.append_statistics = MagicMock()
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)

        with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
            await sensor._insert_statistics()

        sensor.fetch_past_data.assert_awaited_once()
        sensor.append_statistics.assert_called_once()


class TestStatisticHelper:
    @pytest.mark.asyncio
    async def test_metadata_should_poll_and_abstract_methods(self):
        helper = DummyStatistic(
            hass=MagicMock(),
            uuid="uuid1",
            bosch_object=_bosch_object(),
            gateway=MagicMock(),
            name="Metric",
            attr_uri="metric",
        )
        helper._attr_name = "Metric"
        helper._unit_of_measurement = "kWh"

        assert helper.should_poll is False
        metadata = helper.statistic_metadata
        assert metadata["statistic_id"] == "dummy:statistic"
        assert metadata["has_sum"] is True
        assert metadata["name"] == "Stats Metric"

        with pytest.raises(NotImplementedError):
            StatisticHelper.statistic_id.__get__(helper)
        with pytest.raises(NotImplementedError):
            # Call the base implementation directly to pin the abstract contract.
            await StatisticHelper._upsert_past_statistics(helper, None, None)

    @pytest.mark.asyncio
    async def test_database_helpers_return_results_and_swallow_errors(self):
        helper = DummyStatistic(
            hass=MagicMock(), uuid="uuid1", bosch_object=_bosch_object(), gateway=MagicMock(), name="Metric", attr_uri="metric"
        )
        instance = MagicMock()
        instance.async_add_executor_job = AsyncMock(return_value={"dummy:statistic": []})
        with patch("custom_components.bosch.sensor.statistic_helper.get_instance", return_value=instance):
            assert await helper.get_last_stat() == {"dummy:statistic": []}
            assert await helper.get_stats_from_ha_db(datetime.now(), datetime.now()) == {"dummy:statistic": []}

        instance.async_add_executor_job.side_effect = RuntimeError("db unavailable")
        with patch("custom_components.bosch.sensor.statistic_helper.get_instance", return_value=instance):
            assert await helper.get_last_stat() == {}
            assert await helper.get_stats_from_ha_db(datetime.now(), datetime.now()) == {}

    def test_add_external_stats_and_find_closest_stat(self):
        helper = DummyStatistic(
            hass=MagicMock(), uuid="uuid1", bosch_object=_bosch_object(), gateway=MagicMock(), name="Metric", attr_uri="metric"
        )
        helper.async_schedule_update_ha_state = MagicMock()
        stats = [{"start": 1, "state": 2.0, "sum": 2.0}, {"start": 2, "state": 3.0, "sum": 5.0}]
        with patch("custom_components.bosch.sensor.statistic_helper.async_add_external_statistics") as add:
            helper.add_external_stats(stats)
        add.assert_called_once()
        assert helper.native_value == 3.0

        helper._unit_of_measurement = "kWh"
        day = datetime(1970, 1, 1, 0, 0, 3, tzinfo=timezone.utc)
        closest = helper.get_last_stats_before_date(
            {helper.statistic_id: [{"start": 0, "state": 1}, {"start": 2, "state": 3}]}, day
        )
        assert closest["start"] == 2

        helper.add_external_stats([])

    @pytest.mark.asyncio
    async def test_move_old_entity_data_updates_statistics_metadata(self):
        helper = DummyStatistic(
            hass=MagicMock(),
            uuid="uuid1",
            bosch_object=_bosch_object(),
            gateway=MagicMock(),
            name="Metric",
            attr_uri="metric",
        )
        helper._entity_id = "sensor.old_metric"
        session = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = session

        with patch(
            "custom_components.bosch.sensor.statistic_helper.session_scope",
            return_value=context,
        ):
            await helper.move_old_entity_data_to_new()

        session.query.assert_called_once()
        session.query.return_value.filter.return_value.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_move_old_entity_data_ignores_integrity_error(self):
        helper = DummyStatistic(
            hass=MagicMock(),
            uuid="uuid1",
            bosch_object=_bosch_object(),
            gateway=MagicMock(),
            name="Metric",
            attr_uri="metric",
        )
        from sqlalchemy.exc import IntegrityError

        error = IntegrityError("already exists", {}, None)
        with patch(
            "custom_components.bosch.sensor.statistic_helper.session_scope",
            side_effect=error,
        ):
            await helper.move_old_entity_data_to_new()

    @pytest.mark.asyncio
    async def test_insert_range_fetches_and_calls_upsert(self):
        helper = DummyStatistic(
            hass=MagicMock(), uuid="uuid1", bosch_object=_bosch_object(), gateway=MagicMock(), name="Metric", attr_uri="metric"
        )
        helper._upsert_past_statistics = AsyncMock()
        start = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        await helper.insert_statistics_range(start)
        helper._upsert_past_statistics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_past_data_normalizes_start_and_delegates(self):
        helper = DummyStatistic(
            hass=MagicMock(), uuid="uuid1", bosch_object=_bosch_object(), gateway=MagicMock(), name="Metric", attr_uri="metric"
        )
        start = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        stop = start + timedelta(days=1)

        assert await helper.fetch_past_data(start, stop) == {}
        helper._bosch_object.fetch_range.assert_awaited_once()
