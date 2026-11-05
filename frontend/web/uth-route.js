/* Illustrated Võ Oanh campus, based on the facade reference in docs/UTH_JOURNEY.md. */
export function buildCampusRoute(THREE, { box, mat, geometry, geometries, materials, textures }) {
  const white = mat('#d4e0e8', '#f1eae0'),
    blue = mat('#244a9b'),
    glass = mat('#253f5b', '#738c9c');
  const bark = mat('#64596b', '#916a54');
  const gold = mat('#e4ce88'),
    grey = mat('#46566b', '#8c8186'),
    trim = mat('#abc2d5', '#e1d3be');
  const leaf = mat('#508e87', '#cd8d58'),
    flower = mat('#b7c27e', '#edb060');
  const glow = mat('#ffe3a1', '#ffe3a1', true);
  const water = mat('#326f96', '#6997ad'),
    roof = mat('#596c8d', '#a77f7e');
  const wind = [],
    birds = [];
  function label(
    parent,
    text,
    w,
    h,
    x,
    y,
    z,
    { color = '#167e91', background = '#edf1ef', size = 60 } = {},
  ) {
    const canvas = document.createElement('canvas');
    canvas.width = 2048;
    canvas.height = Math.max(64, Math.round((2048 * h) / w));
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const lines = text.split('\n'),
      lineHeight = canvas.height / (lines.length + 0.35);
    ctx.fillStyle = color;
    ctx.font = `700 ${Math.min(size * 2, lineHeight * 0.82)}px Arial, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    lines.forEach((line, i) =>
      ctx.fillText(line, 1024, canvas.height / 2 + (i - (lines.length - 1) / 2) * lineHeight, 1980),
    );
    const map = new THREE.CanvasTexture(canvas);
    map.colorSpace = THREE.SRGBColorSpace;
    textures.add(map);
    const m = new THREE.MeshBasicMaterial({ map, side: THREE.DoubleSide });
    materials.add(m);
    const g = new THREE.PlaneGeometry(w, h);
    geometries.add(g);
    const sign = new THREE.Mesh(g, m);
    sign.position.set(x, y, z);
    parent.add(sign);
    return sign;
  }
  function tree(parent, x, z, height = 3) {
    box(parent, 0.2, height, 0.2, x, height / 2, z, bark);
    for (let i = 0; i < 3; i++)
      box(parent, 1.5 - i * 0.32, 0.65, 1.4 - i * 0.3, x, height * 0.58 + i * 0.45, z, leaf);
    box(parent, 1.55, 0.09, 1.45, x, height * 0.58 + 0.36, z, trim);
  }
  function lamp(parent, x, z) {
    box(parent, 0.1, 3, 0.1, x, 1.4, z, grey);
    box(parent, 0.7, 0.1, 0.12, x + 0.3, 2.9, z, grey);
    box(parent, 0.3, 0.22, 0.3, x + 0.58, 2.75, z, glow);
  }
  function bench(parent, x, z) {
    box(parent, 1.3, 0.12, 0.5, x, 0.5, z, roof);
    box(parent, 1.3, 0.5, 0.1, x, 0.8, z - 0.22, roof);
    for (const dx of [-0.45, 0.45]) box(parent, 0.1, 0.5, 0.3, x + dx, 0.2, z, grey);
  }
  const campus = new THREE.Group();
  // The user's reference: triangular pediment, four columns, red louvers and gold relief.
  const crimson = mat('#a82c40'),
    deepRed = mat('#722638'),
    stone = mat('#bfcbd2', '#dedbd2');
  box(campus, 16, 6.9, 2.8, 0, 3.65, -3.6, white);
  box(campus, 14.9, 4.7, 0.1, 0, 4.2, -2.14, deepRed);
  for (let i = 0; i < 31; i++) box(campus, 14.9, 0.075, 0.17, 0, 1.95 + i * 0.15, -2.02, crimson);
  // Glass doors and their pale frames run along the entire ground floor.
  box(campus, 14.6, 1.6, 0.12, 0, 0.95, -2.04, glass);
  for (let i = 0; i < 11; i++) box(campus, 0.07, 1.65, 0.12, -7.15 + i * 1.43, 0.95, -1.94, white);
  box(campus, 14.8, 0.12, 0.2, 0, 1.8, -1.98, stone);
  for (const x of [-8, 8]) {
    box(campus, 0.6, 6.9, 0.7, x, 3.6, -1.8, white);
    box(campus, 0.85, 0.25, 1, x, 0.3, -1.65, stone);
    box(campus, 0.85, 0.25, 1, x, 6.8, -1.65, stone);
  }
  const columnGeometry = new THREE.CylinderGeometry(0.2, 0.27, 6.2, 12);
  geometries.add(columnGeometry);
  for (const x of [-5.3, -1.8, 1.8, 5.3]) {
    const col = new THREE.Mesh(columnGeometry, white);
    col.position.set(x, 3.4, -1.1);
    campus.add(col);
    for (const [y, w, h] of [
      [0.26, 0.7, 0.2],
      [0.44, 0.52, 0.14],
      [6.4, 0.5, 0.16],
      [6.58, 0.66, 0.18],
    ])
      box(campus, w, h, 0.7, x, y, -1.1, stone);
  }
  box(campus, 17.1, 0.24, 4, 0, 6.85, -2.6, stone);
  box(campus, 16.8, 0.62, 0.65, 0, 7.25, -1.04, white);
  label(campus, 'ĐẠI HỌC GIAO THÔNG VẬN TẢI THÀNH PHỐ HỒ CHÍ MINH', 16.1, 0.48, 0, 7.25, -0.69, {
    color: '#a72b3d',
    background: '#e8e7df',
    size: 75,
  });
  box(campus, 17.2, 0.2, 4.1, 0, 7.65, -2.6, stone);
  const pediment = new THREE.Shape();
  pediment.moveTo(-8.55, 0);
  pediment.lineTo(0, 1.9);
  pediment.lineTo(8.55, 0);
  pediment.closePath();
  const pedimentGeometry = new THREE.ExtrudeGeometry(pediment, { depth: 3.2, bevelEnabled: false });
  geometries.add(pedimentGeometry);
  const pedimentMesh = new THREE.Mesh(pedimentGeometry, white);
  pedimentMesh.position.set(0, 7.76, -4.5);
  campus.add(pedimentMesh);
  for (const side of [-1, 1]) {
    const cornice = box(campus, 8.85, 0.18, 0.28, side * 4.28, 8.72, -1.13, stone);
    cornice.rotation.z = -side * Math.atan2(1.9, 8.55);
  }
  for (let i = 0; i < 25; i++)
    box(
      campus,
      0.18,
      0.16,
      0.22,
      -8 + i * 0.67,
      7.93 + 1.72 * (1 - Math.abs(-8 + i * 0.67) / 8),
      -1.08,
      stone,
    );
  // Relief is a geometric gold plaque, not a substituted photograph.
  box(campus, 2.05, 2.4, 0.13, 0, 4.25, -1.85, gold);
  box(campus, 1.8, 2.15, 0.1, 0, 4.25, -1.75, flower);
  for (let i = 0; i < 18; i++) {
    const angle = i * 2.4,
      radius = 0.22 + (i % 4) * 0.12;
    const relief = box(
      campus,
      0.15,
      0.3,
      0.08,
      Math.cos(angle) * radius,
      4.25 + Math.sin(angle) * 0.8,
      -1.66,
      gold,
    );
    relief.rotation.z = angle;
  }
  // Broad shallow steps and flower pots from the reference photograph.
  for (let i = 0; i < 4; i++)
    box(campus, 17.6 + i * 0.5, 0.11, 1.4 + i * 0.5, 0, 0.12 - i * 0.11, -0.4 + i * 0.25, white);
  for (const x of [-8.5, 8.5]) {
    box(campus, 0.65, 0.55, 0.65, x, 0.3, -0.3, stone);
    for (let i = 0; i < 5; i++)
      box(
        campus,
        0.3,
        0.22,
        0.3,
        x + ((i % 3) - 1) * 0.22,
        0.75 + (i % 2) * 0.13,
        -0.3 + (i % 2) * 0.2,
        crimson,
      );
  }
  for (const x of [-10.5, 10.5]) {
    box(campus, 3.5, 5.7, 3, x, 2.9, -4.2, white);
    for (const y of [1.2, 2.8, 4.4])
      for (const dx of [-1, 0, 1]) box(campus, 0.65, 1.05, 0.08, x + dx, y, -2.65, glass);
    tree(campus, x, 0.1, 3.3);
  }
  campus.scale.setScalar(0.72);

  const park = new THREE.Group();
  for (let i = 0; i < 9; i++) tree(park, -10 + i * 2.5, -2 - (i % 2) * 2, 2.3 + (i % 3) * 0.6);
  for (const x of [-6, 0, 6]) {
    bench(park, x, -0.5);
    lamp(park, x + 1, -1);
  }
  box(park, 3, 0.3, 2, 0, 0.1, -3, grey);
  box(park, 0.4, 1.5, 0.4, 0, 0.9, -3, white);
  box(park, 1.7, 0.15, 1.3, 0, 1.65, -3, water);

  const river = new THREE.Group();
  const led = (dark, light) => {
    const m = new THREE.MeshBasicMaterial({ color: dark });
    m.userData.seasons = { dark, light };
    materials.add(m);
    return m;
  };
  const ledBlue = led('#65deff', '#a98bca'),
    ledPink = led('#d3a1ff', '#ce997f');
  const reflection = new THREE.MeshBasicMaterial({
    color: '#9abfff',
    transparent: true,
    opacity: 0.18,
    depthWrite: false,
  });
  materials.add(reflection);
  const glowCanvas = document.createElement('canvas');
  glowCanvas.width = 64;
  glowCanvas.height = 64;
  const glowCtx = glowCanvas.getContext('2d'),
    gradient = glowCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(255,255,255,.9)');
  gradient.addColorStop(0.18, 'rgba(255,255,255,.5)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  glowCtx.fillStyle = gradient;
  glowCtx.fillRect(0, 0, 64, 64);
  const glowMap = new THREE.CanvasTexture(glowCanvas);
  textures.add(glowMap);
  const halos = [];
  const halo = (x, y, z, color, size) => {
    const m = new THREE.SpriteMaterial({
      map: glowMap,
      color,
      transparent: true,
      opacity: 0.8,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    materials.add(m);
    const s = new THREE.Sprite(m);
    s.position.set(x, y, z);
    s.scale.set(size, size, 1);
    river.add(s);
    halos.push(m);
  };
  box(river, 23, 0.05, 5, 0, -0.04, -3, water);
  for (let i = 0; i < 17; i++) {
    const x = -11 + i * 1.4;
    box(river, 0.1, 0.85, 0.1, x, 0.4, -0.4, trim);
    box(river, 0.8, 0.015, 0.06, x, 0.06, -3 + (i % 3) * 0.6, white);
  }
  box(river, 23, 0.09, 0.09, 0, 0.8, -0.4, trim);
  // Ba Son: one curved, tapering pylon with two fans of stay cables.
  box(river, 22, 0.18, 1.8, 0, 1.25, -3.8, roof);
  for (const z of [-4.68, -2.92]) {
    box(river, 22, 0.1, 0.08, 0, 1.4, z, white);
    box(river, 22, 0.055, 0.04, 0, 1.48, z, z < -4 ? ledPink : ledBlue);
    for (let i = 0; i < 35; i++) box(river, 0.07, 0.07, 0.07, -10.8 + i * 0.635, 1.5, z, ledBlue);
  }
  const pylon = new THREE.Shape();
  pylon.moveTo(3.7, 0);
  pylon.quadraticCurveTo(4.35, 3.8, 2.45, 6.9);
  pylon.lineTo(2.7, 6.8);
  pylon.quadraticCurveTo(5.2, 3.7, 4.15, 0);
  pylon.closePath();
  const pylonGeometry = new THREE.ExtrudeGeometry(pylon, { depth: 0.45, bevelEnabled: false });
  geometries.add(pylonGeometry);
  const towerMaterial = new THREE.MeshStandardMaterial({
    color: '#d9e6ed',
    emissive: '#a98dff',
    emissiveIntensity: 0.55,
    roughness: 0.7,
  });
  materials.add(towerMaterial);
  towerMaterial.userData.seasons = { dark: '#d9e6ed', light: '#f1eae0' };
  const tower = new THREE.Mesh(pylonGeometry, towerMaterial);
  tower.position.z = -4.02;
  river.add(tower);
  box(river, 1, 0.55, 2.2, 3.95, 0.2, -3.8, white);
  const spine = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(3.95, 0, -3.8),
    new THREE.Vector3(5, 3.75, -3.8),
    new THREE.Vector3(2.57, 6.85, -3.8),
  );
  const connect = (from, to, light) => {
    const delta = new THREE.Vector3().subVectors(to, from);
    const stay = box(river, 0.032, delta.length(), 0.032, 0, 0, 0, light);
    stay.position.copy(from).add(to).multiplyScalar(0.5);
    stay.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
  };
  for (const z of [-4.58, -3.02]) {
    for (let i = 0; i < 12; i++)
      connect(
        spine.getPoint(0.98 - i * 0.032),
        new THREE.Vector3(-10.7 + i * 1.05, 1.4, z),
        i % 2 ? ledPink : ledBlue,
      );
    for (let i = 0; i < 6; i++)
      connect(
        spine.getPoint(0.6 + i * 0.075),
        new THREE.Vector3(5.3 + i * 1.07, 1.4, z),
        i % 2 ? ledPink : ledBlue,
      );
  }
  for (const x of [-8, -3, 3, 8]) {
    lamp(river, x, -0.1);
    halo(x + 0.58, 2.75, -0.1, '#ffe3a1', 0.85);
  }
  halo(2.57, 6.85, -3.8, '#b8a4ff', 1.25);
  halo(3.95, 0.65, -3.2, '#85dfff', 1.6);
  const flood = new THREE.PointLight('#a7a6ff', 7, 9, 2);
  flood.position.set(3.8, 2.8, -1.8);
  river.add(flood);
  for (let i = 0; i < 24; i++)
    box(
      river,
      0.25 + (i % 3) * 0.15,
      0.01,
      0.45 + (i % 4) * 0.12,
      -10.5 + i * 0.9,
      0.025,
      -1.4 - (i % 3) * 0.6,
      reflection,
    );
  const lighting = {
    update(time, theme) {
      const night = theme !== 'light',
        breath = 0.88 + 0.12 * Math.sin(time * 0.5);
      towerMaterial.emissiveIntensity = night ? 0.55 * breath : 0.04;
      flood.intensity = night ? 7 * breath : 0.2;
      reflection.opacity = night ? 0.17 * breath : 0.035;
      halos.forEach((m) => {
        m.opacity = night ? 0.8 * breath : 0.12;
      });
    },
  };
  label(river, 'CẦU BA SON', 3.2, 0.42, 7, 0.85, -2.8, {
    color: '#426485',
    background: '#e5ecec',
    size: 110,
  });

  const town = new THREE.Group();
  for (let i = 0; i < 5; i++) {
    const x = -9 + i * 4.4,
      h = 3.2 + (i % 3) * 0.9;
    box(town, 3.8, h, 2.6, x, h / 2, -3, i % 2 ? white : roof);
    for (const y of [1, 2.2, 3.3])
      for (const dx of [-1.1, 0, 1.1])
        if (y < h - 0.2) box(town, 0.62, 0.7, 0.06, x + dx, y, -1.67, glow);
    box(town, 4, 0.2, 3, x, h + 0.1, -3, blue);
    for (let j = 0; j < 8; j++)
      box(town, 0.48, 0.3, 0.75, x - 1.68 + j * 0.48, 1.5, -1.3, j % 2 ? white : leaf);
  }
  label(town, 'CÀ PHÊ', 2.6, 0.5, 0, 1, -1.1, {
    color: '#66516e',
    background: '#f3dfba',
    size: 120,
  });
  for (const x of [-7, 3, 8]) tree(town, x, 0, 2.6);

  const avenue = new THREE.Group();
  for (let i = 0; i < 11; i++) {
    const x = -12 + i * 2.4;
    tree(avenue, x, -1.5 - (i % 2) * 2, 2.5 + (i % 3) * 0.5);
    if (i % 3 === 0) lamp(avenue, x, 0);
    box(avenue, 1.2, 0.1, 1, x, -0.05, -4.5, flower);
  }
  const stop = new THREE.Group();
  for (const x of [-9, -4, 4, 9]) tree(stop, x, -2, 3);
  box(stop, 5, 0.18, 2.2, 0, 2.5, -2, blue);
  for (const x of [-2.2, 2.2]) box(stop, 0.14, 2.5, 0.14, x, 1.2, -2, trim);
  box(stop, 4.5, 1.8, 0.08, 0, 1.3, -2.7, glass);
  bench(stop, 0, -2);
  label(stop, 'UTH · VÕ OANH', 4, 0.55, 0, 2.2, -0.88, { size: 100 });
  lamp(stop, -6, 0);
  lamp(stop, 6, 0);
  const chunks = [campus, park, river, town, avenue, stop].map((node, i) => ({ node, at: i * 36 }));
  // Merge static boxes into material batches; only the passing scenery is drawn.
  for (const { node } of chunks) {
    node.updateMatrixWorld(true);
    const batches = new Map(),
      remove = [];
    node.traverse((mesh) => {
      if (!mesh.isMesh || mesh.geometry !== geometry || wind.includes(mesh)) return;
      if (!batches.has(mesh.material)) batches.set(mesh.material, []);
      batches.get(mesh.material).push(mesh.matrix.clone());
      remove.push(mesh);
    });
    remove.forEach((mesh) => mesh.removeFromParent());
    for (const [material, matrices] of batches) {
      const mesh = new THREE.InstancedMesh(geometry, material, matrices.length);
      matrices.forEach((matrix, i) => mesh.setMatrixAt(i, matrix));
      mesh.instanceMatrix.needsUpdate = true;
      node.add(mesh);
    }
  }
  // Small birds are part of the scenery, rather than an overlay on the form.
  for (let i = 0; i < 3; i++) {
    const bird = new THREE.Group();
    const wings = [
      box(bird, 0.45, 0.07, 0.12, -0.2, 0, 0, grey),
      box(bird, 0.45, 0.07, 0.12, 0.2, 0, 0, grey),
    ];
    birds.push({ node: bird, wings, phase: i * 2 });
  }
  return { chunks, wind, birds, lighting };
}
