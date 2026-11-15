# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Home Assistant blueprints and scripts for the PoolHouse, written in HA YAML plus Jinja2 templates.

## Testing

```sh
scripts/test.sh                       # yamllint + full pytest suite, in Docker
scripts/test.sh -k startup            # extra args go to pytest
scripts/test.sh tests/test_handler.py::test_plain_toggle_turns_on_at_start
```

The script builds `tests/Dockerfile` (image `poolhouse-tests`) and runs it with the repo mounted read-only. The tests start a real in-process Home Assistant via `pytest-homeassistant-custom-component`. They load the blueprints from `blueprints/`, call the Handler with fake events, and drive the Dispatcher through a fake calendar entity.

- **HA version:** each harness release pins one exact `homeassistant` version, so the HA version is set by `tests/requirements.txt`, and production runs 2026.10.x, moving to 2026.11. To upgrade, pick the harness release on PyPI that pins the target HA, and update the `python:` base image in `tests/Dockerfile` if its `Requires-Python` changed.
- **Use `settle()` and `advance()` from `tests/conftest.py`, not `hass.async_block_till_done()`.** The latter waits for every tracked task, so it hangs forever while a handler run is parked in a `wait_template`. Time is frozen at `T0` and moved with `advance()`, which also fires the minute ticks the "off for N minutes" templates depend on.
- **New behaviour gets a test.** Each README rule is meant to have a test that fails when that rule is broken. Mutation-checking new tests (temporarily break the blueprint, confirm a test fails) has caught gaps here before.

## Layout

- `blueprints/`: the current, maintained code. `blueprints/README.md` is the user-facing spec for the calendar toggle behaviour. Keep it in sync when behaviour changes.
- `blueprints/scripts/play_last_audiobook.yaml`: a standalone script blueprint (Audiobookshelf lookup via `rest_command`, then playback through Music Assistant, with a TTS fallback). It has nothing to do with the calendar toggle.

## Calendar toggle architecture

The calendar toggle is split across two blueprints that must stay consistent with each other:

- **Dispatcher** (`calendar_toggle_dispatcher.yaml`, automation): triggers on the calendar's `start` and `end` and on `homeassistant` `start`. For calendar triggers it forwards `trigger.calendar_event` to the handler script through `script.turn_on` with `variables: {trigger_id, event}`. On startup it waits `startup_delay`, then calls `calendar.get_events` (duration 1s) to find events that are active now. It re-dispatches them with `trigger_id: startup`, skipping any event that started after `startup_ts`, because its own `start` trigger already handled it.
- **Handler** (`calendar_toggle_handler.yaml`, script, `mode: parallel`, `max: 20`): all decision logic for one event. It computes everything up front in a single `variables` block (`act`, `proceed_on_timeout`, `timeout_s`, `is_delayed_end`, and so on), then runs the steps in order: validation `stop`s, an optional `wait_template`, a gate on `wait.completed`, and finally `{{ domain }}.{{ act }}`. Waits run inside the script, so reloading the Dispatcher does not cancel them.

Calendar event fields: **Location** is the target `entity_id`, and the domain is taken from it. **Summary** may carry a case-sensitive `Start:` or `End:` prefix. **Description** sets an optional wait condition. The README's "Timing at the end of the window" table is the source of truth for what happens on timeout. Toggleable `Start:` events and plain toggleable events time out 2s before the event ends, to avoid racing the `end` trigger.

On `startup` the handler ignores the motion lookback, because `last_changed` is reset at boot. It also skips scenes and scripts unless `rerun_scenes_on_startup` is enabled.

## HA template gotchas

- **There is no `from_yaml` filter in HA.** The Description is parsed by a hand-written Jinja loop that splits each line on the first `:` and strips quotes. Any Description containing `:` is treated as key/value lines. Otherwise it is read as `entity_id` or `!entity_id` shorthand.
- Event `start` and `end` can arrive timezone-aware or naive, so they are normalised with `as_datetime(...) | as_local`.
- The unknown-entity checks use `states(x) == 'unknown'`, which also rejects real entities whose state is `unknown` (for example, scenes that have never been activated).
- Service calls use `continue_on_error: true`. A target that is `unavailable` fails silently.
