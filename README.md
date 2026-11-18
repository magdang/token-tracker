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

Running the overlay command again toggles the existing instance. Escape or
Close hides it; Quit exits. It refreshes visible accounts every five minutes
without blocking GTK. No autostart or desktop configuration is changed.

Optional Hyprland binding (replace with the actual absolute repo path):

```ini
bind = SUPER, U, exec, /home/yousef/Projects/repos/usage-tracker/bin/token-tracker overlay
```

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
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q token_tracker
```

Live credentials are not needed by tests. Demo data is explicitly marked and
never written into account configuration. No telemetry or cloud backend.
