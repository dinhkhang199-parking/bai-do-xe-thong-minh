/* A local, decorative Three.js scene. Ticket and camera workflows stay in app.js. */
const host = document.querySelector('#login-diorama');
const login = document.querySelector('#login-view');
const toggle = document.querySelector('#scene-toggle');
const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
let renderer, scene, camera, world, car, flakes, materials, geometries, textures;
let bridgeLighting;
let framing = { width: 15, height: 10, x: 0, y: 0 };
const rollingWheels = [], roadMarks = [];
const routeItems = [], routeBirds = [], routeFlags = [];
const headlights = [];
const ROUTE_LENGTH = 216, ROAD_SPEED = 1.2;
function routeOffset(at, travel) { return ((at - travel + ROUTE_LENGTH/2) % ROUTE_LENGTH + ROUTE_LENGTH) % ROUTE_LENGTH - ROUTE_LENGTH/2; }
function updateRoute(travel) {
  bridgeLighting?.update(elapsed,theme);
  routeItems.forEach(({node,at}) => {
    node.position.x = routeOffset(at,travel);
    node.visible = Math.abs(node.position.x) < 30;
  });
  routeFlags.forEach((flag,i) => { flag.rotation.y=.15*Math.sin(elapsed*2+i); });
  routeBirds.forEach(({node,wings,phase}) => {
    node.position.set(routeOffset(phase*12,travel*.4),5.7+.2*Math.sin(elapsed+phase),-4.5);
    wings[0].rotation.z=.35*Math.sin(elapsed*4+phase); wings[1].rotation.z=-wings[0].rotation.z;
  });
}
let enabled = true, dead = false, frame = 0, last = null, elapsed = 0, theme = '', turboSpeed = 1;
let observer, resizeObserver;
const stored = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
const paused = () => document.body.classList.contains('motion-paused') ||
  (stored('its_reduce_motion') !== 'false' && motion.matches);

function stop() { cancelAnimationFrame(frame); frame = 0; last = null; }
function nextScenery(event) {
  const stage=Number(event.detail);
  if(!Number.isInteger(stage)||stage<0||stage>5||dead) return;
  elapsed=stage*30; updateRoute(elapsed*ROAD_SPEED); sync();
}
function dispose() {
  if (dead) return;
  dead = true; stop(); observer?.disconnect(); resizeObserver?.disconnect();
  document.removeEventListener('visibilitychange', sync);
  motion.removeEventListener('change', sync);
  window.removeEventListener('pageshow', sync);
  window.removeEventListener('its:journey-next',nextScenery);
  toggle.removeEventListener('click', changeMode);
  geometries?.forEach(g => g.dispose());
  materials?.forEach(m => m.dispose());
  textures?.forEach(t => t.dispose());
  world?.traverse(mesh=>{if(mesh.isInstancedMesh) mesh.dispose();});
  renderer?.dispose();
  host.replaceChildren(); login.classList.remove('scene-3d-active'); toggle.hidden = true;
}
function changeMode() {
  enabled = !enabled;
  try { localStorage.setItem('its_scene_3d', String(enabled)); } catch (_) { /* Session-only preference. */ }
  sync();
}
function resize() {
  if (dead) return;
  const { width, height } = host.getBoundingClientRect();
  if (!width || !height) return;
  renderer.setSize(width, height, false);
  const aspect = width / height;
  // Fit the actual model in its own layout column, including a motion margin.
  const span = Math.max(framing.height, framing.width / aspect) * 1.18;
  camera.left = framing.x - span * aspect / 2; camera.right = framing.x + span * aspect / 2;
  camera.top = framing.y + span / 2; camera.bottom = framing.y - span / 2;
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
}
function sync() {
  if (dead || !renderer) return;
  const nextTheme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  if (nextTheme !== theme) {
    theme = nextTheme;
    materials.forEach(m => {
      if (m.userData.seasons) m.color.set(m.userData.seasons[theme]);
    });
    flakes.material.color.set(theme === 'light' ? '#e8a45c' : '#c5edff');
    headlights.forEach(beam=>{beam.visible=theme==='dark';});
    bridgeLighting?.update(elapsed,theme);
  }
  login.classList.toggle('scene-3d-active', enabled && nextTheme !== 'light');
  toggle.setAttribute('aria-pressed', String(enabled));
  toggle.title = enabled ? 'Chuyển về cảnh pixel 2D' : 'Xem xe pixel 3D';
  stop();
  if (!enabled || nextTheme === 'light' || login.hidden || document.hidden) return;
  resize();
  if (!paused()) frame = requestAnimationFrame(animate);
}
function animate(now) {
  if (dead) return;
  frame = requestAnimationFrame(animate);
  // Follow every display frame; the old 30 fps threshold produced uneven skips.
  const dt = last === null ? 0 : Math.min((now - last) / 1000, 0.05);
  const targetSpeed = login.classList.contains('winter-turbo') ? 3 : 1;
  turboSpeed += (targetSpeed - turboSpeed) * (1 - Math.exp(-dt * 7));
  elapsed += dt * turboSpeed;
  last = now;
  const travel = elapsed * ROAD_SPEED;
  car.position.y = 0.014 * Math.sin(elapsed * 3.5);
  car.rotation.z = 0.002 * Math.sin(elapsed * 2.1);
  rollingWheels.forEach(wheel => { wheel.rotation.z = -travel / 0.47; });
  roadMarks.forEach((mark, i) => { mark.position.x = ((i * 2.8 - travel) % 22.4 + 22.4) % 22.4 - 11.2; });
  updateRoute(travel);
  const positions = flakes.geometry.attributes.position;
  for (let i = 0; i < positions.count; i++) {
    positions.setY(i, 0.5 + ((i * 0.37 - elapsed * 0.45) % 7 + 7) % 7);
  }
  positions.needsUpdate = true;
  renderer.render(scene, camera);
}

async function boot() {
  if (!host || !login || !toggle) return;
  try {
    const THREE = await import('./vendor/three-0.186.1/three.module.js');
    const {buildCampusRoute} = await import('./uth-route.js?v=4');
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    renderer.localClippingEnabled = true;
    host.append(renderer.domElement);
    renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); dispose(); });
    scene = new THREE.Scene(); world = new THREE.Group(); scene.add(world);
    camera = new THREE.OrthographicCamera(-12, 12, 12, -12, 0.1, 100);
    camera.position.set(8, 9, 24); camera.lookAt(0, 1.6, 0);
    scene.add(new THREE.HemisphereLight(0xd6efff, 0x344365, 2.5));
    const sun = new THREE.DirectionalLight(0xffedce, 3);
    sun.position.set(-5, 12, 5); scene.add(sun);
    materials = new Set(); geometries = new Set(); textures = new Set();
    const geometry = new THREE.BoxGeometry(1, 1, 1); geometries.add(geometry);
    const mat = (dark, light = dark, glow = false) => {
      const m = new THREE.MeshStandardMaterial({ color: dark, roughness: 0.9, metalness: 0,
        ...(glow ? { emissive: dark, emissiveIntensity: 0.5 } : {}) });
      m.userData.seasons = { dark, light }; materials.add(m); return m;
    };
    const snow = mat('#b5dce9', '#e6bc9d'), edge = mat('#345674', '#aa7890');
    const asphalt = mat('#233b54', '#806d89'), stripe = mat('#c3e7ee', '#ffe3b7');
    const pine = mat('#387a79', '#cb794b'), trunk = mat('#665063', '#8d5d49');
    const body = mat('#52c5d5', '#e6a055'), glass = mat('#25425a', '#634e77');
    const rubber = mat('#132137'), lamp = mat('#ffe6aa', '#ffe6aa', true);
    const tailLamp = mat('#cf677d'), trim = mat('#95d6e5', '#ffe0b1');
    const box = (parent, w,h,d, x,y,z, material) => {
      const mesh = new THREE.Mesh(geometry, material);
      mesh.scale.set(w,h,d); mesh.position.set(x,y,z); parent.add(mesh); return mesh;
    };
    box(world,22.4,0.5,12, 0,-0.55,0,edge);
    box(world,22.4,0.12,12, 0,-0.24,0,snow);
    box(world,22.4,0.06,4.6, 0,-0.15,3.4,asphalt);
    for (const z of [1.15,5.65]) box(world,22.4,0.03,0.09,0,-0.1,z,stripe);
    for (let i=0;i<8;i++) roadMarks.push(box(world,1,0.03,0.1,i*2.8-11.2,-0.1,4.6,stripe));
    car = new THREE.Group(); car.position.z=3.3; car.scale.setScalar(.8); world.add(car);
    box(car,4.5,0.62,2.05,0,0.85,0,body);
    box(car,4.25,0.22,2.08,0,0.43,0,edge);
    box(car,2.65,0.95,1.9,-0.48,1.6,0,glass);
    box(car,2.95,0.18,2.08,-0.48,2.13,0,body);
    box(car,1.1,0.18,2.02,1.5,1.19,0,body);
    for (const x of [-1.76,-0.5,0.85]) box(car,0.13,0.98,1.98,x,1.62,0,body);
    for (const z of [-1.04,1.04]) {
      box(car,2.8,0.13,0.08,-0.48,1.12,z,trim);
      box(car,0.32,0.08,0.05,0.2,1.02,z,glass);
      box(car,0.3,0.18,0.28,0.94,1.48,z*1.07,body);
      box(car,2.5,0.12,0.12,-0.48,2.42,z*.75,edge);
    }
    for (const x of [-1.25,0.3]) box(car,0.12,0.28,1.65,x,2.32,0,edge);
    box(car,1.9,0.32,1.2,-0.48,2.55,0,body);
    box(car,1.96,0.08,1.24,-0.48,2.75,0,snow);
    const tireGeometry = new THREE.CylinderGeometry(.47,.47,.3,8); geometries.add(tireGeometry);
    for (const x of [-1.45,1.4]) for (const z of [-1.06,1.06]) {
      const wheel = new THREE.Group(); wheel.position.set(x,.45,z);
      const tire = new THREE.Mesh(tireGeometry,rubber); tire.rotation.x=Math.PI/2; wheel.add(tire);
      box(wheel,.44,.44,.32,0,0,0,trim);
      box(wheel,.15,.15,.34,0,0,0,edge);
      car.add(wheel); rollingWheels.push(wheel);
    }
    box(car,.12,.23,2.15,2.29,.64,0,trim);
    box(car,.12,.23,2.15,-2.29,.64,0,trim);
    box(car,.08,.26,.7,2.29,.94,0,glass);
    for (const z of [-.73,.73]) {
      box(car,.1,.3,.42,2.3,1.02,z,lamp);
      box(car,.08,.28,.3,-2.3,1.02,z,tailLamp);
    }
    const beamGeometry=new THREE.ConeGeometry(.55,3,4,1,true); geometries.add(beamGeometry);
    const beamMaterial=new THREE.MeshBasicMaterial({color:'#ffe9a8',transparent:true,opacity:.09,depthWrite:false,side:THREE.DoubleSide}); materials.add(beamMaterial);
    for(const z of [-.73,.73]) {
      const beam=new THREE.Mesh(beamGeometry,beamMaterial); beam.rotation.z=Math.PI/2;
      beam.scale.z=.45; beam.position.set(3.8,.55,z); car.add(beam); headlights.push(beam);
    }
    const route = buildCampusRoute(THREE,{box,mat,geometry,geometries,materials,textures});
    bridgeLighting=route.lighting;
    routeItems.push(...route.chunks); routeFlags.push(...route.wind); routeBirds.push(...route.birds);
    routeItems.forEach(({node})=>world.add(node)); routeBirds.forEach(({node})=>world.add(node));
    const clips=[new THREE.Plane(new THREE.Vector3(1,0,0),11.15),new THREE.Plane(new THREE.Vector3(-1,0,0),11.15)];
    materials.forEach(material=>{ material.clippingPlanes=clips; });
    updateRoute(0);
    camera.updateMatrixWorld(true);
    // Frame the stage, never the entire three-minute route stretching off-screen.
    const bounds = new THREE.Box3(new THREE.Vector3(-11.4,-.85,-6),new THREE.Vector3(11.4,7.5,6)).applyMatrix4(camera.matrixWorldInverse);
    const size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3());
    framing = { width:size.x, height:size.y, x:center.x, y:center.y };
    const particles = new THREE.BufferGeometry(); geometries.add(particles);
    const values = new Float32Array(70*3);
    for(let i=0;i<70;i++) { values[i*3]=(i*7.31%22)-11; values[i*3+1]=i*0.37%7+.5; values[i*3+2]=(i*3.71%11)-5.5; }
    particles.setAttribute('position',new THREE.BufferAttribute(values,3));
    const flakeMaterial = new THREE.PointsMaterial({ color: '#c5edff', size: 0.09, transparent:true, opacity:0.65, depthWrite:false });
    materials.add(flakeMaterial); flakes = new THREE.Points(particles,flakeMaterial); world.add(flakes);
    enabled = stored('its_scene_3d') !== 'false';
    toggle.hidden = false; toggle.addEventListener('click',changeMode);
    observer = new MutationObserver(sync);
    observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    observer.observe(document.body,{attributes:true,attributeFilter:['class']});
    observer.observe(login,{attributes:true,attributeFilter:['hidden']});
    resizeObserver = new ResizeObserver(resize); resizeObserver.observe(host);
    document.addEventListener('visibilitychange',sync); motion.addEventListener('change',sync);
    window.addEventListener('pageshow',sync);
    window.addEventListener('its:journey-next',nextScenery);
    window.addEventListener('pagehide',event => { if (event.persisted) stop(); else dispose(); });
    sync();
  } catch (_) { dispose(); }
}
boot();
