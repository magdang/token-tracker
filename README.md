# Token Tracker

Local-first, multi-account AI usage OSD for Hyprland and other Wayland
compositors supporting layer-shell. Python + GTK3, using packages already
available on the initial development machine.

## Run

On Arch, dependencies are `python`, `python-gobject`, `gtk3`,
`gtk-layer-shell`, and `libsecret` (`secret-tool`, with a running Secret
Service such as GNOME Keyring). No pip dependencies.

```sh
./bin/token-tracker overlay
./bin/token-tracker overlay --demo
./bin/token-tracker list
./bin/token-tracker status
```

Starts a small `AI` button at the top-right of the compositor's current monitor.
The panel follows the button onto the same output. Hover to open it. Moving
outside both button and panel closes the panel after a 180 ms grace period.
The button remains visible. Click also opens it; Escape dismisses it and Quit
exits the application. Running the command again toggles the panel.

Accounts refresh automatically **every 5 seconds, including while collapsed**,
without blocking GTK. Slow requests never overlap for the same account; errors
back off from 10 seconds up to five minutes. Last successful data is retained
and marked stale when refresh fails. Checking more frequently does not make
provider billing or local snapshots update more frequently.
No autostart or desktop configuration is changed. See `DESIGN.md` for UI decisions.

For an optional shortcut, follow the [official Hyprland documentation](https://wiki.hypr.land/)
for your installed version and use the absolute path to `bin/token-tracker overlay`.

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
./tests/run-smoke.sh --synthetic
# On an unlocked Hyprland session (moves/restores the pointer):
./tests/run-smoke.sh
```

Live credentials are not needed by tests. Demo data is explicitly marked and
never written into account configuration. No telemetry or cloud backend.
The real-pointer test additionally needs `wayland-scanner`, a C compiler,
`libwayland-client` headers, and `grim`. It skips if hyprlock is active.
Both smoke modes save only a demo-panel image to
`/tmp/opencode/token-tracker-hover.png`, not a full-desktop screenshot.
