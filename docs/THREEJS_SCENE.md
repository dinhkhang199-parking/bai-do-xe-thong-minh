# Three.js sign-in scene

The optional decorative pixel SUV scene is in `frontend/web/parking-3d.js`.
The current UTH campus and long route are documented in [UTH_JOURNEY.md](UTH_JOURNEY.md),
including the user's photographic reference and the six-segment 180-second loop.
It uses an orthographic camera, shared box geometry, seasonal materials, one
hemisphere light and one directional light. It contains no live parking data
and does not control cameras, tickets or barriers. A single SUV with roof luggage
sits on a short seasonal road; rolling wheels, road markings and gentle suspension
motion suggest driving without moving the model out of frame.

The scene and sign-in form occupy separate grid cells. At widths up to 960 px,
the scene stacks above the form, including the 794 × 884 in-app browser window.
On desktop they sit side by side. The camera fits the scene's measured bounds
in camera space with 18% breathing room, recalculated for each canvas aspect ratio.
The whole model stays visible instead of being faded behind the form.

Seasonal landscape layers reuse the local still-frame artwork across the login
background, with a pixel moon, distant terrain and trees. Two warm roadside
lanterns, a fence and snow banks fill out the SUV vignette. These layers are
decorative, sit behind the form, and add no motion or network dependencies.

The Cảnh 3D button switches between this scene and the existing pixel artwork.
The preference is stored locally. Unsupported WebGL or a lost context restores
the original 2D scene. Theme changes recolor the scene without rebuilding it.
Rendering stops while the login view or browser tab is hidden. Reduced motion
uses a still frame. Animation follows the display's animation-frame cadence;
elapsed-time movement stays consistent across refresh rates, with a 50 ms delta
cap after stalls. Wheels track road speed and suspension motion is restrained.
Pixel ratio is capped at 1.5.
Geometry, materials and renderer are disposed when leaving the page.

Three.js 0.186.1 is vendored locally with its MIT license. The package tarball's
SHA-512 integrity was verified against npm metadata. There are no runtime CDN
imports or new build steps. Source: https://www.npmjs.com/package/three/v/0.186.1

Installed authoring skills: https://github.com/full-stack-skills/threejs-skills
Applied scene, renderer, orthographic camera and lighting guidance.

The login has its own motion button synchronized with the dashboard control;
a saved pause can be resumed without signing in. The preference is retained
after reload. Global snow falls only while motion is enabled.

Validation: 57 frontend regressions passed, including 10 scene tests. Browser
checks covered 794 × 884, 1440 × 900, 390 × 844 and 320 × 640; both themes and
2D/3D switching were inspected. Tests cover reduced motion, hidden login/tab,
disposal and camera containment across narrow, wide and short scene cells.
The Impeccable mechanical detector was run; it cannot resolve this backend's
root-relative `/static/` URLs from disk, so its missing-styles / flat-type warning
was checked against the live HTTP page instead.
