# Troubleshooting and maintenance

Start with commands that do not expose secrets:

```sh
./bin/token-tracker --help
./bin/token-tracker list
./bin/token-tracker status
```

`list` shows local non-secret configuration. `status` performs real provider
reads and prints snapshots; redact email, account IDs, project IDs, and private
paths before sharing it. Never share `auth.json`, raw keys, managed credential
files, or the private `accounts.json`.

## Codex cannot be found or started

Waybar and GUI applications often have a smaller `PATH` than an interactive
shell. Check the executable and exact supported version from the desktop's
environment. For a nonstandard installation, set `TOKEN_TRACKER_CODEX` to an
absolute executable path in the environment that launches Waybar or the overlay.
The only accepted output is `codex-cli 0.170.0`.

npm launchers also need an executable `node`. The tracker checks absolute desktop
`PATH` entries, the launcher's directory, and standard system bin directories.
Fix the desktop environment, executable permission, Node availability, or pinned
version first; unlinking or reinstalling accounts is not the first remedy because
the error does not imply damaged credentials.

## Keyring unavailable or key missing

Unlock and start the session's Secret Service, then run:

```sh
./bin/token-tracker set-key ACCOUNT_ID
```

Reload the Waybar process after setting a key or unlocking the keyring because
each reporter caches its first lookup result. An inference key cannot replace the
admin key required by the organization cost API.

## ChatGPT identity errors

Missing email, known plan, canonical user ID, or quota workspace/account ID fails
closed. A changed email, plan, user ID, workspace name, workspace ID, or routing
also rejects fresh quota. Confirm the browser identity and relink only when the
change is expected. Duplicate users or workspaces must use the existing link.

Only one tracker login may run at once. If callback port 1455 is occupied, finish
or close the other Codex login window/process and retry. Token Tracker does not
kill it. A failed or cancelled login is not saved and its temporary managed home
is removed.

## Python, GTK, or GI import errors

Always enter through `./bin/token-tracker`. It selects `/usr/bin/python3` so the
Arch `python-gobject` and `gtk3` packages are visible even if your shell currently
uses pyenv or a virtual environment. Installing PyGObject only into a pip/pyenv
environment does not satisfy this launcher. The standalone overlay additionally
needs `gtk-layer-shell`; the Waybar stream itself does not.

## Stale or delayed data

Upstream quota and cost data can lag. Waybar preserves the previous successful
metrics with a **Stale** warning after a failure and waits five minutes before
retrying that account. The overlay uses exponential backoff up to five minutes.
Codex-local is a historical session snapshot by design. Routine successful
observation lines are omitted from the compact Waybar tooltip.

## Waybar shows nothing or does not reload

- Run the quoted absolute `exec` command with `waybar --demo`; verify that a JSON
  line appears immediately and then every five seconds.
- Keep `return-type: json` and omit `interval`. `restart-interval` only handles an
  exited stream.
- Verify both quoted paths, including spaces, and make sure
  `bin/token-tracker` remains executable.
- Merge the property into the existing top-level config and insert the module
  before the real Wi-Fi/network entry without replacing `modules-right`.
- Keep CSS scoped to `#custom-token-tracker`.
- Find the actual process with `pgrep -af '[w]aybar'`, inspect
  `/proc/PID/cmdline`, then send `kill -USR2 PID`. Wrapper executables need not
  have `comm=waybar`.

## Locked-screen and desktop smoke tests

Do not run pointer or screenshot smoke tests while the screen is locked. The
scripts check for `hyprlock`, never unlock the session, and the real-pointer tests
restore the pointer when they can. A lock racing with the test can still abort
cleanup, so run these only on an unlocked, attended desktop. The Waybar desktop
test requires a caller-supplied crop entirely inside the visible tooltip; it must
not capture unrelated desktop content.

## Update

From the clone, review local changes and then fast-forward only:

```sh
git status --short
git pull --ff-only
./bin/token-tracker --help
```

Reload the confirmed Waybar PID as described above. Pulling and reloading do not
remove config, managed ChatGPT homes, or keyring items. If you run the standalone
overlay, use its normal **Quit** button before updating and launch it again after
the update; do not kill it to restart it.

## Uninstall

Before deleting the clone, perform any desired state cleanup while the tracker is
still available: disconnect each ChatGPT connection so the app can coordinate
managed-home cleanup, and remove unwanted API key items with your keyring
manager. Ordinary restarts preserve credentials and do not perform this cleanup.

If the standalone overlay is running, exit through its normal **Quit** button;
do not use a kill command. Remove the module and tracker CSS from your maintained
Waybar files, then reload the confirmed bar PID. You can then delete the clone.
After inspecting and backing up anything wanted, delete only these Token Tracker
directories if you also want the remaining personal state removed:

```text
$XDG_CONFIG_HOME/token-tracker
$XDG_DATA_HOME/token-tracker
```

Their defaults are `~/.config/token-tracker` and
`~/.local/share/token-tracker`. Do not delete a broader XDG directory.

For support, open a [repository issue](https://github.com/magdang/token-tracker/issues)
with redacted errors, your platform, and the Codex version. Never include secrets
or private identifiers. See the [license](../LICENSE).
