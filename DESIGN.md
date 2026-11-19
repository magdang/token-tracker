# Entry points

The recommended entry point is a Waybar custom module. It inherits the bar
style and uses a native GTK hover tooltip, closing on pointer leave. A continuous
JSON reporter updates every five seconds, with four background workers, one
pending request per account, cached keyring lookups, and five-minute error retries.
No separate launcher or panel is started in this mode.

## Optional standalone overlay

Small desktop utility, not a dashboard. The only persistent surface is an
`AI` button. Hover opens a right-aligned usage list; leaving both surfaces
closes it after 180 ms. The short delay allows crossing the gap. Escape
dismisses it; clicking the button or invoking the command supports non-hover use.

- Solid charcoal surface; no blue tint, gradients, glow, or nested cards.
- One system typeface, two sizes, aligned numeric values.
- Account groups separated by one-pixel rules, not containers.
- Thin monochrome bars; amber only for high usage/errors.
- No repeated product slogans, decorative status pills, or fake live states.
- Details and provenance in tooltips; manual/local/stale observations stay visible.
- Demo mode explicitly labelled. No decorative animation.
- Two separate layer-shell surfaces: a collapsed panel cannot intercept clicks.
- Five-second background checks. In-flight requests never overlap for an account;
  errors retry with exponential backoff capped at five minutes.

Reference reviewed: [UI Deslopify](https://github.com/AntonioSpagnol/UI-Deslopify-Skill).
Applied its flat surfaces, purposeful typography, direct copy, and reduced-noise
principles to native GTK. No third-party skill installer or frontend packages used.
