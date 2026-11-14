// Copy this file to config.js (gitignored) and fill in your own keys.
// config.js is loaded by index.html before the main script.
window.GMAPS_KEY = 'YOUR_GOOGLE_MAPS_API_KEY';

// Supabase project (Sign in + Saved buildings). The anon key is safe to expose in the browser.
window.SUPABASE_URL = 'https://YOUR_PROJECT_REF.supabase.co';
window.SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';

// CARTO Basemaps API key. Without it the map tiles come back stamped
// "API KEY REQUIRED" — CARTO bakes the watermark into the image, so no amount
// of referrer or caching work avoids it. Free to 5M tile requests/month, no
// account needed: https://carto.com/basemaps/apikey
window.CARTO_KEY = '';
