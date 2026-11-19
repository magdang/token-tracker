# Token Tracker

Local-first, multi-account AI usage OSD for Hyprland and other Wayland
compositors supporting layer-shell. Python + GTK3, using packages already
available on the initial development machine.

## Run

On Arch, dependencies are `python`, `python-gobject`, `gtk3`,
`gtk-layer-shell`, and `libsecret` (`secret-tool`, with a running Secret
Service such as GNOME Keyring). No pip dependencies.

```sh
./bin/token-tracker accounts
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
off closes it, just like Wi-Fi. Clicking AI opens the native account manager.
The tooltip is informational and cannot be interacted with. No unsupported
`on-hover` hook is used. The tracker scopes **14pt body text and bold 16pt
remaining values** to its own Pango tooltip; other tooltips keep their theme.
Each 20-segment monochrome bar fills with **remaining allowance**, rounded down
to 5% steps. The adjacent number is more precise. Window labels follow reported
durations, with reset countdowns and observation age. Manual, local and stale
sources remain explicit; failed refreshes retain their original observation time.
Unknown caps have no bar. Dollar amounts show a user-defined budget, never
provider credit; uncapped credits stay credit balances. Exhausted/over-limit
rows retain the used amount. Aliases identify accounts here; verified identity
details remain available in the account manager.

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
Use the ID printed by `add` or `connect` for `set-key` and `remove`.

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

### Link three ChatGPT subscription accounts

Use **Codex CLI 0.170.0** (npm package `@openai/codex`). The tracker searches
absolute PATH directories, then `~/.npm-global/bin/codex` and `~/.local/bin/codex`,
so desktop launchers need not inherit your terminal PATH. For a custom install,
set `TOKEN_TRACKER_CODEX` to its absolute executable path in the tracker's launch
environment. npm launchers also need Node.js; the tracker checks PATH, the
launcher's directory, and standard system bin directories for `node`. It never
loads shell startup files. Existing working installations need no upgrade.
This integration was
verified against that installed version's generated JSON schemas, not inferred
from latest-main documentation. No MCP dependency or API key is needed.

Click **AI → Add ChatGPT account** (or run `./bin/token-tracker accounts`). Enter
`Account 1` and its expected ChatGPT email. Optionally enter the expected workspace
name or canonical workspace ID. Click **Add ChatGPT account**, complete browser
sign-in, then review the returned email, plan, canonical **user ID** and
**workspace/account ID**. Click **Link this verified user and workspace** only
when they match. Repeat with `Account 2` and `Account 3`, using the corresponding
email and browser identity each time. The manager does not select browser accounts
or inspect cookies. Use the browser's account switcher yourself. It displays the
sign-in URL, success/error state, and a **Cancel sign-in** button.

The equivalent terminal flow, **one at a time**, is:

```sh
./bin/token-tracker connect chatgpt "Account 1"
./bin/token-tracker connect chatgpt "Account 2"
./bin/token-tracker connect chatgpt "Account 3"
./bin/token-tracker list
./bin/token-tracker status
```

Each command prompts for the expected email and optional workspace, opens and
prints the sign-in URL, and asks you to confirm the verified identity with `y`.
`--email` and `--workspace` can supply those expectations instead of prompting.
Ctrl+C cancels. Do not paste tokens anywhere. Only user-invoked Add/connect starts
OAuth; polling, opening the manager, and tests never start real sign-in. Finish
or cancel one login before starting another: Codex uses callback port **1455**.
If another Codex app owns the port, finish/close its login window and retry; the
tracker never kills other Codex processes.

A connection is saved only after official `account/read` and
`account/rateLimits/read` expose email, known plan, canonical `userId`, and quota
`accountId`. The alias is only a label. The user ID identifies the person; the
quota account ID identifies the selected workspace/account. Both IDs are required:
if a server/backend omits either, linking fails closed. A workspace display name
alone cannot prove exact attribution. If you leave the workspace expectation
blank, explicitly review its canonical ID in the confirmation. The stable
0.170.0 schema does not expose workspace routing in `account/read`; the tracker
does not enable experimental APIs to obtain it. If that field is supplied, its
workspace ID must agree with the quota account ID.

Every refresh rechecks the pinned email, plan, user ID, workspace ID and initially
reported workspace name. Missing or changed pinned fields reject new quota; a plan
or workspace change requires disconnecting and linking again. Duplicate user IDs
**or** workspace IDs are rejected conservatively to avoid representing overlapping
quota as independent accounts. This also deliberately prevents linking two
workspaces for one person, or multiple people in a shared workspace. Account
snapshots are never added together. Previous verified data may remain explicitly
**stale** after a failed refresh, with its observation time and error visible.
There is no fallback to another signed-in app, API key, or local session snapshot.

Each connection has a random, app-owned home below
`$XDG_DATA_HOME/token-tracker/chatgpt/ID` (default
`~/.local/share/token-tracker/chatgpt/ID`). Its `codex/` directory is its own
`CODEX_HOME`; isolated HOME/XDG paths and a neutral trusted working directory
prevent use of your normal Codex/OpenCode config, instructions, plugins or MCP
servers. The tracker uses supported strict config: read-only sandbox, no
approvals, disabled plugins/hooks/apps/cloud skills, and an inherited-environment
allowlist. It sends only initialize/initialized and account RPCs, never threads,
turns, generation, PTY scraping, private quota endpoints, or raw credential APIs.
The child has a restrictive umask; managed directories are 0700 and files 0600.
Codex alone writes, reads and refreshes its credentials. The tracker never reads,
copies, extracts or logs credential contents. Nonsecret verified metadata lives
in the accounts config and is visible in the local manager, tooltip and `list`.

Successful checks reuse one app-server per identity, with at most four parallel
collector jobs and one job per account. RPCs time out after 15 seconds each;
failed providers back off independently. Waybar retries after five minutes; the
optional overlay uses exponential backoff up to five minutes. Config changes
invalidate pending results and close obsolete children; exit reaps owned children.
Use `remove ID` or the manager's **Disconnect and delete managed credentials** to
remove a ChatGPT link. Running readers release their home on the next refresh;
cleanup waits up to 20 seconds. If readers cannot stop in time, the connection is
removed but an explicit error reports retained managed state. Close tracker
readers before deleting that disconnected ID's managed directory. Other providers'
keyring entries retain their existing removal behavior.

**Scope:** This is the subscription's **coding quota**, including usage that
OpenCode bills to the same ChatGPT plan. It does not expose the ChatGPT website's
per-model message limits. Primary/secondary durations follow the reported minutes, formatted as whole
hours/days when exact, across all returned buckets. Missing usage is unknown, not 0%; a
reported 0% remains 0%. Credit balances are credits, **not USD**. Provider data can
lag, and five-second polling does not guarantee the backend updates that often.

Protocol sources: the official [app-server guide](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server/README.md),
[account protocol](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server-protocol/src/protocol/v2/account.rs),
and [config schema](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/config.schema.json)
for 0.170.0, plus the installed `codex app-server generate-json-schema` output.
[OpenCode's ChatGPT provider documentation](https://opencode.ai/docs/providers#chatgpt)
describes subscription billing; OpenAI API keys use separate API billing.
[CodexBar](https://github.com/steipete/CodexBar/blob/main/docs/codex.md),
[codex-status-mcp](https://github.com/DrSmile444/codex-status-mcp), and
[chatgpt-quota-mcp](https://github.com/komaksym/chatgpt-quota-mcp) are related quota
implementations; they are not runtime dependencies or protocol authorities here.

### What's real today

- **ChatGPT subscription:** directly linked, verified coding quota via the official
  Codex account API. See the three-account sign-in steps and attribution limits above.
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
Removing an API connection retains its keyring entry; use your keyring manager
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
/usr/bin/python3 tests/render_waybar_demo.py
./tests/run-smoke.sh --synthetic
/usr/bin/python3 tests/smoke_accounts.py
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
