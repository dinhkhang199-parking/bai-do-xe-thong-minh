# ITS Parking interface refinements

Applied with the Impeccable polish playbook on 2026-10-29.

The existing winter dark and Halloween light themes remain the visual reference.
Keep pixel illustration, the animated car, pumpkin eyes, the password lamp and
the seasonal easter eggs. Operational labels and forms use the existing readable
sans-serif face. No ticket, OCR, camera permission or authentication rules change.

`frontend/web/refinements.css` is the shared final layer for both themes. It owns
readable secondary text, keyboard focus, form borders, touch targets and the
responsive fixes. Seasonal artwork and animation stay in their original files.

The sign-in fields have persistent visible labels. The app offers a keyboard
skip link and names its navigation landmark. Toast messages use a live region.
Short desktop windows keep the sidebar scrollable; mobile controls retain a
44 pixel minimum target and long tables scroll within their own container.

Impeccable is installed globally at `~/.codex/skills/impeccable`. On Codex, use
`$impeccable polish` with a specific component or route. The manual skill install
does not enable an automatic hook. Run its detector explicitly after UI work.
