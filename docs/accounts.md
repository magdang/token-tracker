# ChatGPT accounts

## Requirements and executable discovery

The ChatGPT integration is tested and deliberately locked to **Codex CLI
0.170.0** (`codex-cli 0.170.0`, distributed as `@openai/codex`). Its strict
configuration and JSON schemas were verified against that version. Newer or
older versions are rejected; there is no arbitrary “latest” compatibility claim.

The tracker searches executable files in absolute `PATH` directories, followed
by `~/.npm-global/bin/codex` and `~/.local/bin/codex`. It does not load shell
startup files. To choose another installation, set `TOKEN_TRACKER_CODEX` to the
absolute executable path in Waybar's or the launcher's environment. An npm
launcher also requires `node`; discovery checks the desktop `PATH`, the
launcher's directory, `/usr/local/bin`, `/usr/bin`, and `/bin`.

Optionally install the pinned version under a tracker-specific user prefix,
without replacing an existing Codex installation. This example is performed by
the user; Token Tracker never installs Codex automatically. It requires Node.js
and npm (Arch packages: `nodejs` and `npm`):

```sh
npm install --prefix "$HOME/.local/share/token-tracker-codex" @openai/codex@0.170.0
export TOKEN_TRACKER_CODEX="$HOME/.local/share/token-tracker-codex/node_modules/.bin/codex"
"$TOKEN_TRACKER_CODEX" --version
```

The verification must print `codex-cli 0.170.0`. Propagate the same variable to
the environment that launches Waybar, or set it in both module commands, using
absolute paths:

```json
{
"exec": "env TOKEN_TRACKER_CODEX='/absolute/path/to/codex' '/absolute/path/to/token-tracker/bin/token-tracker' waybar",
"on-click": "env TOKEN_TRACKER_CODEX='/absolute/path/to/codex' '/absolute/path/to/token-tracker/bin/token-tracker' accounts"
}
```

## Link independent accounts

There is no fixed account count. Repeat the manager or CLI flow for as many
independent accounts as needed, subject to the duplicate guard described below.

```sh
./bin/token-tracker accounts
# or:
./bin/token-tracker connect chatgpt "Personal"
```

Repeat that same `connect` command with a different alias and browser identity
for each additional independent account. `--email` supplies the expected email
without prompting; `--workspace` requires the returned workspace name or
canonical ID to match the supplied value.

The manager asks for an alias, expected email, and optional expected workspace
name or canonical ID. The CLI prompts for omitted expectations. The tracker asks
Codex to start browser OAuth, displays and attempts to open the official sign-in
URL, and leaves browser account selection to you. It never inspects browser
cookies. The manager shows progress and a **Cancel sign-in** button; Ctrl+C
cancels the CLI flow. Finish or cancel one attempt before starting another:
Codex's callback uses port **1455**, and the tracker serializes its own login
attempts.

After browser sign-in, review the exact returned email, plan, canonical user ID,
workspace name (when supplied), and canonical quota workspace/account ID. Saving
requires explicit confirmation: answer `y` to the CLI prompt `Link this exact
user and workspace? [y/N]`, or click **Link this verified user and workspace**
in the GUI. The expected email must match; a supplied workspace expectation must
equal the returned name or canonical ID. If the workspace prompt was left blank,
inspect the returned canonical ID carefully.

A connection fails closed unless official `account/read` and
`account/rateLimits/read` return a known plan, email, canonical `userId`, and
quota `accountId`. Workspace routing, if returned, must agree with that quota ID.
Every refresh rechecks the entire pinned identity, including the initially
reported workspace name. Missing or changed fields reject the new quota; relink
after a legitimate plan or workspace change.

The tracker rejects a repeated user ID **or** workspace/account ID. That avoids
presenting overlapping quota as independent, and intentionally prevents both
multiple workspaces for one person and multiple people in a shared workspace.
Snapshots are not summed.

## Scope and isolation

ChatGPT metrics are coding allowances reported by Codex. OpenCode usage charged
to the same subscription may count in this provider quota. They are not general
ChatGPT website, per-model, or universal subscription limits. Credits are
provider credits, not USD, and backend reporting can lag.

Each link receives a random app-owned directory:

```text
$XDG_DATA_HOME/token-tracker/chatgpt/CONNECTION_ID
```

The default base is `~/.local/share`. Inside it, the tracker creates isolated
`HOME`, `CODEX_HOME`, and XDG directories plus a neutral trusted working
directory. It does not import `~/.codex`, OpenCode state, existing sessions,
instructions, plugins, hooks, MCP servers, apps, cloud skills, or ambient API
environment variables. The generated strict config uses a read-only sandbox,
no approvals, disables those integrations, and passes only a small environment
allowlist. Only initialize and account login/read/logout/rate-limit RPCs are
allowed; no generation or thread RPC is sent.

This path does not require an OpenAI API key or an MCP server.

Codex alone creates, reads, stores, and refreshes credentials in the managed
home. Token Tracker handles structured identity and quota responses but never
opens or copies credential contents. Managed directories are mode 0700 and files
0600. Non-secret verified metadata is stored in `accounts.json` and is visible
through the manager and `list`.

## Disconnect and persistence

Ordinary app, Waybar, or machine restarts preserve connections. Disconnect with
the manager's **Disconnect and delete managed credentials** button or:

```sh
./bin/token-tracker remove CONNECTION_ID
```

For ChatGPT, configuration is removed first and that connection's app-owned home
is then deleted. Active readers are asked to close and cleanup waits up to 20
seconds. If a reader does not release the home, removal still succeeds but the
error reports retained managed state; close tracker readers before manually
deleting only that disconnected ID's directory. Removal behavior for API keys is
different: their keyring entry is retained.

Protocol references for the pinned version:

- [Codex app-server guide](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server/README.md)
- [Account protocol](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server-protocol/src/protocol/v2/account.rs)
- [Configuration schema](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/config.schema.json)
