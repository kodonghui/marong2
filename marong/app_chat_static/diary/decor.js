const ART = /^\/chat\/decor\/v[0-9]{1,3}\/[a-z0-9-]{3,40}\/[A-Za-z0-9_-]+\.(?:png|webp|woff2)$/;
const clamp = (v, low, high) => Math.max(low, Math.min(high, Math.round(v)));
const fonts = new Map();

export function imageSource(url) {
  return typeof url === 'string' && ART.test(url) ? url : null;
}

export function paintDecor(paper, book, decor) {
  const background = imageSource(decor?.background?.imageUrl);
  const lining = imageSource(decor?.paper?.imageUrl);
  if (background) book.style.setProperty('--book-background', `url("${background}")`);
  else book.style.removeProperty('--book-background');
  if (lining) paper.style.setProperty('--paper-background', `url("${lining}")`);
  const url = imageSource(decor?.font?.fontUrl);
  if (!url || !document.fonts) return;
  let loaded = fonts.get(url);
  if (!loaded) {
    const family = 'MarongDiary' + fonts.size;
    const next = new FontFace(family, `url("${url}")`, {display: 'swap'});
    loaded = next.load().then(() => { document.fonts.add(next); return family; }).catch(() => null);
    fonts.set(url, loaded);
  }
  loaded.then(family => { if (family) paper.style.setProperty('--font-diary', family); });
}

export function styleSticker(image, entry) {
  image.style.left = entry.x / 10 + '%';
  image.style.top = entry.y / 10 + '%';
  image.style.setProperty('--sticker-size', entry.scale / 100);
  image.style.setProperty('--sticker-angle', entry.rotation + 'deg');
}

export function drawStickers(container, entries) {
  for (const sticker of entries) {
    const url = imageSource(sticker.imageUrl);
    if (!url) continue;
    const image = new Image();
    image.className = 'diary-sticker';
    image.src = url;
    image.alt = '';
    image.draggable = false;
    styleSticker(image, sticker);
    image.addEventListener('error', () => image.remove(), {once: true});
    container.append(image);
  }
}

export function moveSticker(button, board, entry, redraw) {
  const points = new Map();
  let gesture = null;
  const measure = () => {
    const [a, b] = points.values();
    return b ? {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2,
                span: Math.hypot(b.x - a.x, b.y - a.y), angle: Math.atan2(b.y - a.y, b.x - a.x)}
      : {x: a.x, y: a.y, span: 0, angle: 0};
  };
  function start() {
    gesture = {...measure(), x0: entry.x, y0: entry.y, scale: entry.scale, rotation: entry.rotation};
  }
  button.addEventListener('pointerdown', event => {
    if (points.size === 2) return;
    points.set(event.pointerId, {x: event.clientX, y: event.clientY});
    button.setPointerCapture(event.pointerId);
    start();
  });
  button.addEventListener('pointermove', event => {
    if (!points.has(event.pointerId)) return;
    points.set(event.pointerId, {x: event.clientX, y: event.clientY});
    const next = measure();
    const bounds = board.getBoundingClientRect();
    entry.x = clamp(gesture.x0 + (next.x - gesture.x) * 1000 / bounds.width, 0, 1000);
    entry.y = clamp(gesture.y0 + (next.y - gesture.y) * 1000 / bounds.height, 0, 1000);
    if (gesture.span > 0 && next.span > 0) {
      entry.scale = clamp(gesture.scale * next.span / gesture.span, 50, 200);
      entry.rotation = clamp(gesture.rotation + (next.angle - gesture.angle) * 180 / Math.PI, -180, 180);
    }
    styleSticker(button, entry);
  });
  const stop = event => {
    if (!points.delete(event.pointerId)) return;
    if (points.size) start();
    else if (redraw) redraw();
  };
  button.addEventListener('pointerup', stop);
  button.addEventListener('lostpointercapture', stop);
}

export function resizeSticker(handle, sticker, entry) {
  let start;
  handle.addEventListener('pointerdown', event => {
    event.stopPropagation();
    handle.setPointerCapture(event.pointerId);
    const box = sticker.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    start = {x, y, size: entry.scale, radius: Math.max(1, Math.hypot(event.clientX - x, event.clientY - y))};
  });
  handle.addEventListener('pointermove', event => {
    if (!start || !handle.hasPointerCapture(event.pointerId)) return;
    const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    entry.scale = clamp(start.size * distance / start.radius, 50, 200);
    styleSticker(sticker, entry);
  });
  handle.addEventListener('lostpointercapture', () => { start = null; });
}
