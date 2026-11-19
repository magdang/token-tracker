# Token Tracker

Local-first, multi-account AI usage OSD for Hyprland and other Wayland
compositors supporting layer-shell. Python + GTK3, using packages already
available on the initial development machine.

## Run

On Arch, dependencies are `python`, `python-gobject`, `gtk3`,
`gtk-layer-shell`, and `libsecret` (`secret-tool`, with a running Secret
Service such as GNOME Keyring). No pip dependencies.

```sh
./bin/token-tracker waybar
./bin/token-tracker overlay
./bin/token-tracker overlay --demo
./bin/token-tracker list
./bin/token-tracker status
```

## Waybar (recommended)

Merge [examples/waybar.jsonc](examples/waybar.jsonc) into your existing config,
replacing the executable path. Insert `custom/token-tracker` immediately before
`network` in the existing module list, keeping your other modules. Add
`#custom-token-tracker` to the same CSS rule as `#network` and `#battery`, or
adapt [examples/waybar.css](examples/waybar.css). Back up both files first.

The `AI` entry lives inside Waybar. Hover opens its native GTK tooltip; moving
off closes it, just like Wi-Fi. There is no click requirement or separate popup.
The tooltip is informational and cannot be interacted with. No unsupported
`on-hover` hook is used. Your existing tooltip theme applies.

`./bin/token-tracker waybar` streams one JSON line every **5 seconds**, including
while hidden. Do not set Waybar's `interval`: this is a continuous script.
At most four provider calls run concurrently, with at most one pending request
per account. Reporting stays responsive while calls run. Failures retain stale
data and retry after five minutes. Each API credential is looked up once per
reporter lifetime; after `set-key` or unlocking the keyring, reload Waybar.
Cached keys stay in process memory only. New/reconfigured accounts are picked
up automatically; removed/reconfigured accounts discard old snapshots.

Reload the existing Waybar with `kill -USR2 WAYBAR_PID` (default reload action;
check any `on-sigusr2` override). Do not launch a second bar. See the official
[custom module docs](https://github.com/Alexays/Waybar/wiki/Module:-Custom) and
[signal configuration](https://github.com/Alexays/Waybar/wiki/Configuration).
Stop any previously launched `token-tracker overlay` process to remove its
independent button. No Hyprland config or global package changes are needed.

Use `waybar --demo` instead of `waybar` for explicitly labelled sample accounts.
Real mode shows “No accounts configured” until you add your own connections.
Demo never writes accounts or reads credentials.

## Optional standalone overlay

`overlay` remains available for desktops without Waybar. It starts a floating
`AI` button. Hover opens the panel; leaving button and panel closes it after
180 ms. Escape dismisses it, Quit exits it, and running it again toggles it.
It refreshes every five seconds with per-account overlap protection and error
backoff. Use only one entry point to avoid duplicate launchers. See `DESIGN.md`.

## Connect accounts

Connections are independent, including multiple accounts from one provider.
Use the ID printed by `add` for `set-key` and `remove`.

```sh
./bin/token-tracker add openai-api "OpenAI · Personal" --budget 30
./bin/token-tracker set-key ACCOUNT_ID
# Optional project-scoped cost report:
./bin/token-tracker add openai-api "OpenAI · Work" --project-id proj_example --budget 100

./bin/token-tracker add codex-local "Codex · Personal" --codex-home ~/.codex
./bin/token-tracker add codex-local "Codex · Work" --codex-home ~/.codex-work
./bin/token-tracker add manual "Claude · Personal"
./bin/token-tracker add manual "Gemini · Personal"
./bin/token-tracker remove ACCOUNT_ID
```

### What's real today

- **OpenAI API:** official organization cost reports, paginated, UTC calendar
  month to date. Requires an **admin API key**, not a normal inference key.
  Costs may lag billing. Optional project filter. A budget is a user-defined
  USD target, **not available provider credit** or a spending enforcement mechanism.
  Reports from the same organization can overlap; we deliberately do not sum accounts.
- **Codex local:** quota snapshots from the most recent local session events.
  No login tokens are read. Snapshot timestamps remain visible; opening the
  overlay does not make them live. Uses up to 30 recent session files and the
  last 2 MB of each. Older snapshots may therefore be unavailable. Schema changes
  can break parsing. **Each home must belong to one account**: switching accounts
  within a shared home cannot be attributed reliably.
- **Claude / Gemini / other subscriptions:** manual placeholders for now,
  not automatic integrations. No promise of universal hourly/weekly limits.

Configuration lives at `$XDG_CONFIG_HOME/token-tracker/accounts.json`
(default `~/.config/token-tracker/accounts.json`). Keys go only into the
desktop keyring, never into config, CLI arguments, or the repository.
Removing a connection retains its keyring entry; use your keyring manager
to delete it. `status` prints usage and connection IDs, never keys.

Manual metrics can be entered by editing a manual connection in the config:

```json
{
  "id": "your-existing-id",
  "provider": "manual",
  "name": "Claude · Personal",
  "updated_at": "2026-11-18T12:00:00+00:00",
  "metrics": [
    {"label": "Session", "used": 42, "limit": 100, "unit": "%"}
  ]
}
```

## Development

```sh
export PYTHONPYCACHEPREFIX=/tmp/opencode/pycache TMPDIR=/tmp/opencode
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q token_tracker
./tests/run-smoke.sh --waybar-stream
./tests/run-smoke.sh --synthetic
# On an unlocked Hyprland session (moves/restores the pointer):
./tests/run-smoke.sh
```

Live credentials are not needed by tests. Demo data is explicitly marked and
never written into account configuration. No telemetry or cloud backend.
The real-pointer test additionally needs `wayland-scanner`, a C compiler,
`libwayland-client` headers, and `grim`. It skips if hyprlock is active.
The standalone smoke modes save only a demo-panel image to
`/tmp/opencode/token-tracker-hover.png`, not a full-desktop screenshot.

The installed Waybar can also be checked on an unlocked session with
`./tests/run-smoke.sh --waybar-desktop --tooltip-region 'x,y WxH'`.
Choose a crop inside your tooltip using logical output coordinates. This needs
`at-spi2-core` introspection and `tesseract` for visible-text checks. Add `--demo`
when the module exec is temporarily set to `waybar --demo`; restore real mode
and reload afterward. The test restores the pointer and saves only the supplied
tooltip crop under `/tmp/opencode/token-tracker-waybar-{real,demo}-hover.png`.
