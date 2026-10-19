# Calendar Toggle Automation

This automation uses the **`Calendar Toggle`** calendar as a flexible scheduler for Home Assistant entities. It supports immediate "dumb" triggers, lifecycle-bound toggles, and occupancy/state-gated execution bounded by the calendar event's time window.

It comes in two pieces:

  - Dispatcher: the Automation that triggers from calender events.
  - Handler: the actual handler for calendar events, triggered from the Dispatcher. This allows re-triggering during Home Assistant startups.

---

## Calendar Event Field Mapping

Every calendar entry uses three standard fields to control what happens and when:

| Calendar Field | Required | Purpose | Example |
| :--- | :---: | :--- | :--- |
| **Summary (Title)** | Yes | Human-readable label and optional lifecycle prefix (`Start:` or `End:`). | `Start: Morning Music` |
| **Location** | Yes | The exact Home Assistant `entity_id` to control. | `script.morning_music_wake_up` |
| **Description** | No | Optional sensor/entity gating condition (shorthand `entity_id` or YAML dictionary). | `binary_sensor.upstairs_stairwell_motion` |

---

## Supported Domains & Lifecycle Prefixes

### 1. One-Off Domains (`scene`, `script`)
* Scenes and scripts only execute an activation (`turn_on`).
* They are always evaluated at the **start** of the calendar event—even if the summary begins with `End:` (e.g., `End: Evening Lights` triggering `scene.evening_lights_off`).
* If a `Description` wait condition is configured, the calendar event's **Start-to-End duration** acts as the waiting window.

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
  * **With Description (`wait_entity`):** Begins watching the sensor at event **start**, turns the entity `off` as soon as the condition is met, or forces it `off` at event **end**.

---

## Sensor-Gated Delays (`Description` Field)

Leave the **Description** blank for immediate execution. To delay an event until a secondary condition is met (bounded by the end of the calendar event), use either **Shorthand** or **YAML** in the Description.

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
| `state` | `'on'` | All | Target state to wait for (`'on'` or `'off'`). |
| `within_minutes` | `60` | `state: 'on'` | Triggers immediately at event start if `wait_entity` changed within this many minutes prior to event start. |
| `since` | *(none)* | `state: 'on'` | Overrides `within_minutes` with a fixed time string (`"HH:MM:SS"`, e.g., `"05:00:00"`). |
| `for_minutes` | `5` (when `off`) | `state: 'off'` | Requires `wait_entity` to stay `'off'` continuously for this many minutes before firing. |

---

## Examples

### Example 1: Morning Wake-Up Music (Wait for Motion, Fallback to Event End)
You want morning music to play at 6:05 AM if someone is already awake, or wait until someone walks down the stairs, with a hard upper limit of 6:45 AM.
* **Time:** `6:05 AM – 6:45 AM`
* **Summary:** `Start: Morning Music`
* **Location:** `script.morning_music_wake_up`
* **Description:**
  ```text
  binary_sensor.upstairs_stairwell_motion
  ```
* **Result:** At 6:05 AM, if stairwell motion occurred between 5:05 AM and 6:05 AM, the music starts immediately. If not, it waits until motion is detected. If no motion occurs by 6:45 AM, the music starts anyway.

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
You want your evening lights scene to turn off starting at 10:30 PM, but delay turning off if people are still active in the room—up to a hard cutoff of 11:30 PM.
* **Time:** `10:30 PM – 11:30 PM`
* **Summary:** `End: Evening Lights`
* **Location:** `scene.evening_lights_off`
* **Description:**
  ```yaml
  wait_entity: binary_sensor.living_room_motion
  state: "off"
  for_minutes: 10
  ```
* **Result:** At 10:30 PM, if the living room has already been clear for 10+ minutes, `scene.evening_lights_off` activates immediately. Otherwise, it waits until 10 minutes of continuous inactivity passes, or forces the lights off at 11:30 PM.

---

## Limitations & Edge Cases

1. **Home Assistant Restarts Reset `last_changed`:**
   * Home Assistant resets `states[entity].last_changed` to the boot timestamp whenever HA restarts or reloads an integration.
   * *Impact:* If HA restarts at 5:45 AM, a 6:05 AM event checking `within_minutes: 60` will see `last_changed` as `5:45 AM` and trigger immediately at 6:05 AM. Conversely, an running `wait_template` in progress will be cancelled if HA restarts mid-window.
2. **1-Minute Resolution on `for_minutes` Duration Checks:**
   * When waiting for `state: 'off'` with `for_minutes > 0`, Home Assistant re-evaluates `(now() - last_changed)` on entity state changes and once every 60 seconds on the minute tick. The action may fire up to ~59 seconds after the exact `for_minutes` threshold is crossed.
3. **Rich-Text / HTML Formatting in Calendar Descriptions:**
   * Some calendar clients (like Google Calendar web UI) automatically inject HTML tags (`<br>`, `<a href="...">`) into the Description field if you paste text or links. Always paste plain text into the Description so `from_yaml` and entity parsing do not fail.
4. **Concurrency Limit (`max: 20`):**
   * Because delayed events hold open a running execution slot inside `mode: parallel`, up to 20 events can wait or execute simultaneously. If more than 20 calendar events overlap at the exact same time, additional triggers will be dropped and logged by Home Assistant.
5. **Single `wait_entity` Per Event:**
   * Each calendar entry supports monitoring one `wait_entity` in its Description. To gate an event on multiple motion sensors simultaneously, create a Home Assistant **Group Binary Sensor Helper** combining those sensors and reference the group's `entity_id` in the calendar Description.
