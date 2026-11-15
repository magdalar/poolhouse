"""Behaviour of the Calendar Toggle: Dispatcher automation blueprint.

Uses a fake calendar entity, so events flow through the real calendar
trigger and calendar.get_events into the handler script.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.const import EVENT_CALL_SERVICE, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockPlatform, mock_platform

from .conftest import HANDLER, HANDLER_RERUN, TARGET, advance, is_on, settle

CALENDAR = "calendar.poolhouse"


class FakeCalendar(CalendarEntity):
    _attr_name = "PoolHouse"

    def __init__(self) -> None:
        self.events: list[CalendarEvent] = []

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self.events if e.end > now]
        return min(upcoming, key=lambda e: e.start, default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self.events if e.start < end_date and e.end > start_date]

    def add(
        self, summary: str, location: str, start: timedelta, end: timedelta
    ) -> None:
        """Add an event, with start/end given relative to now."""
        now = dt_util.now()
        self.events.append(
            CalendarEvent(
                start=now + start, end=now + end, summary=summary, location=location
            )
        )


@pytest.fixture
async def calendar(ha: HomeAssistant) -> AsyncGenerator[FakeCalendar]:
    cal = FakeCalendar()

    async def setup_platform(hass, config, async_add_entities, discovery_info=None):
        async_add_entities([cal])

    mock_platform(ha, "test.calendar", MockPlatform(async_setup_platform=setup_platform))
    assert await async_setup_component(ha, "calendar", {"calendar": {"platform": "test"}})
    await ha.async_block_till_done()
    assert ha.states.get(CALENDAR) is not None
    yield cal
    # Cancel timers that would otherwise outlive the test and fail teardown:
    # the calendar trigger's polling, and the entity's refresh at event end.
    if ha.services.has_service("automation", "turn_off"):
        await ha.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )
    await cal.async_remove()


async def setup_dispatcher(hass: HomeAssistant, handler: str = HANDLER) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "dispatcher",
                "use_blueprint": {
                    "path": "poolhouse/calendar_toggle_dispatcher.yaml",
                    "input": {
                        "calendar": CALENDAR,
                        "handler_script": handler,
                        "startup_delay": 1,
                    },
                },
            }
        },
    )
    await settle(hass)


def count_script_runs(hass: HomeAssistant, script: str) -> list[Event]:
    calls: list[Event] = []

    @callback
    def listener(ev: Event) -> None:
        data = ev.data
        if (data["domain"], data["service"]) == ("script", "turn_on") and script in str(
            data.get("service_data", {}).get("entity_id")
        ):
            calls.append(ev)

    hass.bus.async_listen(EVENT_CALL_SERVICE, listener)
    return calls


async def test_calendar_start_and_end_toggle_target(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    calendar.add("Lights", TARGET, timedelta(minutes=5), timedelta(minutes=10))
    await setup_dispatcher(ha)

    await advance(ha, freezer, timedelta(minutes=4))
    assert not is_on(ha, TARGET)
    await advance(ha, freezer, timedelta(minutes=2))
    assert is_on(ha, TARGET)
    await advance(ha, freezer, timedelta(minutes=5))
    assert not is_on(ha, TARGET)


async def test_startup_recovers_active_event_after_delay(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    calendar.add("Lights", TARGET, timedelta(minutes=-30), timedelta(minutes=30))
    await setup_dispatcher(ha)

    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await settle(ha)
    await advance(ha, freezer, timedelta(seconds=30))
    assert not is_on(ha, TARGET)  # still inside the 1 minute startup delay
    await advance(ha, freezer, timedelta(seconds=60))
    assert is_on(ha, TARGET)


async def test_startup_ignores_events_that_already_ended(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    calendar.add("Lights", TARGET, timedelta(hours=-2), timedelta(hours=-1))
    await setup_dispatcher(ha)

    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await advance(ha, freezer, timedelta(minutes=2))
    assert not is_on(ha, TARGET)


async def test_startup_skips_events_that_started_during_delay(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    # The event's own start trigger handles it; the recovery pass must not
    # dispatch it again. Use a script with rerun enabled so a second dispatch
    # would show up as a second run.
    calendar.add("Flag", "script.set_flag", timedelta(seconds=20), timedelta(minutes=30))
    runs = count_script_runs(ha, "script.set_flag")
    await setup_dispatcher(ha, handler=HANDLER_RERUN)

    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await advance(ha, freezer, timedelta(minutes=2))
    assert len(runs) == 1


async def test_startup_recovery_reruns_script_when_enabled(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    calendar.add("Flag", "script.set_flag", timedelta(minutes=-5), timedelta(minutes=30))
    runs = count_script_runs(ha, "script.set_flag")
    await setup_dispatcher(ha, handler=HANDLER_RERUN)

    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await advance(ha, freezer, timedelta(minutes=2))
    assert len(runs) == 1



async def test_startup_recovery_skips_script_by_default(
    ha: HomeAssistant, calendar: FakeCalendar, freezer: FrozenDateTimeFactory
) -> None:
    # Also proves recovered events reach the handler as 'startup', not 'start'.
    calendar.add("Flag", "script.set_flag", timedelta(minutes=-5), timedelta(minutes=30))
    runs = count_script_runs(ha, "script.set_flag")
    await setup_dispatcher(ha)

    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await advance(ha, freezer, timedelta(minutes=2))
    assert runs == []
