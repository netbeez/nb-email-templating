# NetBeez Webhook Payloads Reference

Reference for the JSON payloads that the NetBeez platform `POST`s to a
configured webhook endpoint for each supported notification case.

Read this if you are building the **consumer** side of a NetBeez webhook
integration and need to know exactly what shape of JSON to expect.

## Transport

- Method: `POST`
- `Content-Type: application/json`
- Body: a JSON object with a single top-level key, `data`.
- Expected response: any `2xx` status. Non-`2xx` responses are retried by the
  sender.

The envelope follows the JSON:API convention:

- Single events → `data` is an **object**.
- Aggregate events → `data` is an **array** of objects.

Every element inside `data` has the same three top-level keys:

```json
{
  "id":   "…",
  "type": "alert" | "incident",
  "attributes": { … }
}
```

All event-specific fields live inside `attributes`.

## Event catalog

NetBeez supports twelve distinct notification cases, grouped by the entity the
notification is about (`agent`, `target`, `wifi_profile`, `scheduled_test`) and
by the notification type (`device alert`, `alert`, `aggregate alert`, or
`incident`):

- [NetBeez Webhook Payloads Reference](#netbeez-webhook-payloads-reference)
  - [Transport](#transport)
  - [Event catalog](#event-catalog)
  - [Event lifecycle](#event-lifecycle)
    - [Alerts (`"type": "alert"`)](#alerts-type-alert)
    - [Incidents (`"type": "incident"`)](#incidents-type-incident)
  - [Agent device alerts](#agent-device-alerts)
    - [Opening (agent went down)](#opening-agent-went-down)
    - [Cleared (agent came back)](#cleared-agent-came-back)
  - [Agent aggregate alerts](#agent-aggregate-alerts)
  - [Agent incidents](#agent-incidents)
    - [Opened](#opened)
    - [Cleared](#cleared)
  - [Target alerts](#target-alerts)
    - [Opening](#opening)
    - [Cleared](#cleared-1)
  - [Target aggregate alerts](#target-aggregate-alerts)
  - [Target incidents](#target-incidents)
    - [Opened](#opened-1)
    - [Cleared](#cleared-2)
  - [WiFi profile alerts](#wifi-profile-alerts)
    - [Opening](#opening-1)
    - [Cleared](#cleared-3)
  - [WiFi profile aggregate alerts](#wifi-profile-aggregate-alerts)
  - [WiFi profile incidents](#wifi-profile-incidents)
    - [Opened](#opened-2)
    - [Cleared](#cleared-4)
  - [Scheduled test alerts](#scheduled-test-alerts)
    - [Opening](#opening-2)
    - [Cleared](#cleared-5)
  - [Scheduled test aggregate alerts](#scheduled-test-aggregate-alerts)
  - [`test_counts`](#test_counts)
    - [Per-test-type (agent / target / WiFi profile aggregates)](#per-test-type-agent--target--wifi-profile-aggregates)
    - [Flat (scheduled test aggregates)](#flat-scheduled-test-aggregates)
  - [Attribute matrix](#attribute-matrix)
  - [Consumer tips](#consumer-tips)

Each case is toggled independently in the NetBeez notification settings UI.
A single webhook endpoint can receive any combination of the above.

## Event lifecycle

### Alerts (`"type": "alert"`)

Alerts come in pairs: an opening event and a matching clearing event. They
are always the same shape; the only differences are:

| Field           | Opening event              | Clearing event                        |
|-----------------|----------------------------|---------------------------------------|
| `severity`      | `<= 5`                     | `> 5` (typically `6`)                 |
| `severity_name` | `alert`, `critical`, …     | `informational`                       |
| `event_type`    | `"ALERT_OPEN"`             | `"ALERT_CLEARED"`                     |
| `alert_dedup_id`| equals `id`                | equals the opening event's `id`       |

`event_type` is derived from `severity`: `severity <= 5` → `"ALERT_OPEN"`,
otherwise `"ALERT_CLEARED"`.

`alert_dedup_id` lets a consumer correlate the opening and clearing events
for the same underlying condition without tracking pairs of `id`s —
deduplicate / group by `alert_dedup_id`.

### Incidents (`"type": "incident"`)

Incidents also come in pairs: an open event and a cleared event.

| Field        | Open event                           | Cleared event                          |
|--------------|--------------------------------------|----------------------------------------|
| `event`      | `"INCIDENT_OPEN"`                    | `"INCIDENT_CLEARED"`                   |
| `event_ts`   | the moment the incident started      | the moment the incident cleared        |
| `id`         | `"<incident_id>-<start_ts>"`         | `"<incident_id>-<end_ts>"`             |
| `message`    | most recent incident log line        | literal string `"Incident Cleared"`    |
| `incident_id`| same value across both events        | same value across both events          |
| `incident_ts`| start timestamp                      | start timestamp (same value as open)   |

Correlate open / cleared events by `incident_id` (or by the `<incident_id>`
prefix of `id`). `incident_ts` is always the incident's start time, so it is
useful as a stable correlation key as well.

All timestamps (`alert_ts`, `event_ts`, `incident_ts`) are Unix epoch
**milliseconds**.

---

## Agent device alerts

Emitted when an agent itself becomes unreachable (or recovers). `type` is
`"alert"`, envelope `data` is an **object**.

### Opening (agent went down)

```json
{
  "data": {
    "id": "982062",
    "type": "alert",
    "attributes": {
      "severity": 1,
      "severity_name": "alert",
      "alert_dedup_id": 982062,
      "event_type": "ALERT_OPEN",
      "agent": "dummy wired",
      "destination": null,
      "message": "Agent Unreachable",
      "test_type": null,
      "alert_ts": 1774612435626
    }
  }
}
```

### Cleared (agent came back)

```json
{
  "data": {
    "id": "982061",
    "type": "alert",
    "attributes": {
      "severity": 6,
      "severity_name": "informational",
      "alert_dedup_id": 982060,
      "event_type": "ALERT_CLEARED",
      "agent": "dummy wired",
      "destination": null,
      "message": "Agent back online",
      "test_type": null,
      "alert_ts": 1774547861352
    }
  }
}
```

## Agent aggregate alerts

Emitted when the UI requests an aggregated notification for a specific agent
(for example, when a user clicks "notify" from an agent's alert list). `type`
is `"alert"`, envelope `data` is an **array**.

Each element of `data` is an alert from a test the agent is running — for
example the agent's own ping / DNS / HTTP / traceroute / WiFi test failures.
The payload is a snapshot of the test alerts triggered on that agent over a
small recent window, so both opening and clearing events may be present in
the same array.

Agent device alerts (e.g. "Agent Unreachable") are **not** included in an
agent aggregate — they are delivered separately via
[agent device alerts](#agent-device-alerts) and
[agent incidents](#agent-incidents).

Because the envelope is scoped to the agent, every element emits `agent` with
the agent's display name and additionally emits `target`, `destination` and
`test_type` from the underlying test. `wifi_profile` is **not** emitted under
an agent aggregate even if the underlying test targets a WiFi profile — use a
[WiFi profile aggregate](#wifi-profile-aggregate-alerts) if you need that.

Each element also carries a `test_counts` summary; see
[`test_counts`](#test_counts) below for the format.

```json
{
  "data": [
    {
      "id": "974623",
      "type": "alert",
      "attributes": {
        "severity": 1,
        "severity_name": "alert",
        "alert_dedup_id": 974623,
        "event_type": "ALERT_OPEN",
        "agent": "dummy wired",
        "target": "Test target",
        "destination": "test.netbeezcloud.net",
        "message": "DNS server returned no results",
        "test_type": "DnsTest",
        "test_counts": {
          "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 6 },
          "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 3 },
          "3": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 2 },
          "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 },
          "9": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 2 }
        },
        "alert_ts": 1742303320663
      }
    },
    {
      "id": "974701",
      "type": "alert",
      "attributes": {
        "severity": 2,
        "severity_name": "critical",
        "alert_dedup_id": 974701,
        "event_type": "ALERT_OPEN",
        "agent": "dummy wired",
        "target": "Corporate HTTP",
        "destination": "intranet.example.com",
        "message": "HTTP request timed out",
        "test_type": "HttpTest",
        "test_counts": { "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 6 }, "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 3 }, "3": { "success": 0, "fail": 1, "warning": 0, "paused": 0, "unknown": 1 }, "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }, "9": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 2 } },
        "alert_ts": 1742303500112
      }
    },
    {
      "id": "974823",
      "type": "alert",
      "attributes": {
        "severity": 6,
        "severity_name": "informational",
        "alert_dedup_id": 974623,
        "event_type": "ALERT_CLEARED",
        "agent": "dummy wired",
        "target": "Test target",
        "destination": "test.netbeezcloud.net",
        "message": "Target success",
        "test_type": "DnsTest",
        "test_counts": { "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 6 }, "2": { "success": 1, "fail": 0, "warning": 0, "paused": 0, "unknown": 2 }, "3": { "success": 0, "fail": 1, "warning": 0, "paused": 0, "unknown": 1 }, "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }, "9": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 2 } },
        "alert_ts": 1742303620450
      }
    }
  ]
}
```

All three elements are test alerts from tests the agent is running — a DNS
test failure, a concurrent HTTP test failure, and the clearing event for the
DNS test (paired with the first element via `alert_dedup_id`). The `agent`
attribute is the same value on every element.

## Agent incidents

Emitted when an incident is opened or cleared against an agent. `type` is
`"incident"`, envelope `data` is an **object**.

### Opened

```json
{
  "data": {
    "id": "42001-1776360336303",
    "type": "incident",
    "attributes": {
      "incident_id": 42001,
      "event": "INCIDENT_OPEN",
      "event_ts": 1776360336303,
      "agent": "Datacenter Pittsburgh SFO very long name it cannot fit",
      "agent_id": 122,
      "url": "https://example.netbeez.net/#agent-tab/network-agent-view/122",
      "message": "Agent Unreachable",
      "incident_ts": 1776360336303
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "42002-1776360936303",
    "type": "incident",
    "attributes": {
      "incident_id": 42002,
      "event": "INCIDENT_CLEARED",
      "event_ts": 1776360936303,
      "agent": "Datacenter Pittsburgh SFO very long name it cannot fit",
      "agent_id": 122,
      "url": "https://example.netbeez.net/#agent-tab/network-agent-view/122",
      "message": "Incident Cleared",
      "incident_ts": 1776360336303
    }
  }
}
```

Notes:

- `event_ts` reflects the moment the event was emitted (start timestamp for
  open, end timestamp for cleared). `incident_ts` is always the start
  timestamp, so it stays the same across both events.
- The envelope `id` contains both `incident_id` and `event_ts`, so a single
  incident produces two distinct envelope `id`s across its lifecycle. Use
  `incident_id` to correlate open / cleared.
- `message` on a cleared incident is always the literal string
  `"Incident Cleared"`.
- `url` is a deep link back to the incident in the NetBeez UI.

## Target alerts

Emitted when a test targeting a monitored destination fails (or recovers).
`type` is `"alert"`, envelope `data` is an **object**.

### Opening

```json
{
  "data": {
    "id": "974623",
    "type": "alert",
    "attributes": {
      "severity": 1,
      "severity_name": "alert",
      "alert_dedup_id": 974623,
      "event_type": "ALERT_OPEN",
      "agent": "[172.17.0.3-00:03]",
      "target": "Test target",
      "destination": "test.netbeezcloud.net",
      "message": "DNS server returned no results",
      "test_type": "DnsTest",
      "alert_ts": 1742303320663
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "1974623",
    "type": "alert",
    "attributes": {
      "severity": 6,
      "severity_name": "informational",
      "alert_dedup_id": 974623,
      "event_type": "ALERT_CLEARED",
      "agent": "[172.17.0.3-00:03]",
      "target": "Test target",
      "destination": "test.netbeezcloud.net",
      "message": "Target success",
      "test_type": "DnsTest",
      "alert_ts": 1776360936266
    }
  }
}
```

Notes:

- `agent` is the display name of the agent that ran the test. If the agent
  does not have a friendly name configured, a synthesized placeholder such as
  `"[172.17.0.3-00:03]"` appears here.
- `target` is the target's display name as configured in NetBeez.
- `destination` is the actual host / IP the test was attempting to reach.
- `test_type` is the kind of test that produced the alert
  (e.g. `"PingTest"`, `"DnsTest"`, `"HttpTest"`, `"TracerouteTest"`, …).

## Target aggregate alerts

Emitted when the UI requests an aggregated notification for a specific
target. `type` is `"alert"`, envelope `data` is an **array**.

Because the envelope is scoped to a target (not an agent), the `agent`
attribute is **omitted** from each element. Each element carries a
`test_counts` summary; see [`test_counts`](#test_counts) below.

```json
{
  "data": [
    {
      "id": "974623",
      "type": "alert",
      "attributes": {
        "severity": 1,
        "severity_name": "alert",
        "alert_dedup_id": 974623,
        "event_type": "ALERT_OPEN",
        "target": "Test target",
        "destination": "test.netbeezcloud.net",
        "message": "DNS server returned no results",
        "test_type": "DnsTest",
        "test_counts": {
          "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 },
          "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 },
          "3": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 },
          "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 },
          "9": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }
        },
        "alert_ts": 1742303320663
      }
    },
    {
      "id": "1974623",
      "type": "alert",
      "attributes": {
        "severity": 6,
        "severity_name": "informational",
        "alert_dedup_id": 974623,
        "event_type": "ALERT_CLEARED",
        "target": "Test target",
        "destination": "test.netbeezcloud.net",
        "message": "Target success",
        "test_type": "DnsTest",
        "test_counts": { "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 }, "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 }, "3": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 10 }, "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }, "9": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 } },
        "alert_ts": 1776360936266
      }
    }
  ]
}
```

## Target incidents

Emitted when an incident is opened or cleared against a target. `type` is
`"incident"`, envelope `data` is an **object**.

### Opened

```json
{
  "data": {
    "id": "42001-1776360336314",
    "type": "incident",
    "attributes": {
      "incident_id": 42001,
      "event": "INCIDENT_OPEN",
      "event_ts": 1776360336314,
      "target": "Google Workspace",
      "target_id": 1,
      "url": "https://example.netbeez.net/#target-tab/1",
      "message": "Target unreachable",
      "incident_ts": 1776360336314
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "42002-1776360936314",
    "type": "incident",
    "attributes": {
      "incident_id": 42002,
      "event": "INCIDENT_CLEARED",
      "event_ts": 1776360936314,
      "target": "Google Workspace",
      "target_id": 1,
      "url": "https://example.netbeez.net/#target-tab/1",
      "message": "Incident Cleared",
      "incident_ts": 1776360336314
    }
  }
}
```

## WiFi profile alerts

A WiFi profile alert is a test alert whose underlying test runs against a
WiFi profile. When the test also belongs to a target and both toggles are
enabled in NetBeez, the alert is normally routed as a
[target alert](#target-alerts). When explicitly scoped to a WiFi profile,
`agent` is omitted and both `target` and `wifi_profile` are included.

### Opening

```json
{
  "data": {
    "id": "2974623",
    "type": "alert",
    "attributes": {
      "severity": 1,
      "severity_name": "alert",
      "alert_dedup_id": 2974623,
      "event_type": "ALERT_OPEN",
      "target": "Test target",
      "wifi_profile": "dummy-wifi (open)",
      "destination": "test.netbeezcloud.net",
      "message": "WiFi target unreachable",
      "test_type": "DnsTest",
      "alert_ts": 1776360936291
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "2974624",
    "type": "alert",
    "attributes": {
      "severity": 6,
      "severity_name": "informational",
      "alert_dedup_id": 2974623,
      "event_type": "ALERT_CLEARED",
      "target": "Test target",
      "wifi_profile": "dummy-wifi (open)",
      "destination": "test.netbeezcloud.net",
      "message": "WiFi target reachable",
      "test_type": "DnsTest",
      "alert_ts": 1776360936292
    }
  }
}
```

`wifi_profile` is the profile's display name; it includes the encryption
method in parentheses (e.g. `"dummy-wifi (open)"`, `"corp-wifi (wpa2)"`).

## WiFi profile aggregate alerts

Emitted when the UI requests an aggregated notification for a specific WiFi
profile. `type` is `"alert"`, envelope `data` is an **array**.

```json
{
  "data": [
    {
      "id": "2974623",
      "type": "alert",
      "attributes": {
        "severity": 1,
        "severity_name": "alert",
        "alert_dedup_id": 2974623,
        "event_type": "ALERT_OPEN",
        "target": "Test target",
        "wifi_profile": "dummy-wifi (open)",
        "destination": "test.netbeezcloud.net",
        "message": "WiFi target unreachable",
        "test_type": "DnsTest",
        "test_counts": {
          "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 11 },
          "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 6 },
          "3": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 3 },
          "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }
        },
        "alert_ts": 1776360936291
      }
    },
    {
      "id": "2974624",
      "type": "alert",
      "attributes": {
        "severity": 6,
        "severity_name": "informational",
        "alert_dedup_id": 2974623,
        "event_type": "ALERT_CLEARED",
        "target": "Test target",
        "wifi_profile": "dummy-wifi (open)",
        "destination": "test.netbeezcloud.net",
        "message": "WiFi target reachable",
        "test_type": "DnsTest",
        "test_counts": { "1": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 11 }, "2": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 6 }, "3": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 3 }, "4": { "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 } },
        "alert_ts": 1776360936292
      }
    }
  ]
}
```

## WiFi profile incidents

Emitted when an incident is opened or cleared against a WiFi profile. `type`
is `"incident"`, envelope `data` is an **object**.

### Opened

```json
{
  "data": {
    "id": "42001-1776360336315",
    "type": "incident",
    "attributes": {
      "incident_id": 42001,
      "event": "INCIDENT_OPEN",
      "event_ts": 1776360336315,
      "wifi_profile": "dummy-wifi (open)",
      "wifi_profile_id": 1,
      "url": "https://example.netbeez.net/#wifi-tab/1",
      "message": "WiFi profile degraded",
      "incident_ts": 1776360336315
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "42002-1776360936315",
    "type": "incident",
    "attributes": {
      "incident_id": 42002,
      "event": "INCIDENT_CLEARED",
      "event_ts": 1776360936315,
      "wifi_profile": "dummy-wifi (open)",
      "wifi_profile_id": 1,
      "url": "https://example.netbeez.net/#wifi-tab/1",
      "message": "Incident Cleared",
      "incident_ts": 1776360336315
    }
  }
}
```

## Scheduled test alerts

Emitted when a scheduled test (an on-demand or recurring test run that is
not tied to an agent's live test list) fails or recovers. `type` is
`"alert"`, envelope `data` is an **object**.

Scheduled test alerts do **not** include `agent`, `target` or `wifi_profile`
attributes.

### Opening

```json
{
  "data": {
    "id": "3974623",
    "type": "alert",
    "attributes": {
      "severity": 1,
      "severity_name": "alert",
      "alert_dedup_id": 3974623,
      "event_type": "ALERT_OPEN",
      "destination": "Datacenter Pittsburgh (10.0.0.1)",
      "message": "Scheduled test failure",
      "test_type": null,
      "alert_ts": 1776360936299
    }
  }
}
```

### Cleared

```json
{
  "data": {
    "id": "3974624",
    "type": "alert",
    "attributes": {
      "severity": 6,
      "severity_name": "informational",
      "alert_dedup_id": 3974623,
      "event_type": "ALERT_CLEARED",
      "destination": "Datacenter Pittsburgh (10.0.0.1)",
      "message": "Scheduled test recovered",
      "test_type": null,
      "alert_ts": 1776360936299
    }
  }
}
```

Notes:

- `destination` is the scheduled test's target, formatted as
  `"<label> (<host_or_ip>)"` when a label is set, otherwise just the raw host
  or IP. If the scheduled test has no target configured, `destination` is
  an empty string (`""`).
- `test_type` is always `null` for scheduled test alerts.

## Scheduled test aggregate alerts

Emitted when the UI requests an aggregated notification for a scheduled
test. `type` is `"alert"`, envelope `data` is an **array**.

The `test_counts` summary on scheduled test aggregates uses a **flat** key
set (not per-test-type). See [`test_counts`](#test_counts) below.

```json
{
  "data": [
    {
      "id": "3974623",
      "type": "alert",
      "attributes": {
        "severity": 1,
        "severity_name": "alert",
        "alert_dedup_id": 3974623,
        "event_type": "ALERT_OPEN",
        "destination": "",
        "message": "Scheduled test failure",
        "test_type": null,
        "test_counts": {
          "fail": 2,
          "warning": 1,
          "success": 10,
          "unknown": 0,
          "stopped": 0,
          "paused": 0
        },
        "alert_ts": 1776360936299
      }
    },
    {
      "id": "3974624",
      "type": "alert",
      "attributes": {
        "severity": 6,
        "severity_name": "informational",
        "alert_dedup_id": 3974623,
        "event_type": "ALERT_CLEARED",
        "destination": "",
        "message": "Scheduled test recovered",
        "test_type": null,
        "test_counts": {
          "fail": 2,
          "warning": 1,
          "success": 10,
          "unknown": 0,
          "stopped": 0,
          "paused": 0
        },
        "alert_ts": 1776360936299
      }
    }
  ]
}
```

---

## `test_counts`

`test_counts` appears only on aggregate alert elements. It summarises the
count of tests in each state at the time the aggregate was generated.

Two shapes exist depending on the aggregate case:

### Per-test-type (agent / target / WiFi profile aggregates)

Keys are numeric `test_type_id` values encoded as strings. Possible values:

| Key   | Test type       |
|-------|-----------------|
| `"1"` | Ping            |
| `"2"` | DNS             |
| `"3"` | HTTP            |
| `"4"` | Traceroute      |
| `"9"` | Path Analysis   |

Each value is an object of state counters:

```json
{ "success": 0, "fail": 0, "warning": 0, "paused": 0, "unknown": 0 }
```

Which `test_type_id` keys appear depends on which test types exist for that
entity in NetBeez. Do not assume all keys are present — treat absent keys
as "no tests of that type".

### Flat (scheduled test aggregates)

Keys are state names, values are integer counts:

```json
{ "fail": 2, "warning": 1, "success": 10, "unknown": 0, "stopped": 0, "paused": 0 }
```

The full key set is `fail`, `warning`, `success`, `unknown`, `stopped`,
`paused`.

## Attribute matrix

Which alert attributes appear depends on the notification case. `●` =
always, `○` = conditional, `—` = never.

| Attribute                                                                          | Agent device alert | Test alert under agent aggregate | Target alert | WiFi profile alert | Scheduled test alert |
|------------------------------------------------------------------------------------|--------------------|----------------------------------|--------------|--------------------|----------------------|
| `severity`, `severity_name`, `alert_dedup_id`, `event_type`, `message`, `alert_ts` | ●                  | ●                                | ●            | ●                  | ●                    |
| `agent`                                                                            | ●                  | ●                                | ●            | ○ (omitted when scoped to a WiFi profile) | — |
| `agent_description`                                                                | ○ (if set)         | ○                                | ○            | ○                  | —                    |
| `target`                                                                           | —                  | ●                                | ●            | ●                  | —                    |
| `wifi_profile`                                                                     | —                  | —                                | —            | ●                  | —                    |
| `destination`                                                                      | ● (may be `null`)  | ●                                | ●            | ●                  | ● (may be `""`)      |
| `test_type`                                                                        | ● (`null`)         | ●                                | ●            | ●                  | ● (`null`)           |
| `test_counts`                                                                      | ○ (aggregate only) | ○ (aggregate only)               | ○ (aggregate only) | ○ (aggregate only) | ○ (aggregate only, flat shape) |

For incidents:

| Attribute                                                                | Agent incident | Target incident | WiFi profile incident |
|--------------------------------------------------------------------------|----------------|-----------------|-----------------------|
| `incident_id`, `event`, `event_ts`, `url`, `message`, `incident_ts`      | ●              | ●               | ●                     |
| `agent`, `agent_id`                                                      | ●              | —               | —                     |
| `agent_description`                                                      | ○ (if set)     | —               | —                     |
| `target`, `target_id`                                                    | —              | ●               | —                     |
| `wifi_profile`, `wifi_profile_id`                                        | —              | —               | ●                     |

## Consumer tips

- **Deduplicating alerts**: group by `alert_dedup_id`. The opener and closer
  of the same logical condition share it.
- **Correlating incidents**: group by `incident_id`. Do not rely on the
  envelope `id` — it differs between open and cleared events for the same
  incident.
- **Ordering**: events within a single aggregate payload are not guaranteed
  to be ordered. If you need chronological order, sort by `alert_ts`.
- **Optional attributes**: several fields are conditionally present; see the
  matrix above. Consumers should treat missing attributes as "not
  applicable" rather than an error.
- **Timestamps**: all `*_ts` fields are Unix epoch **milliseconds**.
- **Retries**: the sender retries on non-`2xx` responses. Consumers should
  be idempotent — the same event may arrive more than once, identifiable by
  its envelope `id`.
