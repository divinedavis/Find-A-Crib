/* Apple Look Around photos. Uses Apple's supported renderer;
   does not extract, store, or rehost Apple imagery. */
(() => {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  const enabled = (local || ['findacrib.com', 'www.findacrib.com'].includes(location.hostname))
    && !(local && new URLSearchParams(location.search).get('photos') === 'mapillary');
  let storedToken = '';
  if (local) { try { storedToken = sessionStorage.getItem('fac.apple_maps_token') || ''; } catch (_) {} }
  const token = (window.APPLE_MAPS_TOKEN || storedToken).trim();
  const records = new Map(), queue = [];
  let loading = 0;
  const observers = new Map();
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function destroy(record) {
    record.cancel?.();
    try { record.view?.destroy(); } catch (_) {}
    record.view = null;
  }
  function prune() {
    records.forEach((record, el) => {
      if (!el.isConnected) { record.observer?.unobserve(el); destroy(record); records.delete(el); }
    });
    // Retain a few offscreen previews so small scrolls don't reload them.
    const mounted = [...records.values()].filter(r => r.view);
    for (const record of mounted) {
      if (mounted.filter(r => r.view).length < 12) break;
      if (!record.visible && !record.loading && !record.view.openDialog) destroy(record);
    }
  }
  async function mount(record) {
    const {el} = record, status = el.querySelector('.apple-street-status');
    if (!token) {
      status.innerHTML = local ? '<a href="/apple-preview/">Connect Apple Maps to preview photos</a>' : 'Street photo temporarily unavailable';
      record.failed = true; return;
    }
    status.hidden = false; status.textContent = 'Loading Apple street view…';
    record.loading = true;
    try {
      if (!el.isConnected || !record.visible) return;
      // MapKit supports one Look Around instance per document. Each tile gets
      // its own document and the browser caches the shared SDK files.
      const frame = document.createElement('iframe');
      frame.title = el.querySelector('.apple-street-canvas').getAttribute('aria-label');
      frame.src = '/static/apple-street-frame.html?v=3';
      frame.style.cssText = 'width:100%;height:100%;border:0;display:block;margin:0;padding:0';
      let expanded = false;
      function collapse() {
        if (!expanded) return;
        expanded = false;
        frame.hidePopover();
        frame.removeAttribute('popover');
        frame.style.width = frame.style.height = '100%';
        frame.contentWindow?.postMessage({type:'fac-apple-close'}, location.origin);
      }
      const escape = event => { if (event.key === 'Escape') collapse(); };
      record.view = {
        get openDialog() { return expanded; },
        close() { collapse(); },
        destroy() { collapse(); window.removeEventListener('keydown', escape); frame.remove(); }
      };
      window.addEventListener('keydown', escape);
      await new Promise(resolve => {
        let settled = false;
        const finish = message => {
          if (settled) return;
          settled = true; clearTimeout(timer); record.cancel = null;
          status.hidden = !message;
          if (message) { status.textContent = message; record.failed = true; }
          resolve();
        };
        const receive = event => {
          if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
          if (event.data?.type !== 'fac-apple-state') return;
          const state = event.data.state;
          if (state === 'complete') finish('');
          if (state === 'error') finish('Apple street imagery is unavailable here');
          if (state === 'browser-error') finish('Street photos are unavailable in this browser');
          if (state === 'open' && !expanded && frame.showPopover) {
            expanded = true;
            frame.popover = 'manual';
            frame.style.width = '100vw'; frame.style.height = '100dvh';
            frame.showPopover();
          }
          if (state === 'close') collapse();
        };
        window.addEventListener('message', receive);
        const remove = record.view.destroy;
        record.view.destroy = () => { window.removeEventListener('message', receive); remove(); };
        const timer = setTimeout(() => finish('Apple street view took too long to load'), 45000);
        record.cancel = () => finish('');
        frame.addEventListener('load', () => frame.contentWindow.postMessage({
          type:'fac-apple-init', token,
          lat:Number(el.dataset.appleLat), lng:Number(el.dataset.appleLng)
        }, location.origin), {once:true});
        el.querySelector('.apple-street-canvas').appendChild(frame);
      });
      if (record.failed) destroy(record);
    } catch (error) {
      status.textContent = error.message || 'Apple street view is unavailable';
      status.hidden = false; record.failed = true; destroy(record);
    } finally { record.loading = false; }
  }
  function onScreen(record) {
    const rect = record.el.getBoundingClientRect();
    const bounds = record.root?.getBoundingClientRect() || {top:0, bottom:innerHeight, left:0, right:innerWidth};
    return rect.width > 0 && rect.height > 0 && rect.bottom > Math.max(0, bounds.top)
      && rect.top < Math.min(innerHeight, bounds.bottom) && rect.right > Math.max(0, bounds.left)
      && rect.left < Math.min(innerWidth, bounds.right);
  }
  function drain() {
    prune();
    // Load visible photos first. Two slots may warm the next row.
    queue.sort((a,b) => Number(onScreen(b)) - Number(onScreen(a)));
    while (loading < 5 && queue.length) {
      const record = queue[0];
      if (!record.el.isConnected || !record.visible || record.view || record.failed || record.loading) {
        queue.shift(); record.queued = false; continue;
      }
      const prefetch = !onScreen(record);
      // Sorted on-screen first, so if this one is off screen none behind it
      // are either, and a record that already stalled off screen waits for the
      // scroll rather than taking a slot again.
      if (prefetch && (record.needsVisible
          || [...records.values()].filter(r => r.loading && !onScreen(r)).length >= 2)) break;
      queue.shift(); record.queued = false;
      loading++;
      // Safari does not run an iframe that is off screen: a preview started
      // below the fold never reports back, held its slot until the 45 s
      // timeout, and every card behind it waited (2026-09-15 — three photos
      // loaded and the rest sat on "Loading…"). Hand the slot back after 6 s
      // and let that card mount for real when it scrolls into view.
      const guard = prefetch ? setTimeout(() => {
        if (!record.loading || onScreen(record)) return;
        record.needsVisible = true;
        const status = record.el.querySelector('.apple-street-status');
        destroy(record);
        if (status) { status.hidden = false; status.textContent = 'Loading Apple street view…'; }
      }, 6000) : null;
      mount(record).finally(() => {
        clearTimeout(guard);
        loading--;
        if (record.visible && record.el.isConnected) enqueue(record);
        drain();
      });
    }
  }
  function enqueue(record) {
    if (record.queued || record.loading || record.view || record.failed) return;
    record.queued = true; queue.push(record);
  }
  function observerFor(root) {
    if (!enabled || !('IntersectionObserver' in window)) return null;
    if (!observers.has(root)) {
      observers.set(root, new IntersectionObserver(entries => {
        entries.forEach(entry => {
          const record = records.get(entry.target);
          if (!record) return;
          record.visible = entry.isIntersecting;
          if (record.visible) enqueue(record);
          // A quick scroll must not leave the new row waiting on old requests.
          else if (record.loading && !record.view?.openDialog) destroy(record);
        });
        drain();
      }, {root, rootMargin:root ? '350px 0px' : '0px'}));
    }
    return observers.get(root);
  }
  function watch(root) {
    if (!enabled) return;
    prune();
    root.querySelectorAll('[data-apple-lat]').forEach(el => {
      if (records.has(el)) return;
      const scrollRoot = el.closest('#grid');
      const observer = observerFor(scrollRoot);
      const record = {el, root:scrollRoot, observer, visible:!observer, view:null, queued:false, loading:false, failed:false};
      records.set(el, record);
      // Apple's controls open its own viewer; the address/body still opens building details.
      el.addEventListener('click', e => e.stopPropagation());
      if (observer) observer.observe(el); else enqueue(record);
    });
    drain();
  }
  function html(rec) {
    if (!enabled) return '';
    const lat=Number(rec.lat), lng=Number(rec.lng);
    if (rec.lat == null || rec.lng == null || rec.lat === '' || rec.lng === ''
      || !Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat)>90 || Math.abs(lng)>180)
      return '<span class="apple-street-status">Street location unavailable</span>';
    return `<div class="apple-street-preview" data-apple-lat="${lat}" data-apple-lng="${lng}">
      <div class="apple-street-canvas" aria-label="Apple street preview near ${esc(rec.a || rec.address || rec.name || 'this property')}"></div>
      <span class="apple-street-status" role="status">Loading Apple street view…</span>
    </div>`;
  }
  function release(root) {
    records.forEach((record, el) => {
      if (!root.contains(el)) return;
      record.observer?.unobserve(el); destroy(record); records.delete(el);
    });
  }
  function close(root) {
    records.forEach((record, el) => {
      if (root.contains(el)) record.view?.close?.();
    });
  }
  window.AppleStreetPreview = {enabled, provider:'apple', html, watch, release, close};
})();
