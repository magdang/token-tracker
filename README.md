# Token Tracker

Token Tracker adds an `AI` button to Waybar. Its tooltip shows the **remaining
coding allowance reported by the provider**, including reset countdowns. It is
not a view of every ChatGPT website, message, or per-model limit.

Credentials stay local. Codex owns them inside isolated, app-managed homes;
Token Tracker has no hosted backend or telemetry. This setup is tested on Arch
Linux with Waybar and the system GTK/PyGObject bindings.

## Install

1. Clone the repository and enter it:

   ```sh
   git clone https://github.com/magdang/token-tracker.git
   cd token-tracker
   ```

2. Install the Arch packages (the launcher uses `/usr/bin/python3`, no pip setup):

   ```sh
   sudo pacman -S --needed git waybar python python-gobject gtk3 nodejs npm
   ```

3. Install the supported Codex CLI in an isolated prefix under your home:

   ```sh
   npm install --prefix "$HOME/.local/share/token-tracker-codex" @openai/codex@0.170.0
   export TOKEN_TRACKER_CODEX="$HOME/.local/share/token-tracker-codex/node_modules/.bin/codex"
   "$TOKEN_TRACKER_CODEX" --version
   ```

   ChatGPT linking requires exactly `codex-cli 0.170.0`. This installation
   leaves your existing Codex installation unchanged.

4. Merge [examples/waybar.jsonc](examples/waybar.jsonc) into your existing
   Waybar config and [examples/waybar.css](examples/waybar.css) into its existing
   stylesheet. Preserve the rest of the config and every existing module; do
   not replace `modules-right`. In the copied module, replace **both** quoted
   repository paths and use these commands so Waybar propagates Codex explicitly:

   ```json
   {
     "custom/token-tracker": {
       "exec": "env TOKEN_TRACKER_CODEX='/absolute/path/to/codex' '/absolute/path/to/token-tracker/bin/token-tracker' waybar",
       "on-click": "env TOKEN_TRACKER_CODEX='/absolute/path/to/codex' '/absolute/path/to/token-tracker/bin/token-tracker' accounts",
       "return-type": "json",
       "restart-interval": 5,
       "tooltip": true
     }
   }
   ```

   Replace `/absolute/path/to/codex` with the absolute value printed by
   `printf '%s\n' "$TOKEN_TRACKER_CODEX"`. Keep the inner single quotes so
   paths containing spaces work. Do not add `interval`; this command is a
   continuous JSON stream.

5. Insert `custom/token-tracker` into the existing `modules-right` array before
   your network entry (`network`, `network#wifi`, or your custom module),
   preserving every other entry.

6. Launch the account manager:

   ```sh
   ./bin/token-tracker accounts
   ```

   Enter an account label, the expected ChatGPT email, and optionally the
   expected workspace name or canonical ID. Click **Add ChatGPT account**,
   choose the intended identity in the browser, inspect the returned email,
   plan, user ID, and workspace/account ID, then click **Link this verified user
   and workspace**. Repeat the Add flow with a different browser identity for
   every additional independent account.

7. Reload the existing Waybar only after confirming its PID:

   ```sh
   pgrep -af '[w]aybar'
   tr '\0' ' ' </proc/PID/cmdline
   kill -USR2 PID
   ```

   Replace `PID` with the confirmed existing Waybar PID. `SIGUSR2` reloads
   Waybar by default; check for an `on-sigusr2` override. Do not start a second bar.

[License](LICENSE).
