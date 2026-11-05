const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup({ hidden = false, reduced = false, preference = null } = {}) {
  const attributes = {},
    classes = new Set(),
    stored = new Map();
  if (preference !== null) stored.set('its_reduce_motion', preference);
  const calls = { requested: 0, cancelled: 0, rendered: 0, disposed: 0 };
  const login = {
    hidden,
    classList: {
      contains: (name) => classes.has(name),
      toggle(name, value) {
        value ? classes.add(name) : classes.delete(name);
      },
      remove(name) {
        classes.delete(name);
      },
    },
  };
  const toggle = {
    setAttribute(k, v) {
      attributes[k] = v;
    },
    removeEventListener() {},
  };
  const host = { getBoundingClientRect: () => ({ width: 500, height: 600 }), replaceChildren() {} };
  const context = vm.createContext({
    document: {
      hidden: false,
      documentElement: { dataset: { theme: 'dark' } },
      body: { classList: { contains: () => reduced } },
      removeEventListener() {},
      querySelector: (id) =>
        ({ '#login-diorama': host, '#login-view': login, '#scene-toggle': toggle })[id],
    },
    window: {
      matchMedia: () => ({ matches: reduced, removeEventListener() {} }),
      removeEventListener() {},
    },
    localStorage: { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, v) },
    requestAnimationFrame: () => ++calls.requested,
    cancelAnimationFrame: (id) => {
      if (id) calls.cancelled++;
    },
    calls,
  });
  const source = fs.readFileSync(path.join(__dirname, '../frontend/web/parking-3d.js'), 'utf8');
  vm.runInContext(source.replace(/\nboot\(\);\s*$/, '\n'), context);
  vm.runInContext(
    `
    renderer={setSize(){},render(){calls.rendered++},dispose(){calls.disposed++}};
    camera={updateProjectionMatrix(){}}; scene={};
    materials=new Set(); geometries=new Set(); flakes={material:{color:{set(){}}}};
  `,
    context,
  );
  return {
    run: (code) => vm.runInContext(code, context),
    calls,
    login,
    stored,
    attributes,
    context,
  };
}

test('3D stops scheduled rendering when the authenticated app hides login', () => {
  const s = setup();
  s.run('sync()');
  assert.equal(s.calls.requested, 1);
  s.login.hidden = true;
  s.run('sync()');
  assert.equal(s.calls.requested, 1);
  assert.equal(s.calls.cancelled, 1);
});
test('reduced motion draws a still scene without an animation loop', () => {
  const s = setup({ reduced: true });
  s.run('sync()');
  assert.equal(s.calls.requested, 0);
  assert.equal(s.calls.rendered, 1);
});
test('2D choice is persisted and cancels pending 3D frames', () => {
  const s = setup();
  s.run('sync(); changeMode()');
  assert.equal(s.stored.get('its_scene_3d'), 'false');
  assert.equal(s.attributes['aria-pressed'], 'false');
  assert.equal(s.calls.cancelled, 1);
  assert.equal(s.calls.requested, 1);
  s.run('changeMode()');
  assert.equal(s.calls.requested, 2);
});
test('hidden browser tabs stop rendering and resume on return', () => {
  const s = setup();
  s.run('sync(); document.hidden=true; sync()');
  assert.equal(s.calls.cancelled, 1);
  assert.equal(s.calls.requested, 1);
  s.run('document.hidden=false; sync()');
  assert.equal(s.calls.requested, 2);
});
test('Halloween illustration stops the hidden 3D renderer and winter resumes it', () => {
  const s = setup();
  s.run('sync(); document.documentElement.dataset.theme="light"; sync()');
  assert.equal(s.calls.requested, 1);
  assert.equal(s.calls.cancelled, 1);
  s.run('document.documentElement.dataset.theme="dark"; sync()');
  assert.equal(s.calls.requested, 2);
});
test('WebGL fallback disposal is idempotent and disables the 3D control', () => {
  const s = setup();
  s.run('sync(); dispose(); dispose(); sync()');
  assert.equal(s.calls.disposed, 1);
  assert.equal(s.calls.requested, 1);
  assert.equal(s.calls.cancelled, 1);
});
test('camera contains the measured model across narrow, wide and short scene cells', () => {
  const s = setup();
  s.run('framing={width:12,height:8,x:.4,y:-1}');
  for (const [width, height] of [
    [280, 180],
    [520, 238],
    [340, 520],
    [680, 400],
    [1920, 600],
  ]) {
    s.run(`host.getBoundingClientRect=()=>({width:${width},height:${height}}); resize()`);
    assert.equal(s.run('camera.left < framing.x-framing.width/2'), true);
    assert.equal(s.run('camera.right > framing.x+framing.width/2'), true);
    assert.equal(s.run('camera.bottom < framing.y-framing.height/2'), true);
    assert.equal(s.run('camera.top > framing.y+framing.height/2'), true);
    const aspect = s.run('(camera.right-camera.left)/(camera.top-camera.bottom)');
    assert.ok(Math.abs(aspect - width / height) < 1e-9);
  }
});
test('animation renders every display frame and travels equally at 60 and 144 Hz', () => {
  for (const hz of [60, 144]) {
    const s = setup();
    s.run('car={position:{},rotation:{}}; flakes.geometry={attributes:{position:{count:0}}}');
    for (let i = 0; i <= hz; i++) s.run(`animate(${(i * 1000) / hz})`);
    assert.equal(s.calls.rendered, hz + 1);
    assert.ok(Math.abs(s.run('elapsed') - 1) < 1e-9);
  }
});
test('resuming after pause does not jump the vehicle animation forward', () => {
  const s = setup();
  s.run(
    'car={position:{},rotation:{}}; flakes.geometry={attributes:{position:{count:0}}}; animate(0); animate(16); stop(); animate(5000)',
  );
  assert.equal(s.run('elapsed'), 0.016);
});

test('Turbo accelerates 3D travel and eases back to normal without resetting the route', () => {
  const s = setup();
  s.run(
    'car={position:{},rotation:{}}; flakes.geometry={attributes:{position:{count:0}}}; animate(0); login.classList.toggle("winter-turbo",true)',
  );
  for (let i = 1; i <= 60; i++) s.run(`animate(${(i * 1000) / 60})`);
  const boosted = s.run('elapsed');
  assert.ok(boosted > 2.5 && boosted < 3);
  s.run('login.classList.remove("winter-turbo")');
  for (let i = 61; i <= 120; i++) s.run(`animate(${(i * 1000) / 60})`);
  assert.ok(s.run('elapsed') > boosted + 1);
  assert.ok(s.run('elapsed') < boosted + 1.4);
  assert.ok(Math.abs(s.run('turboSpeed') - 1) < 0.003);
});
test('six scenery stops form a 180-second journey and only wrap offstage', () => {
  const s = setup();
  assert.equal(s.run('ROUTE_LENGTH/ROAD_SPEED'), 180);
  for (let stop = 0; stop < 6; stop++) {
    assert.equal(s.run(`routeOffset(${stop * 36},${stop * 36})`), 0);
  }
  assert.equal(s.run('routeOffset(0,ROUTE_LENGTH)'), 0);
  let previous = s.run('routeOffset(0,0)');
  for (let i = 1; i <= 1800; i++) {
    const next = s.run(`routeOffset(0,${i}*ROAD_SPEED/10)`);
    if (Math.abs(next - previous) > 1) assert.ok(Math.abs(next) > 30 && Math.abs(previous) > 30);
    previous = next;
  }
});
test('campus route builds finite static batches using the vendored Three.js runtime', async () => {
  const { pathToFileURL } = require('node:url');
  const THREE = await import(
    pathToFileURL(path.join(__dirname, '../frontend/web/vendor/three-0.186.1/three.module.js')).href
  );
  const context = vm.createContext({
    document: {
      createElement: () => ({
        getContext: () => ({
          fillRect() {},
          fillText() {},
          createRadialGradient: () => ({ addColorStop() {} }),
        }),
      }),
    },
  });
  const builder = fs
    .readFileSync(path.join(__dirname, '../frontend/web/uth-route.js'), 'utf8')
    .replace('export function', 'function');
  vm.runInContext(builder + '\nthis.build=buildCampusRoute', context);
  const geometry = new THREE.BoxGeometry(),
    geometries = new Set([geometry]),
    materials = new Set(),
    textures = new Set();
  const mat = (color) => {
    const m = new THREE.MeshBasicMaterial({ color });
    materials.add(m);
    return m;
  };
  const box = (parent, w, h, d, x, y, z, material) => {
    const m = new THREE.Mesh(geometry, material);
    m.scale.set(w, h, d);
    m.position.set(x, y, z);
    parent.add(m);
    return m;
  };
  const route = context.build(THREE, { box, mat, geometry, geometries, materials, textures });
  assert.equal(route.chunks.length, 6);
  route.lighting.update(0, 'dark');
  route.lighting.update(20, 'light');
  let batches = 0;
  for (const { node } of route.chunks) {
    const size = new THREE.Box3().setFromObject(node).getSize(new THREE.Vector3());
    assert.ok([size.x, size.y, size.z].every((v) => Number.isFinite(v) && v > 0));
    node.traverse((mesh) => {
      if (mesh.isInstancedMesh) {
        batches++;
        assert.ok(mesh.count > 0);
        mesh.dispose();
      }
    });
  }
  assert.ok(batches > 6 && batches < 60);
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
  textures.forEach((t) => t.dispose());
});
