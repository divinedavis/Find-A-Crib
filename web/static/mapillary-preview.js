/* Local-only Mapillary evaluation. No requests unless explicitly selected.
   Use a project-owned client token before considering a production rollout. */
(() => {
  const enabled = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)
    && new URLSearchParams(location.search).get('photos') === 'mapillary';
  const token = window.MAPILLARY_PREVIEW_TOKEN || '';
  const cache = new Map(), queue = [], observed = new Set();
  let active = 0, searches = 0;
  const limit = 24; // Bound use of the official demo token during evaluation.
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const radians = d => d * Math.PI / 180;
  function rank(row, lat, lng) {
    const xy = (row.computed_geometry || row.geometry)?.coordinates;
    if (!xy || row.is_pano || !row.thumb_1024_url) return null;
    const [x, y] = xy;
    const dx = (lng - x) * 111320 * Math.cos(radians(lat));
    const dy = (lat - y) * 111320;
    const distance = Math.hypot(dx, dy);
    if (distance > 80) return null;
    const bearing = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
    const angle = row.compass_angle == null ? 90
      : Math.abs(((bearing - row.compass_angle + 540) % 360) - 180);
    // Prefer a camera looking towards the property; never claim a facade match.
    return {row, distance, score: distance + angle * 0.6};
  }
  async function search(lat, lng) {
    if (!token) return {message: 'Photo preview needs a Mapillary token'};
    if (searches >= limit) return {message: 'Preview limit reached — reload to explore here'};
    searches++;
    const dy = 80 / 111320, dx = dy / Math.cos(radians(lat));
    const params = new URLSearchParams({access_token: token,
      bbox: [lng-dx, lat-dy, lng+dx, lat+dy].join(','), limit: '100',
      fields: 'id,geometry,computed_geometry,compass_angle,is_pano,captured_at,thumb_1024_url,creator'});
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('https://graph.mapillary.com/images?' + params, {signal: controller.signal});
      if (!response.ok) return {message: response.status === 429 ? 'Photos temporarily busy' : 'Photo service unavailable'};
      const data = await response.json();
      const candidates = (data.data || []).map(row => rank(row, lat, lng)).filter(Boolean).sort((a,b) => a.score-b.score);
      return candidates[0] || {message: 'No nearby street photo found'};
    } catch (_) { return {message: 'Photo service unavailable'}; }
    finally { clearTimeout(timer); }
  }
  function drain() {
    while (active < 3 && queue.length) {
      const job = queue.shift();
      if (!job.el.isConnected) { job.resolve(null); cache.delete(job.key); continue; }
      active++;
      search(job.lat, job.lng).then(job.resolve).finally(() => { active--; drain(); });
    }
  }
  function lookup(el) {
    const lat = Number(el.dataset.mlyLat), lng = Number(el.dataset.mlyLng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat)>85 || Math.abs(lng)>180)
      return Promise.resolve({message:'Street location unavailable'});
    const key = `${lat.toFixed(6)},${lng.toFixed(6)}`;
    if (!cache.has(key)) {
      if (cache.size >= 100) cache.delete(cache.keys().next().value);
      const promise = new Promise(resolve => queue.push({el, lat, lng, resolve, key}));
      cache.set(key, promise);
      drain();
    }
    return cache.get(key);
  }
  async function load(el) {
    const result = await lookup(el);
    if (!el.isConnected) return;
    if (!result) return load(el); // A queued copy was removed during a grid redraw.
    const status = el.querySelector('.mly-status');
    if (!result.row) { status.textContent = result.message; return; }
    const row = result.row, image = el.querySelector('img');
    const year = new Date(row.captured_at).getUTCFullYear();
    const credit = el.querySelector('.mly-credit');
    const username = row.creator?.username || 'Contributor';
    const source = credit.querySelector('.mly-source');
    source.href = 'https://www.mapillary.com/app/?pKey=' + encodeURIComponent(row.id) + '&focus=photo';
    source.textContent = 'Mapillary';
    const author = credit.querySelector('.mly-author');
    author.textContent = username;
    author.href = 'https://www.mapillary.com/app/user/' + encodeURIComponent(username);
    const label = el.querySelector('.mly-label');
    label.textContent = `Street nearby · ${Math.round(result.distance)}m${Number.isFinite(year) ? ' · '+year : ''}`;
    image.addEventListener('load', () => {
      status.hidden = true; credit.hidden = false; label.hidden = false; image.hidden = false;
    }, {once:true});
    image.addEventListener('error', () => { status.textContent = 'Photo unavailable'; }, {once:true});
    image.src = row.thumb_1024_url;
  }
  const observer = enabled && 'IntersectionObserver' in window
    ? new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { observer.unobserve(entry.target); observed.delete(entry.target); load(entry.target); }
    }), {rootMargin:'0px'}) : null;
  function watch(root) {
    if (!enabled) return;
    observed.forEach(el => { if (!el.isConnected) { observer.unobserve(el); observed.delete(el); } });
    root.querySelectorAll('[data-mly-lat]:not([data-mly-watched])').forEach(el => {
      el.dataset.mlyWatched = '1';
      el.querySelectorAll('a').forEach(a => a.addEventListener('click', e => e.stopPropagation()));
      if (observer) { observed.add(el); observer.observe(el); } else load(el);
    });
  }
  function html(rec) {
    if (!enabled) return '';
    if (rec.lat == null || rec.lng == null) return '<span class="mly-status">Street location unavailable</span>';
    return `<div class="mly-visual" data-mly-lat="${esc(rec.lat)}" data-mly-lng="${esc(rec.lng)}">
      <img hidden alt="Street near ${esc(rec.a || rec.address || rec.name || 'this property')}; building appearance not verified" decoding="async">
      <span class="mly-status">Loading street photo…</span>
      <span class="mly-label" hidden></span>
      <small class="mly-credit" hidden><a class="mly-source" target="_blank" rel="noopener"></a> / <a class="mly-author" target="_blank" rel="noopener"></a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">CC BY-SA</a></small>
    </div>`;
  }
  window.MapillaryPreview = {enabled, html, watch};
})();
