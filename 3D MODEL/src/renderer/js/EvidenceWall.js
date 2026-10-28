/* ══════════════════════════════════════════════════════════════════════
   Nishaan — Evidence Wall theme (presentation only)

   Adds the "detective's evidence wall" look on top of the existing markup:
     • hand-inked line icons (CSS masks over the Font Awesome <i> tags)
     • torn paper edges and slight tilts on notes, strips and tabs
     • red string ring with pins, plus pins on the left panel and viewport
       frame, corner brackets and registration marks around the 3D plate

   It never changes element ids, structure or behaviour; removing this file
   and styles/evidence-wall.css restores the previous look.
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  document.body.classList.add('ew');

  // ── Inked glyphs: 24×24, single 1.5px stroke, square caps, mitred joins ──
  const G = {
    pin: 'M12 3.5a4 4 0 1 1 0 8a4 4 0 1 1 0-8zM12 11.5v9.5M10 7.5h.01',
    face: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM9 9.5v1.5M15 9.5v1.5M8.5 14.5c2 2.2 5 2.2 7 0',
    scissors: 'M6 3.5a3 3 0 1 1 0 6a3 3 0 1 1 0-6zM6 14.5a3 3 0 1 1 0 6a3 3 0 1 1 0-6zM8.4 8.2L20 19M8.4 15.8L20 5',
    palette: 'M12 3c5 0 9 3.5 9 7.8c0 3-2.4 4.2-4.6 4.2h-1.6c-1.4 0-2 1.6-1 2.6c1 1 .3 2.4-1.2 2.4H12a8.5 8.5 0 0 1 0-17zM7 11h1.5M9.5 7h1.5M14 7h1.5',
    glasses: 'M3 14a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0zM14 14a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0zM10 14h4M3.2 13L5 6.5h2M20.8 13L19 6.5h-2',
    robot: 'M5 8h14v11H5zM12 8V4.5M10 4.5h4M9 11.5v2M15 11.5v2M9 16h6M3 11v4M21 11v4',
    camera: 'M3 7.5h4l2-3h6l2 3h4V19H3zM12 10a3.5 3.5 0 1 1 0 7a3.5 3.5 0 1 1 0-7zM17.5 10h1',
    folder: 'M3 5h6l2 2.5h10V19H3zM3 10h18',
    undo: 'M4.5 9.5H15a5 5 0 0 1 0 10H9M4.5 9.5l4-4M4.5 9.5l4 4',
    redo: 'M19.5 9.5H9a5 5 0 0 0 0 10h6M19.5 9.5l-4-4M19.5 9.5l-4 4',
    trash: 'M4 6.5h16M9 6.5V3.5h6v3M6 6.5l1 14h10l1-14M10 10v7M14 10v7',
    mic: 'M9 3h6v10.5H9zM5 11a7 7 0 0 0 14 0M12 18v3M8 21h8',
    plus: 'M12 4.5v15M4.5 12h15',
    send: 'M3 11.5L21 3l-7 18l-3-7.5zM11 13.5L21 3',
    save: 'M4 4h13l3 3v13H4zM8 4v5h8V4M7 14h10v6H7z',
    export: 'M12 15V3.5M7 8l5-4.5L17 8M4 14v6.5h16V14',
    import: 'M12 3.5V15M7 10.5l5 4.5l5-4.5M4 14v6.5h16V14',
    sliders: 'M4 6h9M17 6h3M15 4v4M4 12h3M11 12h9M9 10v4M4 18h11M19 18h1M17 16v4',
    minus: 'M5.5 12h13',
    square: 'M6 6h12v12H6z',
    times: 'M6 6l12 12M18 6L6 18',
    user: 'M12 3.5a4 4 0 1 1 0 8a4 4 0 1 1 0-8zM4.5 21c1-4.5 3.8-6.5 7.5-6.5s6.5 2 7.5 6.5',
    facescan: 'M3 8.5V3h5.5M15.5 3H21v5.5M21 15.5V21h-5.5M8.5 21H3v-5.5M12 7a3 3 0 1 1 0 6a3 3 0 1 1 0-6zM7 18c1-2.5 2.7-3.5 5-3.5s4 1 5 3.5',
    portrait: 'M6 3h12v18H6zM12 7a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5zM8.5 17.5c.8-2 2-3 3.5-3s2.7 1 3.5 3',
    walker: 'M12 3a2.3 2.3 0 1 1 0 4.6a2.3 2.3 0 1 1 0-4.6zM9 9.5h6V15h-1.5v5h-3v-5H9zM5 18.5c-2 1.2.5 2.5 7 2.5s9-1.3 7-2.5',
    down: 'M12 4v15M6 13l6 6l6-6',
    up: 'M12 20V5M6 11l6-6l6 6',
    left: 'M20 12H5M11 6l-6 6l6 6',
    right: 'M4 12h15M13 6l6 6l-6 6',
    grid: 'M4 4h16v16H4zM12 4v16M4 12h16',
    pointer: 'M9 11V4h3v7M12 8.5h3V12M15 10h3v5.5L16 21H9l-4-6l2-2l2 2',
    dot: 'M12 6.5a5.5 5.5 0 1 1 0 11a5.5 5.5 0 1 1 0-11z',
    stamp: 'M9 3h6v6l3 2v4H6v-4l3-2zM5 19h14v2H5z',
    video: 'M3 6.5h13v11H3zM16 10l5-3v10l-5-3',
    badge: 'M5 3h14v18H5zM10 3v3h4V3M12 9a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5zM8.3 18.5c.8-2 2-3 3.7-3s2.9 1 3.7 3',
    image: 'M3 5h18v14H3zM3 16l5-5l4 4l3-3l6 6M15 8.5h1.5',
    eraser: 'M14 4l6 6l-9 9H6l-3-3zM8 10l6 6M11 19h10',
    pen: 'M4 20l1-5L16 4l4 4L9 19zM14 6l4 4',
    mesh: 'M4 4h16v16H4zM4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16',
    target: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM11 12h2',
    gauge: 'M3 16a9 9 0 0 1 18 0M12 16l4-6M3 16h3M18 16h3',
    database: 'M5 5c0-1.5 3-2.5 7-2.5s7 1 7 2.5v14c0 1.5-3 2.5-7 2.5s-7-1-7-2.5zM5 5c0 1.5 3 2.5 7 2.5s7-1 7-2.5M5 12c0 1.5 3 2.5 7 2.5s7-1 7-2.5',
    check: 'M4.5 12.5l4.5 4.5L19.5 6.5',
    chevdown: 'M6 9.5l6 6l6-6',
    chevup: 'M6 14.5l6-6l6 6',
    cog: 'M12 9a3 3 0 1 1 0 6a3 3 0 1 1 0-6zM12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1',
    info: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM12 10.5v6.5M11.3 7.5h1.4',
    note: 'M5 3h10l4 4v14H5zM15 3v4h4M8 12h8M8 16h6',
    sync: 'M4.5 12a7.5 7.5 0 0 1 13.2-4.8M19.5 12a7.5 7.5 0 0 1-13.2 4.8M18 3.5v4h-4M6 20.5v-4h4',
    clock: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM12 7v5.5l3.5 2.5',
    lock: 'M6 11h12v10H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11',
    eye: 'M2.5 12c2.8-4.6 6-6.8 9.5-6.8s6.7 2.2 9.5 6.8c-2.8 4.6-6 6.8-9.5 6.8s-6.7-2.2-9.5-6.8zM12 9a3 3 0 1 1 0 6a3 3 0 1 1 0-6z',
    cube: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5l8-4.5M12 12v9',
    crosshair: 'M12 3v5M12 16v5M3 12h5M16 12h5M12 7.5a4.5 4.5 0 1 1 0 9a4.5 4.5 0 1 1 0-9z',
    comment: 'M4 4h16v12h-9l-5 4v-4H4z',
    ban: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM5.6 5.6l12.8 12.8',
    drop: 'M12 3.5l5.5 8a6 6 0 1 1-11 0z',
    move: 'M12 3v18M3 12h18M9 6l3-3l3 3M9 18l3 3l3-3M6 9l-3 3l3 3M18 9l3 3l-3 3',
    ruler: 'M3 17L17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2',
    layers: 'M12 3.5l9 4.5l-9 4.5L3 8zM3 12l9 4.5l9-4.5M3 16l9 4.5l9-4.5',
    brush: 'M14 4l6 6l-7 7l-6-6zM7 11l-3 3c-1 1-1 4 0 5s4 1 5 0l3-3',
    globe: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM3 12h18M12 3c-3 3-3 15 0 18M12 3c3 3 3 15 0 18',
    bulb: 'M9 17h6M10 21h4M12 3a6 6 0 0 1 3.5 10.9V17h-7v-3.1A6 6 0 0 1 12 3z',
    film: 'M4 3h16v18H4zM8 3v18M16 3v18M4 8h4M4 13h4M4 18h4M16 8h4M16 13h4M16 18h4',
    link: 'M9 15l6-6M10.5 6.5l2-2a4 4 0 0 1 5.7 5.7l-2 2M13.5 17.5l-2 2a4 4 0 0 1-5.7-5.7l2-2',
    warn: 'M12 3.5l9.5 16.5h-19zM12 9.5v5M11.3 17h1.4',
    search: 'M10 3.5a6.5 6.5 0 1 1 0 13a6.5 6.5 0 1 1 0-13zM15 15l5.5 5.5M10 7.5v5M7.5 10h5',
    mark: 'M7 7h10v10H7zM12 3v4M12 17v4M3 12h4M17 12h4',
  };
  const FA = {
    gem: 'pin', 'thumbtack': 'pin',
    'face-smile': 'face', smile: 'face', cut: 'scissors', palette: 'palette', glasses: 'glasses', robot: 'robot',
    'camera-retro': 'camera', camera: 'camera', 'folder-open': 'folder', folder: 'folder',
    undo: 'undo', 'undo-alt': 'undo', 'rotate-left': 'undo', rotate: 'sync', redo: 'redo', 'redo-alt': 'redo',
    'trash-alt': 'trash', trash: 'trash', microphone: 'mic', 'microphone-slash': 'mic', plus: 'plus', 'plus-circle': 'plus',
    'paper-plane': 'send', save: 'save', 'file-export': 'export', upload: 'export', 'file-import': 'import', download: 'import',
    'sliders-h': 'sliders', sliders: 'sliders', minus: 'minus', square: 'square', times: 'times', xmark: 'times',
    user: 'user', 'user-tie': 'user', 'user-clock': 'user', 'user-shield': 'user', 'user-secret': 'user', 'user-plus': 'user',
    'user-ninja': 'user', 'user-graduate': 'user', 'user-doctor': 'user', 'user-astronaut': 'user', 'id-card': 'badge',
    'users-viewfinder': 'facescan', portrait: 'portrait', 'street-view': 'walker', 'arrow-down': 'down', 'arrow-up': 'up',
    'arrow-left': 'left', 'arrow-right': 'right', 'angle-double-right': 'right', 'border-all': 'grid', columns: 'grid',
    'hand-pointer': 'pointer', circle: 'dot', 'dot-circle': 'target', stamp: 'stamp', video: 'video', 'id-badge': 'badge',
    image: 'image', eraser: 'eraser', broom: 'eraser', pen: 'pen', edit: 'pen', th: 'mesh', 'tachometer-alt': 'gauge',
    database: 'database', check: 'check', 'caret-down': 'chevdown', 'angle-down': 'chevdown', 'sort-down': 'chevdown',
    'chevron-down': 'chevdown', 'chevron-up': 'chevup', cog: 'cog', tools: 'cog', 'info-circle': 'info',
    'sticky-note': 'note', 'file-alt': 'note', 'sync-alt': 'sync', history: 'clock', clock: 'clock', 'hourglass-half': 'clock',
    lock: 'lock', eye: 'eye', cube: 'cube', crosshairs: 'crosshair', bullseye: 'crosshair', 'comment-alt': 'comment',
    'comment-dots': 'comment', ban: 'ban', tint: 'drop', droplet: 'drop', 'fill-drip': 'drop', adjust: 'drop',
    'arrows-alt': 'move', 'arrows-up-down-left-right': 'move', 'arrows-left-right': 'move', 'arrows-alt-v': 'move',
    'expand-alt': 'move', 'expand-arrows-alt': 'move', expand: 'move', 'ruler-vertical': 'ruler', 'ruler-combined': 'ruler',
    'layer-group': 'layers', 'paint-brush': 'brush', globe: 'globe', lightbulb: 'bulb', film: 'film', link: 'link',
    'exclamation-triangle': 'warn', 'search-plus': 'search', 'circle-notch': 'sync', 'head-side-mask': 'face', mask: 'face',
    weight: 'user', 'wave-square': 'mesh', 'bezier-curve': 'pen', 'grip-lines-vertical': 'grid', brain: 'face',
    nose: 'face', kiss: 'face', teeth: 'face', 'ear-listen': 'face', eyedropper: 'drop', 'face-meh': 'face',
    'tachometer': 'gauge', blender: 'cube', cloud: 'layers', bridge: 'move', wind: 'sync', 'file-image': 'image',
  };
  const svgUrl = (d) => `url("data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#000' stroke-width='1.5' stroke-linecap='square' stroke-linejoin='miter' stroke-miterlimit='8'><path d='${d}'/></svg>`)}")`;
  let css = `body.ew i[class*="fa-"]{display:inline-block;width:1em;height:1em;line-height:1;vertical-align:-0.14em;
    background-color:currentColor;-webkit-mask:${svgUrl(G.mark)} center/contain no-repeat;mask:${svgUrl(G.mark)} center/contain no-repeat;}
    body.ew i[class*="fa-"]::before{content:""!important;}\n`;
  for (const [fa, glyph] of Object.entries(FA)) {
    const u = svgUrl(G[glyph]);
    css += `body.ew i.fa-${fa}{-webkit-mask-image:${u};mask-image:${u};}\n`;
  }
  const style = document.createElement('style');
  style.id = 'ew-glyphs';
  style.textContent = css;
  document.head.appendChild(style);

  // ── Deterministic randomness so every scrap keeps its own shape ──
  function rng(seed) {
    let s = seed >>> 0 || 1;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }
  function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
    return h >>> 0;
  }

  /** Ragged polygon: top and bottom edges differ, sides slightly uneven. */
  function tornClip(seed, amp) {
    const r = rng(seed);
    const pts = [];
    const n = 16;
    for (let i = 0; i <= n; i++) pts.push(`${(i / n * 100).toFixed(2)}% ${(r() * amp).toFixed(2)}px`);
    for (let i = 1; i < 6; i++) pts.push(`calc(100% - ${(r() * 0.9).toFixed(2)}px) ${(i / 6 * 100).toFixed(2)}%`);
    for (let i = n; i >= 0; i--) pts.push(`${(i / n * 100).toFixed(2)}% calc(100% - ${(r() * amp * 1.25).toFixed(2)}px)`);
    for (let i = 5; i > 0; i--) pts.push(`${(r() * 0.9).toFixed(2)}px ${(i / 6 * 100).toFixed(2)}%`);
    return `polygon(${pts.join(',')})`;
  }

  // [selector, max tilt (deg), torn amplitude (px)]
  const SCRAPS = [
    ['.rf-sidebar-tab', 1.5, 1.8],
    ['.rf-ai-example-chip', 1.4, 2.0],
    ['.ai-quick-btn', 1.5, 1.4],
    ['#rf-topbar-case-display', 0.9, 1.6],
    ['#rf-topbar-export', 0.6, 1.2],
    ['#rf-viewport-toolbar', 0.35, 1.8],
    ['#rf-viewport-actions .rf-vp-action-row', 0.45, 1.8],
    ['.rf-variant-launch .sub-group-label', 0.8, 1.6],
    ['.ai-chat-textarea', 0.5, 1.4],
    ['.ai-message', 1.0, 1.6],
    ['#rf-backend-banner', 0.4, 1.6],
  ];
  function dress() {
    for (const [sel, tilt, amp] of SCRAPS) {
      document.querySelectorAll(sel).forEach((el, i) => {
        if (el.dataset.ewDressed) return;
        const seed = hash(sel + i + (el.id || el.textContent.trim().slice(0, 24)));
        const r = rng(seed);
        el.style.setProperty('--ew-tilt', `${((r() * 2 - 1) * tilt).toFixed(2)}deg`);
        el.style.setProperty('--ew-torn', tornClip(seed, amp));
        el.style.setProperty('--ew-w', `${(r() * 10 - 5).toFixed(1)}%`);
        el.classList.add('ew-scrap');
        el.dataset.ewDressed = '1';
      });
    }
  }

  // ── Strings, pins, brackets ──
  const RING = 8;          // inset of the string ring from the window edge
  let editor, svg, pinLayer;

  function ensureLayers() {
    editor = document.getElementById('rf-screen-editor');
    if (!editor || svg) return !!editor;
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'ew-strings';
    svg.setAttribute('aria-hidden', 'true');
    editor.insertBefore(svg, editor.firstChild);
    pinLayer = document.createElement('div');
    pinLayer.id = 'ew-pins';
    pinLayer.setAttribute('aria-hidden', 'true');
    editor.appendChild(pinLayer);
    return true;
  }

  function rectIn(el, base) {
    const r = el.getBoundingClientRect();
    return { l: r.left - base.left, t: r.top - base.top, r: r.right - base.left, b: r.bottom - base.top, w: r.width, h: r.height };
  }

  function layout() {
    if (!ensureLayers() || editor.classList.contains('rf-screen-hidden')) return;
    const base = editor.getBoundingClientRect();
    const W = base.width, H = base.height;
    if (W < 10 || H < 10) return;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('width', W);
    svg.setAttribute('height', H);

    const pins = [];
    const lines = [];
    const pin = (x, y, size) => { pins.push({ x, y, size: size || 9 }); return { x, y }; };
    const string = (a, b, over) => {
      // extend each end slightly so strings cross at their pins
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, o = over ?? 5;
      lines.push([a.x - dx / len * o, a.y - dy / len * o, b.x + dx / len * o, b.y + dy / len * o]);
    };

    // Outer ring: corners + side midpoints
    const L = RING, T = RING, R = W - RING, B = H - RING;
    const ring = [pin(L, T), pin(W / 2, T), pin(R, T), pin(R, H / 2), pin(R, B), pin(W / 2, B), pin(L, B), pin(L, H / 2)];
    ring.forEach((p, i) => string(p, ring[(i + 1) % ring.length]));

    // Left panel hangs from two pins
    const panel = document.getElementById('left-panel');
    if (panel && panel.offsetParent) {
      const p = rectIn(panel, base);
      const tl = pin(p.l + 14, p.t + 7, 10), tr = pin(p.r - 14, p.t + 7, 10);
      string(tl, ring[7]);
      const junction = pin(tr.x, T, 7);
      string(tr, junction, 3);
    }

    // Viewport plate: pins on the frame edge, outside the black area
    const canvas = document.getElementById('viewport-canvas');
    if (canvas && canvas.offsetParent) {
      const c = rectIn(canvas, base);
      const o = 7;
      const vtl = pin(c.l - o, c.t - o, 9), vtr = pin(c.r + o, c.t - o, 9);
      pin(c.l - o, c.b + o, 9); pin(c.r + o, c.b + o, 9);
      string(vtr, ring[3]);
      if (panel && panel.offsetParent) {
        const p = rectIn(panel, base);
        string(vtl, { x: p.r - 14, y: p.t + 7 }, 3);
      }
      drawBrackets(c);
    }

    // Active sidebar tab gets its own small pin
    const active = document.querySelector('.rf-sidebar-tab.active');
    if (active && active.offsetParent) {
      const a = rectIn(active, base);
      pin(a.l + a.w / 2, a.t + 4, 7);
    }

    svg.innerHTML = lines.map(([x1, y1, x2, y2]) =>
      `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`).join('');
    pinLayer.querySelectorAll('.ew-pin').forEach(n => n.remove());
    pinLayer.insertAdjacentHTML('beforeend', pins.map(p =>
      `<span class="ew-pin" style="left:${p.x}px;top:${p.y}px;width:${p.size}px;height:${p.size}px"></span>`).join(''));
  }

  function drawBrackets(c) {
    pinLayer.querySelectorAll('.ew-bracket,.ew-reg').forEach(n => n.remove());
    const corners = [['tl', c.l, c.t], ['tr', c.r, c.b * 0 + c.t], ['bl', c.l, c.b], ['br', c.r, c.b]];
    let html = '';
    for (const [k, x, y] of corners) html += `<span class="ew-bracket ew-${k}" style="left:${x}px;top:${y}px"></span>`;
    html += `<span class="ew-reg" style="left:${c.l + 22}px;top:${c.t + 22}px"></span>`;
    html += `<span class="ew-reg" style="left:${c.r - 22}px;top:${c.t + 22}px"></span>`;
    pinLayer.insertAdjacentHTML('beforeend', html);
  }

  let pending = null;
  function schedule() {
    if (pending) return;
    pending = requestAnimationFrame(() => { pending = null; dress(); layout(); });
  }

  window.addEventListener('resize', schedule);
  document.addEventListener('click', (e) => {
    if (e.target.closest('.rf-sidebar-tab, .rf-vp-btn, .rf-mode-btn')) setTimeout(schedule, 50);
  }, true);
  // Re-dress new content (chat messages, tab switches); ignore our own layers
  new MutationObserver((records) => {
    if (records.some(r => !(svg && svg.contains(r.target)) && !(pinLayer && pinLayer.contains(r.target))
        && r.target !== svg && r.target !== pinLayer)) schedule();
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  document.addEventListener('DOMContentLoaded', schedule);
  window.addEventListener('load', () => { schedule(); setTimeout(() => window.dispatchEvent(new Event('resize')), 50); });
  schedule();
})();
