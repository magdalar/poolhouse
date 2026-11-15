"""Shared fixtures: a real Home Assistant instance with the repo's blueprints."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import async_fire_time_changed

REPO = Path(__file__).resolve().parent.parent
BLUEPRINTS = REPO / "blueprints"

# Fixed, timezone-aware start time so tests don't depend on the wall clock.
T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=dt_util.UTC)

TARGET = "input_boolean.target"
FLAG = "input_boolean.flag"  # Set by script.set_flag, to observe script runs.
MOTION = "binary_sensor.motion"
HANDLER = "script.handler"
HANDLER_RERUN = "script.handler_rerun"


@pytest.fixture
async def ha(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> HomeAssistant:
    """Home Assistant with both handler variants, helpers and a fake sensor."""
    freezer.move_to(T0)

    hass.config.config_dir = str(tmp_path)
    shutil.copy(
        BLUEPRINTS / "calendar_toggle_handler.yaml",
        _mkdir(tmp_path / "blueprints/script/poolhouse"),
    )
    shutil.copy(
        BLUEPRINTS / "calendar_toggle_dispatcher.yaml",
        _mkdir(tmp_path / "blueprints/automation/poolhouse"),
    )

    assert await async_setup_component(hass, "system_log", {})
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"target": {}, "flag": {}}}
    )
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "handler": _use_handler(rerun=False),
                "handler_rerun": _use_handler(rerun=True),
                "set_flag": {
                    "sequence": [
                        {"action": "input_boolean.turn_on", "target": {"entity_id": FLAG}}
                    ]
                },
            }
        },
    )
    # A plain state is enough for the handler's wait templates.
    hass.states.async_set(MOTION, "off")
    await hass.async_block_till_done()
    return hass


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _use_handler(rerun: bool) -> dict:
    return {
        "use_blueprint": {
            "path": "poolhouse/calendar_toggle_handler.yaml",
            "input": {"rerun_scenes_on_startup": rerun},
        }
    }


def event(
    summary: str,
    location: str = TARGET,
    description: str = "",
    start: datetime | None = None,
    duration: timedelta = timedelta(hours=1),
) -> dict:
    """A calendar event dict shaped like trigger.calendar_event."""
    start = start or dt_util.utcnow()
    return {
        "summary": summary,
        "location": location,
        "description": description,
        "start": dt_util.as_local(start).isoformat(),
        "end": dt_util.as_local(start + duration).isoformat(),
        "all_day": False,
    }


async def settle(hass: HomeAssistant) -> None:
    """Let pending callbacks and service calls run.

    hass.async_block_till_done() would hang here: it waits for every tracked
    task, including handler runs parked in a wait_template.
    """
    for _ in range(50):
        await asyncio.sleep(0)


async def run_handler(
    hass: HomeAssistant, trigger_id: str, ev: dict, handler: str = HANDLER
) -> None:
    """Start the handler script (non-blocking, like the Dispatcher does)."""
    await hass.services.async_call(
        "script",
        "turn_on",
        {"entity_id": handler, "variables": {"trigger_id": trigger_id, "event": ev}},
        blocking=True,
    )
    await settle(hass)


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    """Move the clock forward, firing timers and minute ticks on the way."""
    step = timedelta(seconds=30)
    while delta > timedelta(0):
        jump = min(step, delta)
        freezer.tick(jump)
        async_fire_time_changed(hass)
        await settle(hass)
        delta -= jump


def is_on(hass: HomeAssistant, entity_id: str) -> bool:
    return hass.states.get(entity_id).state == "on"
