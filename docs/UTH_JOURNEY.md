# UTH sign-in journey

The user selected Võ Oanh and supplied a facade photograph on 29 October 2026.
That photograph is the visual authority: triangular pediment, four round white
columns, outer pilasters, crimson horizontal louvers, central gold relief panel,
red university name, glass doors, flower pots and broad entrance steps. The model
is an illustrated reconstruction from that single view, not a surveyed replica.
The gold relief is an abstract geometric treatment, not a copy of its fine detail.

An earlier web reference showed a different white/blue entrance; it was replaced
when the user supplied their preferred photograph. The school's official contact
page confirms the Võ Oanh address: https://erp.ut.edu.vn/contactus . No downloaded
campus photograph is embedded in the app.

## Route

Both scenes follow a 180-second cycle with six segments: university facade, park,
riverside/Ba Son bridge, cafe street, tree-lined avenue and bus stop. The surrounding
scenery is illustrative; it does not claim to map the real streets around UTH.
The vehicle stays in view while scenery and road markings pass it, avoiding a
visible reset of the car. Winter and Halloween keep the established palettes.
Snow/leaves, birds, wheels, restrained suspension and night-time headlight beams
provide movement; there is no sound or new external dependency.

The Ba Son segment uses a single curved, tapering pylon and two planes of fan-like
stay cables, replacing the earlier two-post bridge. Both panoramas and the 3D
model include it. The 2D illustration fits one complete landscape into the stage
width, including on wide screens, so the pylon is visible at the segment start.
Visual reference: https://tcdulichtphcm.vn/du-khao/ngam-nhin-bieu-tuong-moi-cua-tphcm-tu-tren-cao-c14a75454.html .

Bridge lighting uses alternating cyan and violet cable strips, deck-edge LEDs,
an emissive pylon, a bounded flood light, soft lamp halos and reflected streaks
on the river. The 3D lights vary gently over about 12 seconds while motion runs;
pausing freezes their intensity without turning them off. Daylight reduces the
halos and flood lighting. The 2D panoramas include matching illuminated lines and
reflections, using one local SVG filter rather than an additional renderer pass.

`Đổi cảnh` advances directly to the next segment in both renderers. The motion
button pauses/resumes and retains the user's choice. Hidden login views and tabs
stop the motion. Reduced motion has a static campus view.

## Files

- `frontend/web/uth-route.js`: campus and five additional procedural scenes;
  static boxes are batched into InstancedMesh objects per material.
- `frontend/web/parking-3d.js`: moving route, clipping to the stage, camera fit,
  lifecycle, textures and resources cleanup, display-paced animation.
- `scripts/build_uth_route.py`: generates the two 7680 × 640 pixel panoramas in
  `frontend/web/assets/uth-route-dark.svg` and `uth-route-light.svg`.
- `frontend/web/parking-3d.css`: shared responsive stage and the 180-second 2D loop.
- `frontend/web/app.js`: synchronized controls and hidden-tab pause for 2D.

## Validation

57 frontend tests passed, including the actual route builder with vendored Three.js,
six-segment timing, offstage wrapping, camera fit, refresh-rate independence,
pause/resume and existing ticket/camera/session/spider behavior. Both generated
SVGs parse successfully. The Impeccable detector reports no findings on the
changed scene CSS and JS.

Browser checks covered 3D campus and river scenes at 1440 × 900, both renderers
in the 794 × 884 app window, and both themes at 390 × 844. The independent table,
ticket, authentication and camera workflows were not changed.
