# Providers and data scope

## OpenAI API costs

Create a connection, then store its key through the interactive desktop-keyring
prompt:

```sh
./bin/token-tracker add openai-api "OpenAI API · Organization" --budget 30
./bin/token-tracker set-key ACCOUNT_ID
```

The cost endpoint requires an OpenAI organization **admin API key**. A normal
inference/project key is not sufficient. `set-key` passes the secret to
`secret-tool`; it is not accepted as a CLI argument or written to the config.
The desktop session must have an unlocked Secret Service.

Reports cover the current UTC calendar month and paginate the organization cost
API. Add `--project-id proj_example` to request a project-scoped report. The
`--budget` value is your display target: it is not provider credit, an account
balance, or spending enforcement. Costs may lag. Organization and project
connections can overlap, so Token Tracker deliberately does not sum accounts.

Removing an API connection leaves its Secret Service/keyring item behind. Delete
that item explicitly with your keyring manager if it is no longer wanted.

## Codex-local snapshots

This source does not perform OAuth or read login tokens:

```sh
./bin/token-tracker add codex-local "Codex · Personal" --codex-home ~/.codex
./bin/token-tracker add codex-local "Codex · Work" --codex-home ~/.codex-work
```

It searches up to 30 most-recent JSONL session files and at most the final 2 MB
of each for the newest quota event. Its snapshot time is available in status
JSON, and the standalone overlay shows that timestamp. Waybar labels the local
source but omits routine observation lines. Opening a tooltip does not make it a
live query. Missing events remain unknown rather than becoming 0%. Schema
changes can break parsing.

Use a separate `CODEX_HOME` for each identity. If accounts have been switched
within one home, the snapshot cannot be attributed reliably. This source is
independent of the managed ChatGPT connection homes and is never auto-imported.

## Manual sources

Manual connections are placeholders for providers without an implemented
automatic adapter:

```sh
./bin/token-tracker add manual "Other subscription"
```

To add a metric, edit that existing connection in
`$XDG_CONFIG_HOME/token-tracker/accounts.json` (normally
`~/.config/token-tracker/accounts.json`) while preserving its generated ID:

```json
{
  "id": "your-existing-id",
  "provider": "manual",
  "name": "Other subscription",
  "updated_at": "2026-11-18T12:00:00+00:00",
  "metrics": [
    {"label": "Session", "used": 42, "limit": 100, "unit": "%"}
  ]
}
```

The file itself has a top-level `{"accounts": [...]}` object; the fragment above
is one item in that list. Limits must be finite and positive, and usage must be
finite and nonnegative. Manual data is labelled as manual and makes no claim of
universal provider, website, or model limits.
