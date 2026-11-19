# Token Tracker

Token Tracker is a minimalist, local-first `AI` usage button for Waybar; hover it for remaining
allowance bars, precise percentages, and reset countdowns; click it to manage
ChatGPT connections. A continuous JSON stream refreshes every five seconds.

The bars show **remaining** allowance, not usage. The tooltip uses scoped 12pt
text, adapting to 11pt for multiple accounts or more than four metrics. Routine
observation timestamps are omitted to keep it compact; stale results carry an
explicit warning and keep their original snapshot time.

Tested on Arch Linux with Hyprland 0.57.2. Waybar is the recommended surface.
An optional GTK layer-shell overlay is also included.

## Quick start

Install the Waybar path's Arch dependencies:

```sh
sudo pacman -S --needed git waybar python python-gobject gtk3 libsecret
```

`libsecret` supplies `secret-tool`, but API-key storage also needs an unlocked,
running Secret Service such as GNOME Keyring. Install and configure a Secret
Service implementation if your desktop does not already provide one. The
optional standalone overlay additionally needs `gtk-layer-shell`.

Clone to any directory and confirm the executable works:

```sh
git clone https://github.com/magdang/token-tracker.git
cd token-tracker
./bin/token-tracker --help
./bin/token-tracker waybar --demo
```

The launcher deliberately runs `/usr/bin/python3`, the system Python that sees
Arch's PyGObject/Gtk3 packages. There is no pip installation step. Stop the demo
with Ctrl+C; it prints labelled sample JSON and never reads credentials or
writes account configuration.

Next, merge the custom module from [examples/waybar.jsonc](examples/waybar.jsonc)
into your existing Waybar object, quote the real repository path as shown, and
merge [examples/waybar.css](examples/waybar.css) into your stylesheet. Do not
replace `modules-right` or the rest of the bar configuration. Insert
`custom/token-tracker` immediately before the Wi-Fi/network entry that your
configuration actually uses, such as `network`, `network#wifi`, or a custom
network module. See [Waybar deployment](docs/waybar.md) for the safe merge and
reload procedure.

ChatGPT linking requires exactly Codex CLI 0.170.0. Before linking, see
[ChatGPT accounts](docs/accounts.md#requirements-and-executable-discovery) for
version verification and an optional isolated pinned installation that does not
replace an existing Codex.

## Connect accounts

Open the native manager from the button or terminal:

```sh
./bin/token-tracker accounts
```

There is no fixed account count. Each addition asks for an alias and expected
email, optionally an expected workspace name or canonical ID, then opens
user-driven browser OAuth. Complete one login at a time and confirm the exact
returned email, plan, user ID, and workspace/account ID. In the CLI, answer `y`
to `Link this exact user and workspace? [y/N]`; in the GUI, click **Link this
verified user and workspace**. A duplicate user ID or workspace ID is rejected
because its quota could overlap an existing connection.

The terminal equivalent can be repeated as needed:

```sh
./bin/token-tracker connect chatgpt "Personal"
./bin/token-tracker list
./bin/token-tracker status
```

Repeat the same `connect` command with a different alias and browser identity
for each additional independent account. Use `--email` to supply the expected
email without a prompt and `--workspace` to require a returned workspace name or
canonical ID. Full identity, isolation, callback, and cleanup behavior is
documented in [ChatGPT accounts](docs/accounts.md).

Other source types are configured from the CLI. **For ChatGPT, `remove` or GUI
disconnect deletes that connection's managed credentials. Removing an API-key
connection retains its keyring item. Ordinary restarts preserve both kinds of
state.**

```sh
./bin/token-tracker add openai-api "OpenAI API" --budget 30
./bin/token-tracker set-key ACCOUNT_ID
./bin/token-tracker add codex-local "Codex local" --codex-home ~/.codex
./bin/token-tracker add manual "Other subscription"
./bin/token-tracker remove ACCOUNT_ID
```

OpenAI API reporting requires an organization **admin key**, not an inference
key. Budgets are display targets, not credits or enforcement. Codex-local reads
bounded recent session snapshots; manual entries are placeholders. See
[Providers and data scope](docs/providers.md).

## What it reports

- ChatGPT connections expose subscription **coding allowance** reported by the
  Codex account API. OpenCode activity billed to the same subscription may count
  in that provider quota. This is not a universal view of ChatGPT website or
  per-model limits, and credits are not dollar amounts.
- OpenAI API costs use separate API billing. Provider cost and quota data can
  lag; checking every five seconds does not make the upstream data real-time.
- Independent snapshots are never summed. API organization/project scopes can
  overlap, so their totals must not be added together.
- Unknown caps have no bar. Exhausted and over-limit rows keep the used amount.

## Commands and files

`accounts` manages ChatGPT links; `status` fetches snapshots as JSON; `list`
prints configuration without secrets; `add`, `remove`, and `set-key` manage
connections. Run `./bin/token-tracker COMMAND --help` for exact arguments.

Configuration is stored at
`$XDG_CONFIG_HOME/token-tracker/accounts.json` (normally
`~/.config/token-tracker/accounts.json`). App-owned ChatGPT homes are below
`$XDG_DATA_HOME/token-tracker/chatgpt/` (normally
`~/.local/share/token-tracker/chatgpt/`). Codex owns the credentials inside
those managed homes. API keys live in the desktop keyring, not the config.
Ordinary tracker or Waybar restarts preserve all of this state.

Never post `auth.json`, raw keys, managed credential files, or your private
`accounts.json` in an issue. Redact emails, user/workspace IDs, and private paths
from diagnostic output.

## More documentation

- [Waybar deployment and optional overlay](docs/waybar.md)
- [ChatGPT account linking and isolation](docs/accounts.md)
- [Providers and data scope](docs/providers.md)
- [Troubleshooting, updates, and uninstall](docs/troubleshooting.md)
- [Development and safe tests](docs/development.md)
- [Design notes](DESIGN.md)
- [License](LICENSE)

Token Tracker has no installer, service, telemetry, hosted backend, or automatic
configuration migration. It does not modify Hyprland or Waybar configuration for
you.
