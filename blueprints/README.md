# Calendar Toggle Automation

This automation uses a Home Assistant calendar as a flexible scheduler for entities. It supports immediate "dumb" triggers, lifecycle-bound toggles, and occupancy/state-gated execution bounded by the calendar event's time window. It also recovers after Home Assistant restarts.

It comes in two blueprints:

  - **Dispatcher** (automation blueprint): triggers on calendar event start and end, and on Home Assistant startup, and hands each event to the Handler.
  - **Handler** (script blueprint): the actual logic for one calendar event. Keeping it in a separate script lets the Dispatcher re-trigger active events after a Home Assistant restart, and lets multiple events run (and wait) independently.

---

## Setup

1. Copy the blueprints into your config directory:
   * `calendar_toggle_handler.yaml` → `config/blueprints/script/<folder>/`
   * `calendar_toggle_dispatcher.yaml` → `config/blueprints/automation/<folder>/`
   * Reload blueprints or restart Home Assistant.
2. **Create the Handler first.** Settings → Automations & Scenes → Blueprints → *Calendar Toggle: Event Handler* → Create script.
   * `rerun_scenes_on_startup` (default off): see [Home Assistant Restarts](#home-assistant-restarts).
3. **Create the Dispatcher.** *Calendar Toggle: Dispatcher* → Create automation, and set:
   * **Calendar:** the calendar you will create events in.
   * **Handler script:** the script from step 2.
   * **Startup delay** (default 1 minute): extra wait after Home Assistant's start event before recovering active events. Home Assistant only fires that event once startup has finished, so the delay just gives slower devices (Zigbee, Z-Wave, cloud integrations) time to reconnect. Raise it if your targets are still `unavailable` at that point; `0` recovers immediately.

---

## Calendar Event Field Mapping

Every calendar entry uses three standard fields to control what happens and when:

| Calendar Field | Required | Purpose | Example |
| :--- | :---: | :--- | :--- |
| **Summary (Title)** | Yes | Human-readable label and optional lifecycle prefix (`Start:` or `End:`). | `Start: Porch Light` |
| **Location** | Yes | The exact Home Assistant `entity_id` to control. | `script.morning_music_wake_up` |
| **Description** | No | Optional sensor/entity gating condition (shorthand `entity_id` or YAML dictionary). | `binary_sensor.upstairs_stairwell_motion` |

Notes:

* Prefix matching is case-sensitive and requires the colon (`Start:` / `End:`). Leading and trailing whitespace in the Summary is ignored.
* The domain is taken from the Location (the part before the first `.`).

---

## Supported Domains & Lifecycle Prefixes

### 1. One-Off Domains (`scene`, `script`)
* Scenes and scripts only execute an activation (`turn_on`).
* They are always evaluated at the **start** of the calendar event, even if the summary begins with `End:` (e.g., `End: Evening Lights` triggering `scene.evening_lights_off`).
* The `Start:` and `End:` prefixes have no effect on scenes and scripts.
* If a `Description` wait condition is configured, the calendar event's **Start-to-End duration** acts as the waiting window. If the window expires without the condition being met, the scene or script is activated anyway, at event end.

### 2. Toggleable Domains (`light`, `switch`, `fan`, `input_boolean`)
By default, toggleable entities turn **on** when the calendar event starts and turn **off** when the calendar event ends. You can override this behavior by prefixing the **Summary**:

* **No Prefix** (e.g., `Kitchen Lights`):
  * **Event Start:** Turns entity `on` (or waits for motion during the window; if the window expires with no motion, it aborts turning `on`).
  * **Event End:** Turns entity `off`.
* **`Start:` Prefix** (e.g., `Start: Porch Light`):
  * **Event Start:** Turns entity `on` (if gated by a sensor, waits up to the end of the event, then forces `on` at timeout).
  * **Event End:** Ignored (does not turn `off`).
* **`End:` Prefix** (e.g., `End: Patio Fan`):
  * **Without Description:** Ignores event start; turns entity `off` at event end.
  * **With Description (`wait_entity`):** Begins watching the sensor at event **start**, turns the entity `off` as soon as the condition is met, or forces it `off` at event **end**. The `end` trigger itself is then ignored.

### Timing at the end of the window

| Event type | If the wait times out |
| :--- | :--- |
| Scene / script | Activates at event end |
| `End:` toggleable with a wait | Turns `off` at event end |
| `Start:` toggleable with a wait | Turns `on` 2 seconds **before** event end |
| Plain toggleable with a wait | Aborts (never turns on); the event end then turns it `off` |

The 2-second margin avoids racing the event's own `end` trigger.

---

## Sensor-Gated Delays (`Description` Field)

Leave the **Description** blank for immediate execution. To delay an event until a secondary condition is met (bounded by the end of the calendar event), use either **Shorthand** or **YAML** in the Description.

> **Parsing rule:** if the Description contains a `:`, it is parsed as YAML. Otherwise it is treated as shorthand, which must be a single entity id with no spaces. Free-text notes such as `Remember: check sensor` will therefore be misparsed. Keep descriptions to the forms below.

### Option A: Shorthand Syntax
1. **Wait for Motion / Active State (`entity_id`)**
   ```text
   binary_sensor.upstairs_stairwell_motion
   ```
   * **Behavior:** Fires immediately at event start if the sensor is currently `'on'` **or** has changed state within the **last 60 minutes**. Otherwise, waits for the sensor to turn `'on'`, or times out at the end of the calendar event.
2. **Wait for Inactivity / Inverted State (`!entity_id`)**
   ```text
   !binary_sensor.living_room_motion
   ```
   * **Behavior:** Fires immediately at event start if the sensor is currently `'off'` and has remained `'off'` for at least **5 minutes**. Otherwise, waits until the sensor has been `'off'` for 5 continuous minutes, or forces execution at the end of the calendar event.

### Option B: YAML Syntax
For custom lookback windows, specific cutoff times, or custom inactivity durations, provide valid YAML in the Description:

| Parameter | Default | Applies To | Description |
| :--- | :--- | :--- | :--- |
| `wait_entity` | *(required)* | All | The `entity_id` to monitor (e.g., `binary_sensor.motion`). |
| `state` | `'on'` | All | Target state to wait for. **Must be quoted: `"on"` or `"off"`.** Unquoted `off` is parsed by YAML as boolean `false` and will not work. |
| `within_minutes` | `60` | `state: "on"` | Triggers immediately at event start if `wait_entity` changed state within this many minutes prior to event start. |
| `since` | *(none)* | `state: "on"` | Overrides `within_minutes` with a fixed time string (`"HH:MM:SS"`, e.g., `"05:00:00"`), interpreted as that time **today**. |
| `for_minutes` | `5` (when `off`) | `state: "off"` | Requires `wait_entity` to stay `'off'` continuously for this many minutes before firing. |

---

## Examples

### Example 1: Morning Wake-Up Music (Wait for Motion, Fallback to Event End)
You want morning music to play at 6:05 AM if someone is already awake, or wait until someone walks down the stairs, with a hard upper limit of 6:45 AM.
* **Time:** `6:05 AM – 6:45 AM`
* **Summary:** `Morning Music`
* **Location:** `script.morning_music_wake_up`
* **Description:**
  ```text
  binary_sensor.upstairs_stairwell_motion
  ```
* **Result:** At 6:05 AM, if the stairwell sensor changed state between 5:05 AM and 6:05 AM, the music starts immediately. If not, it waits until motion is detected. If no motion occurs by 6:45 AM, the music starts anyway.

### Example 2: Windowed Room Light (Turn On with Motion, Skip if Empty)
You want the office light to turn on between 7:00 AM and 9:00 AM only if someone enters, and turn off at 9:00 AM.
* **Time:** `7:00 AM – 9:00 AM`
* **Summary:** `Office Light`
* **Location:** `light.office`
* **Description:**
  ```text
  binary_sensor.office_motion
  ```
* **Result:** Waits for motion starting at 7:00 AM (including a 60-minute lookback to 6:00 AM). If nobody enters the office by 9:00 AM, the `turn_on` action aborts so the light never flashes on at the end of the slot.

### Example 3: Evening Lights Wind-Down (Inverted Condition / Wait for No Motion)
You want your evening lights scene to activate starting at 10:30 PM, but delay it if people are still active in the room, up to a hard cutoff of 11:30 PM.
* **Time:** `10:30 PM – 11:30 PM`
* **Summary:** `End: Evening Lights`
* **Location:** `scene.evening_lights_off`
* **Description:**
  ```yaml
  wait_entity: binary_sensor.living_room_motion
  state: "off"
  for_minutes: 10
  ```
* **Result:** At 10:30 PM, if the living room has already been clear for 10+ minutes, `scene.evening_lights_off` activates immediately. Otherwise, it waits until 10 minutes of continuous inactivity passes, or activates at 11:30 PM regardless.

---

## Home Assistant Restarts

After a restart, the Dispatcher waits the configured **startup delay** (default 1 minute) after Home Assistant's start event, which itself fires only once startup has finished. It then re-dispatches every event that is active at that moment, so entities end up in the state the calendar says they should be in.

* **Motion lookback is skipped on startup.** A restart resets every entity's `last_changed`, which would make nearly every sensor look recently active. For recovered events, only the sensor's current state counts: a sensor that is `on` satisfies the wait, one that was merely active recently does not. "Off for N minutes" waits are unaffected in effect, but they are counted from boot, so after a restart a default 5-minute inactivity wait takes about 5 minutes to be satisfied.
* **Scenes and scripts are not re-run** for still-active events, unless `rerun_scenes_on_startup` is enabled on the Handler.
* **Waits in progress are lost on restart, then recovered.** A recovered event restarts its wait from the beginning.
* **Events that start or end during the startup delay** are handled by their normal triggers. The recovery step skips events that started after Home Assistant did, so nothing is handled twice.
* **Events that ended while Home Assistant was down are not cleaned up.** A light turned on by an event that ended during the outage stays on.

---

## Troubleshooting

* **Traces:** the Dispatcher's trace shows what was dispatched. The Handler script's trace shows the decisions (`act`, `timeout_s`, `wait_entity`, `is_delayed_end`, `proceed_on_timeout`) and what was called.
* **Logs:** configuration errors (unknown Location entity, unknown `wait_entity`, unsupported domain) are written to Settings → System → Logs.
* **Testing without the calendar:** call the Handler directly, pointing the Location at a throwaway `input_boolean`:
  ```yaml
  action: script.turn_on
  target:
    entity_id: script.calendar_toggle_handler   # your Handler's entity id
  data:
    variables:
      trigger_id: start          # also: end, startup
      event:
        summary: "Start: Test"
        location: input_boolean.test_poolhouse
        description: "!binary_sensor.your_motion_sensor"
        start: "2026-10-19 18:00:00"   # use the format your calendar returns
        end: "2026-10-19 19:00:00"     # keep this in the future
  ```
  To see the real event format, run `calendar.get_events` for your calendar in Developer Tools → Actions.
* **Nothing happened and no error:** if the target entity is `unavailable`, the action silently does nothing (errors are suppressed with `continue_on_error`).

---

## Limitations & Edge Cases

1. **1-Minute Resolution on `for_minutes` Duration Checks:**
   * When waiting for `state: "off"` with `for_minutes > 0`, Home Assistant re-evaluates `(now() - last_changed)` on entity state changes and once every 60 seconds on the minute tick. The action may fire up to ~59 seconds after the exact `for_minutes` threshold is crossed.
2. **Lookback Counts Any State Change:**
   * The default "motion within the last 60 minutes" check looks at when the sensor last *changed state* in either direction. A sensor that turned `on` and then `off` 20 minutes ago still satisfies it.
3. **`since` Is Anchored to Today:**
   * `since: "HH:MM:SS"` resolves to that time on the current day. For events that cross midnight, it may resolve to the wrong day.
4. **Unknown-State Entities Are Rejected:**
   * The Location (and `wait_entity`) is checked with `states(entity) == 'unknown'`, which also matches real entities whose state is `unknown`. Scenes report `unknown` until first activated, so a brand-new scene may be rejected with an "unknown entity" error. Activate it once manually.
5. **All-Day Events and Timezones:**
   * The handler converts event times to local time and has been written to handle both timezone-aware and naive timestamps, but all-day events have not been tested. Check one with the test call above before relying on them.
6. **Rich-Text / HTML Formatting in Calendar Descriptions:**
   * Some calendar clients (like Google Calendar web UI) automatically inject HTML tags (`<br>`, `<a href="...">`) into the Description field if you paste text or links. Always paste plain text into the Description so `from_yaml` and entity parsing do not fail.
7. **Concurrency Limit (`max: 20`):**
   * Delayed events hold open a running execution slot in the Handler script (`mode: parallel`), so up to 20 events can wait or execute simultaneously. If more than 20 events overlap at the same time, additional runs are dropped and logged by Home Assistant against the script.
8. **Reloading Does Not Cancel Waits:**
   * Because the work runs in the Handler script, reloading or disabling the Dispatcher does not cancel in-flight waits. Restart Home Assistant or stop the script to cancel them.
9. **Single `wait_entity` Per Event:**
   * Each calendar entry supports monitoring one `wait_entity` in its Description. To gate an event on multiple motion sensors simultaneously, create a Home Assistant **Group Binary Sensor Helper** combining those sensors and reference the group's `entity_id` in the calendar Description.
