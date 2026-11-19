# Waybar deployment

## Merge the module

Back up your Waybar config and stylesheet, then edit the copies you normally
maintain. Token Tracker never edits live desktop configuration.

1. Copy only the `custom/token-tracker` property from
   [the example](../examples/waybar.jsonc) into the existing top-level Waybar
   object. Replace the example with the clone's absolute path. Keep the single
   quotes inside the JSON string so paths containing spaces work.
2. In the existing `modules-right` list, insert `custom/token-tracker`
   immediately before the entry that actually provides Wi-Fi/network status.
   That entry may be `network`, an instance such as `network#wifi`, or a custom
   module. Preserve every other module and all bar settings.
3. Merge the tracker-scoped [CSS example](../examples/waybar.css) into the
   existing stylesheet. It does not change other tooltip or module styles.

The command streams one `return-type: json` object every five seconds. Do not
configure Waybar's `interval`; that would treat the stream as a one-shot command.
The optional `restart-interval` in the example only restarts an exited stream.
Clicking runs the account manager. Hovering uses Waybar's native GTK tooltip, so
there is no `on-hover` command and no independent popup process.

## Check before reload

Run the exact absolute command from `exec` in a terminal first:

```sh
'/absolute/path with spaces/token-tracker/bin/token-tracker' waybar --demo
```

Each line must be valid JSON containing `AI DEMO`. Stop it with Ctrl+C. Then use
your Waybar JSON/JSONC validation workflow if you have one.

Waybar process names can be wrappers such as `waybar-lua-workspace-fix`, so do
not assume `comm` is exactly `waybar`. Locate candidates and inspect the full
command line before signalling anything:

```sh
pgrep -af '[w]aybar'
tr '\0' ' ' </proc/PID/cmdline; printf '\n'
kill -USR2 PID
```

Replace `PID` only after confirming that `/proc/PID/cmdline` is the existing bar
you intend to reload. `SIGUSR2` is Waybar's default reload signal; check whether
your configuration overrides `on-sigusr2`. Do not start a second bar.

## Display behavior

The `AI` button remains native to Waybar. Its 20-segment monochrome bars are
filled by remaining allowance and floor the visual fill to 5% steps; the nearby
number is more precise. Reported window durations become readable labels and
reset times become countdowns. With multiple accounts or more than four metrics,
compact 11pt layout removes spacer lines and puts countdowns beside bars;
otherwise it uses 12pt. These font choices are embedded only in this module's
tooltip markup. Account aliases appear in the tooltip; verified identity details
remain available in the account manager and `list` output.

Hover itself never starts provider work. Up to four collectors run concurrently,
with at most one request pending per account. Successful sources are checked on
the five-second loop. Waybar failures retain prior metrics as explicitly stale
and retry after five minutes. API keys are looked up once per reporter process,
so reload Waybar after `set-key` or after unlocking the keyring. Account additions,
removals, and other configuration changes are noticed without restarting.

## Optional standalone overlay

The overlay is for desktops where the Waybar module is unsuitable:

```sh
sudo pacman -S --needed gtk-layer-shell
./bin/token-tracker overlay --demo
./bin/token-tracker overlay
```

It creates its own layer-shell `AI` button and interactive panel. Hover opens the
panel, leaving both surfaces closes it after 180 ms, Escape dismisses it, and
Quit exits it. A second invocation toggles the existing application. It checks
every five seconds with per-account overlap protection and exponential error
backoff capped at five minutes. Use either this overlay or the Waybar button to
avoid duplicate launchers.
