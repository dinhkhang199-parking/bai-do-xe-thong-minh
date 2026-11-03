# Halloween login

Reference supplied by the user: https://www.facebook.com/reel/29003757185927269

The Halloween login borrows the reference's plum night palette, illustrated left panel, orange action button, corner pumpkins, hanging lanterns and drifting mist. The illustration and implementation are original assets for ITS Parking. The winter route and dashboard theme remain available.

## Implementation

- `frontend/web/haunted-login.css` scopes the illustrated layout to the Halloween login. It stacks the artwork above the form on phones and supports reduced motion and the existing pause control.
- `frontend/web/index.html` wraps the existing login form with decorative artwork and SVG ornaments. Form IDs and authentication handlers are retained.
- `frontend/web/parking-3d.js` stops the hidden 3D animation while the illustrated Halloween login is active, then resumes it when switching back to winter.
- `frontend/web/password-lamp.css` preserves the lamp button's centering transform during pointer press. The generic active-button transform previously moved it away before click completion.

## Generated illustration

Generated with the built-in imagegen tool. Saved project asset: `frontend/web/assets/haunted-login-v1.png`.

Prompt:

> Use case: stylized-concept. Asset type: left illustration panel for a real Halloween sign-in webpage, not a UI mockup. Create a rich, atmospheric Halloween night illustration in refined 32-bit pixel-painting style. Portrait composition, about 3:4 aspect. Deep aubergine and midnight plum sky, a large warm ivory full moon above a small crooked haunted house in the middle distance, bare tree silhouettes and a few bats, one friendly small pale ghost floating near the house, orange jack-o-lanterns and warm brass lantern light close to the bottom corners, drifting low lavender mist over the path. Strong depth with layered distant mountains, fine stars and warm windows, restrained gold highlights. Dark low-contrast edges that blend into a #171021 plum panel. Full-bleed artwork, no border, no frame, no interface controls, no text, no letters, no logos, no watermark. No cars or roads; this image belongs to the Halloween variant of an existing parking login app.

## Verification

- All 58 frontend tests pass: `node --test tests/test_web_ui.cjs tests/test_spider_ui.cjs tests/test_parking_3d.cjs`.
- Added coverage for stopping hidden Halloween 3D rendering and resuming winter rendering.
- Browser checked at 390 × 844 and 1280 × 720, with no horizontal page overflow.
- Actual password reveal/hide clicks verified, with test text cleared afterward.
- Winter scene switching checked visually. Browser error log empty during verification.
- Impeccable detector returned no findings for the new stylesheet.
