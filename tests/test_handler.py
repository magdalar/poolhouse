"""Behaviour of the Calendar Toggle: Event Handler script blueprint.

Each test calls the handler directly with a fake calendar event, the way the
Dispatcher does, and checks the resulting entity state. See
blueprints/README.md for the behaviour being specified here.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant

from .conftest import (
    FLAG,
    HANDLER_RERUN,
    MOTION,
    TARGET,
    advance,
    event,
    is_on,
    run_handler,
    settle,
)


async def turn(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call(
        "input_boolean", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
    )


async def set_motion(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    state: str,
    ago: timedelta = timedelta(0),
) -> None:
    """Set the motion sensor so that its last_changed is `ago` in the past."""
    now = freezer.time_to_freeze
    freezer.move_to(now - ago)
    hass.states.async_set(MOTION, "on" if state == "off" else "off")  # force a change
    hass.states.async_set(MOTION, state)
    freezer.move_to(now)
    await settle(hass)


# --- Toggleable domains, no wait -------------------------------------------


async def test_plain_toggle_turns_on_at_start(ha: HomeAssistant) -> None:
    await run_handler(ha, "start", event("Lights"))
    assert is_on(ha, TARGET)


async def test_plain_toggle_turns_off_at_end(ha: HomeAssistant) -> None:
    await turn(ha, TARGET, True)
    await run_handler(ha, "end", event("Lights"))
    assert not is_on(ha, TARGET)


async def test_start_prefix_ignores_end(ha: HomeAssistant) -> None:
    await turn(ha, TARGET, True)
    await run_handler(ha, "end", event("Start: Lights"))
    assert is_on(ha, TARGET)


async def test_end_prefix_ignores_start_and_turns_off_at_end(ha: HomeAssistant) -> None:
    await run_handler(ha, "start", event("End: Lights"))
    assert not is_on(ha, TARGET)
    await turn(ha, TARGET, True)
    await run_handler(ha, "end", event("End: Lights"))
    assert not is_on(ha, TARGET)


async def test_summary_whitespace_is_trimmed(ha: HomeAssistant) -> None:
    await turn(ha, TARGET, True)
    await run_handler(ha, "end", event("  Start: Lights  "))
    assert is_on(ha, TARGET)


# --- Scenes / scripts ------------------------------------------------------


async def test_script_runs_at_start(ha: HomeAssistant) -> None:
    await run_handler(ha, "start", event("Flag", location="script.set_flag"))
    assert is_on(ha, FLAG)


async def test_script_with_end_prefix_still_runs_at_start(ha: HomeAssistant) -> None:
    await run_handler(ha, "start", event("End: Flag", location="script.set_flag"))
    assert is_on(ha, FLAG)


async def test_script_ignores_end(ha: HomeAssistant) -> None:
    await run_handler(ha, "end", event("Flag", location="script.set_flag"))
    assert not is_on(ha, FLAG)


async def test_script_not_rerun_on_startup_by_default(ha: HomeAssistant) -> None:
    await run_handler(ha, "startup", event("Flag", location="script.set_flag"))
    assert not is_on(ha, FLAG)


async def test_script_rerun_on_startup_when_enabled(ha: HomeAssistant) -> None:
    await run_handler(
        ha, "startup", event("Flag", location="script.set_flag"), handler=HANDLER_RERUN
    )
    assert is_on(ha, FLAG)


async def test_toggle_recovered_on_startup(ha: HomeAssistant) -> None:
    await run_handler(ha, "startup", event("Lights"))
    assert is_on(ha, TARGET)


# --- Description parsing and waits -----------------------------------------


async def test_shorthand_fires_immediately_when_sensor_on(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "on", ago=timedelta(hours=3))
    await run_handler(ha, "start", event("Lights", description=MOTION))
    assert is_on(ha, TARGET)


async def test_shorthand_lookback_counts_recent_change(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(minutes=30))
    await run_handler(ha, "start", event("Lights", description=MOTION))
    assert is_on(ha, TARGET)


async def test_shorthand_waits_for_motion(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(hours=2))
    await run_handler(ha, "start", event("Lights", description=MOTION))
    assert not is_on(ha, TARGET)

    await advance(ha, freezer, timedelta(minutes=10))
    assert not is_on(ha, TARGET)

    ha.states.async_set(MOTION, "on")
    await settle(ha)
    assert is_on(ha, TARGET)


async def test_plain_toggle_aborts_on_timeout(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(hours=2))
    await run_handler(ha, "start", event("Lights", description=MOTION))
    await advance(ha, freezer, timedelta(hours=1, minutes=1))
    assert not is_on(ha, TARGET)


async def test_start_prefix_forces_on_just_before_end(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(hours=2))
    await run_handler(ha, "start", event("Start: Lights", description=MOTION))

    await advance(ha, freezer, timedelta(minutes=59, seconds=55))
    assert not is_on(ha, TARGET)
    await advance(ha, freezer, timedelta(seconds=3))  # 2s before end
    assert is_on(ha, TARGET)


async def test_script_wait_runs_at_event_end_on_timeout(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(hours=2))
    await run_handler(
        ha, "start", event("Flag", location="script.set_flag", description=MOTION)
    )
    await advance(ha, freezer, timedelta(minutes=59, seconds=30))
    assert not is_on(ha, FLAG)
    await advance(ha, freezer, timedelta(seconds=31))
    assert is_on(ha, FLAG)


async def test_inverted_shorthand_waits_for_five_minutes_clear(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "on")
    await run_handler(ha, "start", event("Lights", description=f"!{MOTION}"))

    ha.states.async_set(MOTION, "off")
    await advance(ha, freezer, timedelta(minutes=4))
    assert not is_on(ha, TARGET)
    await advance(ha, freezer, timedelta(minutes=2))  # minute tick resolution
    assert is_on(ha, TARGET)


async def test_inverted_fires_immediately_if_already_clear(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(minutes=6))
    await run_handler(ha, "start", event("Lights", description=f"!{MOTION}"))
    assert is_on(ha, TARGET)


@pytest.mark.parametrize(
    "description",
    [
        f'wait_entity: {MOTION}\nstate: "off"\nfor_minutes: 10',
        f"wait_entity: '{MOTION}'\nstate: off\nfor_minutes: 10",
        f"# comment line\nWAIT_ENTITY: {MOTION}\n  state:  off  \nfor_minutes: 10",
    ],
    ids=["double-quotes", "single-quotes", "comment-case-spaces"],
)
async def test_key_value_description(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory, description: str
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(minutes=6))
    await run_handler(ha, "start", event("Lights", description=description))
    assert not is_on(ha, TARGET)  # only 6 of 10 minutes clear
    await advance(ha, freezer, timedelta(minutes=5))
    assert is_on(ha, TARGET)


async def test_key_value_within_minutes(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(minutes=30))
    await run_handler(
        ha, "start", event("Lights", description=f"wait_entity: {MOTION}\nwithin_minutes: 15")
    )
    assert not is_on(ha, TARGET)


async def test_end_prefix_with_wait_turns_off_when_clear(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await turn(ha, TARGET, True)
    await set_motion(ha, freezer, "on")
    ev = event("End: Lights", description=f"!{MOTION}")
    await run_handler(ha, "start", ev)
    assert is_on(ha, TARGET)

    ha.states.async_set(MOTION, "off")
    await advance(ha, freezer, timedelta(minutes=6))
    assert not is_on(ha, TARGET)

    # The event's own end trigger is ignored for delayed End: toggles.
    await turn(ha, TARGET, True)
    await run_handler(ha, "end", ev)
    assert is_on(ha, TARGET)


async def test_end_prefix_with_wait_forces_off_at_end(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await turn(ha, TARGET, True)
    await set_motion(ha, freezer, "on")
    await run_handler(ha, "start", event("End: Lights", description=f"!{MOTION}"))
    await advance(ha, freezer, timedelta(minutes=59, seconds=30))
    assert is_on(ha, TARGET)
    await advance(ha, freezer, timedelta(seconds=31))
    assert not is_on(ha, TARGET)


async def test_startup_skips_motion_lookback(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await set_motion(ha, freezer, "off", ago=timedelta(minutes=5))
    await run_handler(ha, "startup", event("Lights", description=MOTION))
    assert not is_on(ha, TARGET)
    ha.states.async_set(MOTION, "on")
    await settle(ha)
    assert is_on(ha, TARGET)


async def test_end_trigger_never_waits(
    ha: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await turn(ha, TARGET, True)
    await set_motion(ha, freezer, "off", ago=timedelta(hours=2))
    await run_handler(ha, "end", event("Lights", description=MOTION))
    assert not is_on(ha, TARGET)


# --- Errors ----------------------------------------------------------------


async def test_unknown_location_logs_error(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await run_handler(ha, "start", event("Bad", location="light.does_not_exist"))
    assert "unknown entity as location" in caplog.text


async def test_unknown_wait_entity_logs_error(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await run_handler(
        ha, "start", event("Lights", description="binary_sensor.does_not_exist")
    )
    assert "unknown wait_entity" in caplog.text
    assert not is_on(ha, TARGET)


async def test_unsupported_domain_logs_error(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await run_handler(ha, "start", event("Sensor", location=MOTION))
    assert "unsupported calendar entry" in caplog.text


async def test_free_text_description_is_ignored(ha: HomeAssistant) -> None:
    await run_handler(ha, "start", event("Lights", description="just a note"))
    assert is_on(ha, TARGET)
