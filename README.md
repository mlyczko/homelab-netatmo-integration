# Netatmo Custom Thermostat (mlyczko fork)

![Logo](custom_components/netatmo_custom/logo.png)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

> This is a personal fork of [darksider4all/homelab-netatmo-integration](https://github.com/darksider4all/homelab-netatmo-integration).
> All credit for the original integration goes to [@darksider4all](https://github.com/darksider4all) — thank you for building and
> sharing it! This fork carries preset-mode/icon fixes, Netatmo Connect webhook support with reduced
> API polling, and a Reconfigure flow; see [CHANGELOG.md](CHANGELOG.md) for details.

Custom Home Assistant integration for Netatmo Thermostats with enhanced local polling and webhook support. This integration is designed to replace or work alongside the native Netatmo integration to provide more granular control and faster updates for climate devices.

## Features

- **Fast Updates**: Uses webhooks for near-instant status updates from Netatmo.
- **Detailed Control**: Full support for heating modes including Schedule, Manual, Max, Off, and Frost Guard.
- **Schedule Management**: Dedicated service to switch between Netatmo schedules.
- **Sensors**: Battery levels, wifi signal strength, and firmware information.
- **Resilient**: Automatic token refresh with reauth flow, request retry/backoff, rate-limiting, and graceful degradation to cached data during outages.

## Compatibility

- **Home Assistant**: 2024.1.0 or later.
- **Devices**: Smart Thermostat (NATherm1), Smart Radiator Valve (NRV), Relay (NAPlug), OpenTherm (OTH) and Modulating (OTM) thermostats.
- **No external Python dependencies** — only Home Assistant core libraries are used.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click on "Integrations" -> "Custom repositories" (via the 3-dot menu).
3. Add `https://github.com/mlyczko/homelab-netatmo-integration` as an **Integration**.
4. Click "Install".
5. Restart Home Assistant.
6. Go to Settings -> Devices & Services -> Add Integration -> Search for "Homelab Climate" (or Netatmo Custom).

### Manual Installation

1. Download the latest release.
2. Copy the contents of the repository into your Home Assistant `custom_components/netatmo_custom` directory.
   - Note: You should copy all the internal files (except `.git`, `.github`) into `custom_components/netatmo_custom`.
3. Restart Home Assistant.

## Configuration

1. You need a Netatmo Developer account and an App.
2. Get your Client ID and Client Secret from [dev.netatmo.com](https://dev.netatmo.com/).
3. Add the integration in Home Assistant. It will ask for your credentials or use Home Assistant Cloud linking if configured.
4. **Important**: For webhooks to work, your Home Assistant instance must be accessible from the internet (e.g., via Nabu Casa or a reverse proxy).

### Webhooks

Netatmo plans to lower API rate limits for polling-based integrations on **March 1, 2027** and
recommends its [webhooks](https://dev.netatmo.com/apidocumentation/webhooks) instead. Thermostats
behind a Relay (`NAPlug`, `read_thermostat` scope) are supported.

**Requirements:** Home Assistant reachable from the internet over **HTTPS**, and the integration set
up with your own Netatmo app credentials (the Webhook URI is configured on that app, and requests
are verified with its client secret).

**Setup:**

1. Build your webhook URL: `https://<your-external-HA-URL>/api/webhook/<webhook_id>`.
   The integration logs the full URL at startup. This is an info-level message, so first enable
   **Enable debug logging** from the integration's ⋮ menu, reload the integration, then search
   `Settings -> System -> Logs` for `Webhook URL for dev.netatmo.com`.
2. Paste that URL into the **Webhook URI** field of your app on
   [dev.netatmo.com/apps](https://dev.netatmo.com/apps/) and save.
3. In Home Assistant open `Settings -> Devices & services -> Homelab Climate`, choose
   **Reconfigure** from the ⋮ menu and log in to Netatmo again with the same account. Netatmo only
   links the Webhook URI to your account at login time. Your home, entities and webhook URL are
   kept.

**Verify:**

- Opening the URL in a browser shows `405` / `ERR_INVALID_RESPONSE` — that is normal (webhooks only
  accept `POST`). `curl -i -X POST <url>` from outside your network should return
  `401 Missing signature`, which proves the request reached the integration.
- Change the setpoint in the Netatmo app or on the thermostat itself (not from Home Assistant). The
  climate entity should update within seconds.
- Download diagnostics: `coordinator_health` shows `"webhook_active": true` and
  `"update_interval_seconds": 300`.

### How updates work

| Situation | Behaviour |
|---|---|
| Webhooks not set up | `homestatus` polled every 60 s |
| Webhooks arriving | Each event triggers a refresh (bursts are merged); background poll every 5 min as a safety net |
| No webhook for 1 hour, or `webhook_deletion` received | Falls back to polling every 60 s |
| Home structure (`homesdata`: rooms, modules, schedules) | Cached for 1 hour; re-fetched immediately on `topology_changed` / `home_event_changed` webhooks |
| Repeated API failures | Poll interval backs off up to 15 min |

Changes made from Home Assistant (temperature, HVAC mode, presets) are sent to Netatmo and then
confirmed by re-reading the state after about 5 s, retrying if Netatmo hasn't applied them yet.
Preset changes are shown immediately; other changes appear once confirmed.

Webhook requests without a valid `X-Netatmo-Secret` signature are rejected (`401`/`403`), and events
for other homes on the same Netatmo account are ignored.

## Services

### `netatmo_custom.set_schedule`

Switch the home's heating schedule to a specific named schedule from your Netatmo account.

**Parameters:**
- `entity_id`: The climate entity (e.g., `climate.living_room`)
- `schedule_name`: The exact name of the schedule in your Netatmo app (case-sensitive).

## Triggers and conditions

**Triggers.** This integration does not register any device or event triggers of its
own. To react to Netatmo events in automations, use the standard entity-based triggers
that Home Assistant provides — for example a state trigger on a climate entity
(`climate.living_room`), a sensor entity (`sensor.living_room_battery`), or a binary
sensor entity (`binary_sensor.living_room_boiler`).

**Conditions.** This integration does not register any custom conditions. Use the
built-in Home Assistant conditions (state, numeric state, time, etc.) in your
automations as usual.

## Troubleshooting

- **Webhooks not firing / no fast updates** (`webhook_active: false` in diagnostics):
  - Set an external URL under `Settings → System → Network → Home Assistant URL` (or use Home
    Assistant Cloud).
  - Check the Webhook URI on dev.netatmo.com matches the URL from the logs exactly.
  - Run **Reconfigure** after saving the Webhook URI — Netatmo doesn't link it to existing logins.
  - If you use Cloudflare or another WAF/proxy, make sure `POST /api/webhook/*` isn't challenged or
    blocked (e.g. by Bot Fight Mode); check its security events.
  - Without webhooks the integration still works via 60 s polling, just less promptly.
- **Reconfigure aborts with "configured home was not found"**: you logged in with a different Netatmo
  account than the one used to set up the integration. Log in with the original account.
- **Do not delete and re-add the integration to re-link webhooks**: a new entry gets a new webhook
  ID (and URL). Use **Reconfigure** instead.
- **"Reauthentication needed" notification**: Netatmo periodically invalidates tokens. The integration
  raises a reauth flow automatically — open it and re-link your account; your devices, entities, and
  automations are preserved.
- **Entities show as unavailable**: This happens only after several consecutive update failures (a
  sustained API/network outage). The integration serves cached data first and recovers automatically.
- **Diagnostics**: Download diagnostics from the integration's device page for a redacted snapshot of
  coordinator health (last update, failures, interval, webhook status). Tokens, the webhook ID, home
  and room IDs, home coordinates and device MAC addresses are redacted.

## Removing the integration

1. In Home Assistant, go to **Settings → Devices & Services**.
2. Find the **Homelab Climate** entry in the integrations list.
3. Open the entry, click the three-dot menu (top right), and select **Delete**.
4. The integration unloads its platforms, removes its entities and devices, and
   unregisters its local webhook handler. Deleting the entry does **not** revoke the
   Netatmo app itself — if you also want to stop the app from accessing your Netatmo
   account, remove or disable it under **dev.netatmo.com → your app**.
5. (Optional) To remove the component files entirely, delete the
   `custom_components/netatmo_custom` directory from your Home Assistant
   configuration and restart Home Assistant.

## Development

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, linting,
type-checking, and running the test suite. CI runs `ruff`, `mypy`, `pytest`, `hassfest`, and HACS
validation on every push.

### Quality scale

This integration targets the Home Assistant **Silver** quality tier: config, reauth and reconfigure
flows, unique IDs,
device info, diagnostics with redaction, automatic retry/recovery, and a test suite. Remaining
Gold-tier items (entity-name translations and `repairs.py` issues) are tracked in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT License. See [LICENSE](LICENSE) file for details.
