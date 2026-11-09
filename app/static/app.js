"use strict";
/* Foto-Globus – Oberfläche. Kein Build-Schritt: reines JavaScript + MapLibre GL (liegt im Paket). */
const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const state = { me: null, points: [], filtered: [], scope: "all", yearFrom: null, yearTo: null, map: null,
                panel: { photos: [], center: null, clusterId: null }, lb: -1, styleOnline: false };

// ---------- Verbindung zur App (direkt oder im DSM-Fenster über app.cgi) ----------
const session = {
  get() { try { return sessionStorage.getItem("fg_session") || ""; } catch (e) { return session.mem || ""; } },
  set(v) { session.mem = v; try { v ? sessionStorage.setItem("fg_session", v) : sessionStorage.removeItem("fg_session"); } catch (e) { /* egal */ } },
};
const PROXY = window.FG_PROXY || null;
const SYNO_TOKEN = (() => { try { return new URLSearchParams(location.search).get("SynoToken") || ""; } catch (e) { return ""; } })();
function authHeaders(extra = {}) {
  const h = { ...extra };
  const t = session.get();
  if (t) h["X-Session-Token"] = t;
  if (SYNO_TOKEN) h["X-SYNO-TOKEN"] = SYNO_TOKEN;
  return h;
}
function url(path) {
  if (!PROXY) return path;
  return `${PROXY}?${SYNO_TOKEN ? "SynoToken=" + encodeURIComponent(SYNO_TOKEN) + "&" : ""}p=${encodeURIComponent("/" + path)}`;
}
async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const extra = opts.body ? { "Content-Type": "application/json" } : {};
  let sendMethod = method;
  if (PROXY && ["PATCH", "PUT", "DELETE"].includes(method)) { sendMethod = "POST"; extra["X-HTTP-Method-Override"] = method; }
  let full = "api/v1/" + path;
  if (method === "GET") full += (full.includes("?") ? "&" : "?") + "_=" + Date.now();
  const res = await fetch(url(full), { credentials: "same-origin", cache: "no-store", method: sendMethod,
                                       headers: authHeaders(extra), body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401 && path !== "auth/login") { session.set(""); showLogin(); throw new Error("Nicht angemeldet"); }
  const data = (res.headers.get("content-type") || "").includes("json") ? await res.json() : null;
  if (!res.ok) {
    const d = data && data.detail;
    const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join(", ") : "Fehler " + res.status);
    err.status = res.status;
    throw err;
  }
  return data;
}
// Bilder mit Anmeldung laden (im DSM-Fenster gehen Cookies nicht immer mit) → Blob-Adresse
async function blobUrl(path) {
  const res = await fetch(url("api/v1/" + path), { credentials: "same-origin", headers: authHeaders() });
  if (!res.ok) throw new Error("Fehler " + res.status);
  return URL.createObjectURL(await res.blob());
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("de-DE");
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const deDate = (iso) => iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "";
const deDateTime = (iso) => iso ? `${deDate(iso)}${iso.length >= 16 ? ", " + iso.slice(11, 16) + " Uhr" : ""}` : "ohne Datum";
const monthYear = (iso) => iso ? `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : "";
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* egal */ } } };
const okMsg = (el, text) => { el.innerHTML = `<span class="ok">${esc(text)}</span>`; setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 4000); };

// ---------- Start & Anmeldung ----------
function showLogin() {
  $("appView").classList.add("hidden");
  $("loginView").classList.remove("hidden");
  setTimeout(() => $("lu").focus(), 50);
}

$("loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("loginErr").textContent = "";
  const body = { username: $("lu").value, password: $("lp").value };
  if (!$("otpWrap").classList.contains("hidden")) body.otp_code = $("lo").value.trim();
  try {
    const r = await api("auth/login", { method: "POST", body });
    session.set(r.session_token || "");
    $("lp").value = ""; $("lo").value = ""; $("otpWrap").classList.add("hidden");
    await start();
  } catch (e) {
    if (e.message === "otp_required") {
      $("otpWrap").classList.remove("hidden"); $("lo").focus();
      $("loginErr").textContent = "Bitte den Zwei-Faktor-Code deines DSM-Kontos eingeben.";
    } else $("loginErr").textContent = e.message;
  }
});

async function loadBranding() {
  try {
    const b = await api("branding");
    $$(".brandName").forEach(el => { el.textContent = b.company_name ? `${b.company_name} · Foto-Globus` : "Foto-Globus"; });
    if (b.logo) {
      const src = await blobUrl("branding/logo");
      $$(".brand").forEach(el => { el.classList.add("has-logo"); const img = el.querySelector(".brandLogo"); img.src = src; img.classList.remove("hidden"); });
    } else {
      $$(".brand").forEach(el => { el.classList.remove("has-logo"); el.querySelector(".brandLogo").classList.add("hidden"); });
    }
  } catch (e) { /* ohne Branding geht es auch */ }
}

async function start() {
  state.me = await api("me");
  if (window.fgTheme) fgTheme(state.me.theme_effective || "classic");
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  $("who").textContent = `${state.me.display_name}${state.me.is_admin ? " · Admin" : ""}${state.me.via_dsm ? " · über DSM" : ""}`;
  $("logoutBtn").classList.toggle("hidden", !!state.me.via_dsm);
  $$(".admin").forEach(el => el.classList.toggle("hidden", !state.me.is_admin));
  api("health").then(h => { $("version").textContent = "Version " + h.version; }).catch(() => {});
  await initMap();
  await loadPoints();
}

// ---------- Karte ----------
function offlineStyle() {
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  return {
    version: 8,
    // absolute Adresse: MapLibre lädt im Web-Worker, dort gelten relative Pfade nicht
    sources: { world: { type: "geojson", data: new URL(url("static/vendor/world.geojson"), location.href).href } },
    layers: [
      { id: "ocean", type: "background", paint: { "background-color": v("--ocean") } },
      { id: "land", type: "fill", source: "world", paint: { "fill-color": v("--land") } },
      { id: "borders", type: "line", source: "world", paint: { "line-color": v("--border"), "line-width": 0.6 } },
    ],
  };
}

async function onlineStyle(href) {
  if (!href) return null;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  try {
    const res = await fetch(href, { signal: ctl.signal, credentials: "omit" });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) { return null; } finally { clearTimeout(timer); }
}

// Pinnadeln werden im Browser gezeichnet (Kreis mit Spitze, Zahl darin) – so braucht es keine Schriften vom Kartenserver
function drawPin(label, variant) {
  const css = getComputedStyle(document.documentElement);
  const color = css.getPropertyValue(variant === "p" ? "--pin-me" : "--pin").trim() || "#e11d48";
  const r = 2;  // Pixeldichte
  const text = label === "1" ? "" : label;
  const head = text.length <= 1 ? 13 : text.length <= 3 ? 16 : 19;
  const w = (head * 2 + 6) * r, h = (head * 2 + 18) * r;
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d");
  g.scale(r, r);
  const cx = head + 3, cy = head + 3;
  g.shadowColor = "rgba(0,0,0,.35)"; g.shadowBlur = 4; g.shadowOffsetY = 1;
  g.beginPath();
  g.moveTo(cx, cy + head + 12);
  g.bezierCurveTo(cx - 4, cy + head + 2, cx - head, cy + head * 0.55, cx - head, cy);
  g.arc(cx, cy, head, Math.PI, 0);
  g.bezierCurveTo(cx + head, cy + head * 0.55, cx + 4, cy + head + 2, cx, cy + head + 12);
  g.fillStyle = color; g.fill();
  g.shadowColor = "transparent";
  g.lineWidth = 2; g.strokeStyle = "#fff"; g.stroke();
  if (text) {
    g.fillStyle = "#fff";
    g.font = `700 ${text.length <= 2 ? 12 : 11}px system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(text, cx, cy + 0.5);
  } else {
    g.beginPath(); g.arc(cx, cy, head * 0.38, 0, Math.PI * 2); g.fillStyle = "#fff"; g.fill();
  }
  return { width: w, height: h, data: g.getImageData(0, 0, w, h).data };
}

function esriStyle() {
  const base = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  return {
    version: 8,
    sources: {
      sat: { type: "raster", tileSize: 256, maxzoom: 19, tiles: [base + "World_Imagery/MapServer/tile/{z}/{y}/{x}"],
             attribution: "Satellitenbild: Esri, Maxar, Earthstar Geographics, GIS User Community" },
      labels: { type: "raster", tileSize: 256, maxzoom: 19, tiles: [base + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"] },
    },
    layers: [
      { id: "space", type: "background", paint: { "background-color": "#0b1220" } },
      { id: "sat", type: "raster", source: "sat" },
      { id: "labels", type: "raster", source: "labels", paint: { "raster-opacity": 0.85 } },
    ],
  };
}

async function styleFor(mode) {
  const cfg = state.mapCfg || {};
  if (mode === "sat" && cfg.satellite) {
    if (cfg.satellite.type === "esri") return { style: esriStyle(), online: true, sat: true };
    const ms = await onlineStyle(cfg.satellite.style);
    if (ms) return { style: ms, online: true, sat: true };
  }
  const online = await onlineStyle(cfg.style);
  return { style: online || offlineStyle(), online: !!online, sat: false };
}

// Eigene Ebenen (Länder, Pins, Route) – nach jedem Stilwechsel neu, die Karte vergisst sie dabei
function addOverlays() {
  const map = state.map;
  try { map.setProjection({ type: "globe" }); } catch (e) { /* ältere Browser: flache Karte */ }
  const worldUrl = new URL(url("static/vendor/world.geojson"), location.href).href;
  let countrySrc = "world";
  if (!map.getSource("world")) { map.addSource("countries", { type: "geojson", data: worldUrl }); countrySrc = "countries"; }
  const layers = map.getStyle().layers || [];
  const below = state.styleSat ? "labels" : (state.styleOnline ? (layers.find(l => l.type === "symbol") || {}).id : undefined);
  map.addLayer({ id: "visited", type: "fill", source: countrySrc, filter: ["in", ["get", "cc"], ["literal", []]],
                 paint: { "fill-color": accentColor(), "fill-opacity": state.styleSat ? 0.22 : state.styleOnline ? 0.18 : 0.28 } },
               below && map.getLayer(below) ? below : undefined);
  map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "route-casing", type: "line", source: "route", filter: ["==", ["geometry-type"], "LineString"],
                 layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "#fff", "line-width": 6, "line-opacity": 0.85 } });
  map.addLayer({ id: "route-line", type: "line", source: "route", filter: ["==", ["geometry-type"], "LineString"],
                 layout: { "line-join": "round", "line-cap": "round" },
                 paint: { "line-color": accentColor(), "line-width": 3.5, "line-dasharray": [2, 1.4] } });
  map.addLayer({ id: "route-stops", type: "circle", source: "route", filter: ["==", ["geometry-type"], "Point"],
                 paint: { "circle-radius": ["case", ["get", "end"], 7, 5], "circle-color": ["case", ["get", "end"], accentColor(), "#fff"],
                          "circle-stroke-color": accentColor(), "circle-stroke-width": 2.5 } });
  map.addSource("photos", {
    type: "geojson", data: geojson(state.filtered || []),
    cluster: true, clusterRadius: 46, clusterMaxZoom: 17,
    clusterProperties: { mine: ["+", ["case", ["==", ["get", "s"], "p"], 1, 0]] },
  });
  map.addLayer({
    id: "clusters", type: "symbol", source: "photos", filter: ["has", "point_count"],
    layout: {
      "icon-image": ["concat", "pin|", ["to-string", ["get", "point_count_abbreviated"]], "|",
                     ["case", ["==", ["get", "mine"], ["get", "point_count"]], "p", "s"]],
      "icon-anchor": "bottom", "icon-allow-overlap": true, "symbol-sort-key": ["-", 0, ["get", "point_count"]],
    },
  });
  map.addLayer({
    id: "photo", type: "symbol", source: "photos", filter: ["!", ["has", "point_count"]],
    layout: { "icon-image": ["concat", "pin|1|", ["get", "s"]], "icon-anchor": "bottom", "icon-allow-overlap": true },
  });
  // Heatmap: eigene, nicht zusammengefasste Quelle; Umschalter blendet Pins bzw. Heatmap aus
  const firstPinLayer = "clusters";
  map.addSource("heat", { type: "geojson", data: geojson(state.filtered || []) });
  map.addLayer({
    id: "heat", type: "heatmap", source: "heat",
    paint: {
      "heatmap-weight": 1,
      "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 6, 1.4, 12, 3],
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 10, 4, 18, 9, 28, 14, 40],
      "heatmap-opacity": 0.85,
      "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"],
        0, "rgba(0,0,0,0)", 0.15, "rgba(45,212,191,0.55)", 0.35, "#22c55e", 0.55, "#facc15", 0.75, "#f97316", 1, "#dc2626"],
    },
  }, firstPinLayer);
  applyHeatMode();
  updateVisited();
  if (state.routeData) map.getSource("route").setData(state.routeData);
}

function applyHeatMode() {
  const map = state.map;
  if (!map || !map.getLayer("heat")) return;
  const heat = store.get("fg_heat") === "1";
  map.setLayoutProperty("heat", "visibility", heat ? "visible" : "none");
  for (const id of ["clusters", "photo"]) map.setLayoutProperty(id, "visibility", heat ? "none" : "visible");
  const b = $("heatBtn");
  b.textContent = heat ? "📍" : "🔥";
  b.title = heat ? "Pinnadeln zeigen" : "Heatmap zeigen";
  b.setAttribute("aria-label", b.title);
}

async function initMap() {
  if (state.map) return;
  try { state.mapCfg = await api("map-config"); } catch (e) { state.mapCfg = { style: "" }; }
  const mode = state.mapCfg.satellite && store.get("fg_map") === "sat" ? "sat" : "map";
  const st = await styleFor(mode);
  state.styleOnline = st.online; state.styleSat = st.sat;
  $("mapBtn").classList.toggle("hidden", !state.mapCfg.satellite);
  setMapBtn();
  const map = new maplibregl.Map({
    container: "map",
    style: st.style,
    center: [10, 30], zoom: window.innerWidth < 720 ? 0.35 : 1.6,
    attributionControl: { compact: true },
    renderWorldCopies: false,
    maxPitch: 60,
  });
  state.map = map;
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
  map.on("styleimagemissing", (e) => {
    const m = /^pin\|(.+)\|([ps])$/.exec(e.id);
    if (m && !map.hasImage(e.id)) map.addImage(e.id, drawPin(m[1], m[2]), { pixelRatio: 2 });
  });
  await new Promise((resolve) => map.on("load", resolve));
  addOverlays();
  for (const layer of ["clusters", "photo"]) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", "clusters", async (e) => {
    if (state.pickHome) return;
    const f = e.features[0];
    const src = map.getSource("photos");
    const leaves = await src.getClusterLeaves(f.properties.cluster_id, 2000, 0);
    openPanel(leaves.map(l => l.properties.id), f.geometry.coordinates, f.properties.cluster_id, f.properties.point_count);
  });
  map.on("click", "photo", (e) => {
    if (state.pickHome) return;
    const f = e.features[0];
    openPanel([f.properties.id], f.geometry.coordinates, null, 1);
  });
  map.on("click", (e) => { if (state.pickHome) state.pickHome(e.lngLat); });
}

function setMapBtn() {
  const b = $("mapBtn");
  b.textContent = state.styleSat ? "🗺️" : "🛰️";
  b.title = state.styleSat ? "Karte zeigen" : "Satellitenbild zeigen";
  b.setAttribute("aria-label", b.title);
}

async function switchMapMode() {
  const want = state.styleSat ? "map" : "sat";
  const st = await styleFor(want);
  state.styleOnline = st.online; state.styleSat = st.sat;
  store.set("fg_map", st.sat ? "sat" : "map");
  setMapBtn();
  state.map.setStyle(st.style, { diff: false });
  state.map.once("style.load", addOverlays);
}

function geojson(points) {
  return { type: "FeatureCollection", features: points.map(p => ({
    type: "Feature", geometry: { type: "Point", coordinates: [p[2], p[1]] }, properties: { id: p[0], s: p[4] } })) };
}
const accentColor = () => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#0f766e";
const showVisited = () => store.get("fg_visited") !== "0";
function updateVisited() {
  const map = state.map;
  if (!map || !map.getLayer("visited")) return;
  const ccs = showVisited() ? [...new Set(state.filtered.map(p => p[7]).filter(Boolean))] : [];
  map.setFilter("visited", ["in", ["get", "cc"], ["literal", ccs]]);
  map.setPaintProperty("visited", "fill-color", accentColor());
}

function applyFilter(fit = false) {
  const { yearFrom, yearTo, scope } = state;
  state.filtered = state.tripIds
    ? state.points.filter(p => state.tripIds.has(p[0]))
    : state.points.filter(p => (scope === "all" || p[4] === scope)
      && (!yearFrom || (p[5] || 0) >= yearFrom) && (!yearTo || (p[5] || 9999) <= yearTo));
  const src = state.map && state.map.getSource("photos");
  if (src) src.setData(geojson(state.filtered));
  const heat = state.map && state.map.getSource("heat");
  if (heat) heat.setData(geojson(state.filtered));
  updateVisited();
  if (!$("stats").classList.contains("hidden")) loadStats();
  const n = state.filtered.length;
  $("countChip").textContent = `${state.tripIds ? "Reise: " : ""}${nf.format(n)} Foto${n === 1 ? "" : "s"}`;
  $("countChip").title = state.withoutGps ? `${nf.format(state.withoutGps)} Fotos ohne Aufnahmeort werden nicht angezeigt` : "";
  if (fit) flyHome(true);
}

function centroid(points) {
  if (!points.length) return [10, 30];
  // Mittelpunkt über Einheitsvektoren (funktioniert auch über die Datumsgrenze hinweg)
  let x = 0, y = 0, z = 0;
  for (const p of points) {
    const la = p[1] * Math.PI / 180, lo = p[2] * Math.PI / 180;
    x += Math.cos(la) * Math.cos(lo); y += Math.cos(la) * Math.sin(lo); z += Math.sin(la);
  }
  const lo = Math.atan2(y, x), hyp = Math.sqrt(x * x + y * y), la = Math.atan2(z, hyp);
  return [lo * 180 / Math.PI, Math.max(-60, Math.min(60, la * 180 / Math.PI))];
}

function flyHome(instant = false) {
  if (!state.map) return;
  const opts = { center: centroid(state.filtered.length ? state.filtered : state.points), zoom: window.innerWidth < 720 ? 0.35 : 1.6, pitch: 0, bearing: 0 };
  instant ? state.map.jumpTo(opts) : state.map.flyTo({ ...opts, duration: 1600 });
}

function fillYears(years) {
  const opts = (sel, value) => `<option value="">${sel === "from" ? "von" : "bis"}</option>` +
    years.map(y => `<option${y === value ? " selected" : ""}>${y}</option>`).join("");
  $("yearFrom").innerHTML = opts("from", state.yearFrom);
  $("yearTo").innerHTML = opts("to", state.yearTo);
}

function notice(html) {
  $("notice").innerHTML = html || "";
  $("notice").classList.toggle("hidden", !html);
}

async function loadPoints() {
  try {
    const r = await api("points");
    state.points = r.points;
    state.withoutGps = r.without_gps;
    state.years = r.years;
    fillYears(r.years);
    applyFilter(true);
    if (!r.points.length) {
      notice(state.me.is_admin
        ? "Noch keine Fotos mit Aufnahmeort. Läuft die erste Suche noch? Stand unter <b>☰ → Einstellungen → Suche</b>."
        : "Noch keine Fotos mit Aufnahmeort gefunden. Die Suche läuft jede Nacht – oder frag den Admin.");
    } else notice("");
  } catch (e) {
    if (e.status === 403) {
      fillYears([]);
      notice(`${esc(e.message)}${state.me.is_admin ? "<br><span class='small muted'>Als lokaler Admin kannst du hier nur die Einstellungen verwalten.</span>" : ""}`);
      applyFilter();
    } else notice(esc(e.message));
  }
}

$("yearFrom").addEventListener("change", () => { state.yearFrom = Number($("yearFrom").value) || null; applyFilter(); });
$("yearTo").addEventListener("change", () => { state.yearTo = Number($("yearTo").value) || null; applyFilter(); });
$$(".seg button").forEach(b => b.addEventListener("click", () => {
  $$(".seg button").forEach(x => x.classList.toggle("on", x === b));
  state.scope = b.dataset.scope;
  applyFilter();
}));
$("homeBtn").addEventListener("click", () => flyHome());
$("mapBtn").addEventListener("click", () => switchMapMode());
$("heatBtn").addEventListener("click", () => {
  const on = store.get("fg_heat") !== "1";
  store.set("fg_heat", on ? "1" : "0");
  applyHeatMode();
  if (on && !store.get("fg_heat_hint")) {
    notice("Heatmap: je wärmer die Farbe, desto mehr Fotos. Zum Öffnen der Fotos wieder auf 📍 Pinnadeln umschalten.");
    store.set("fg_heat_hint", "1");
    setTimeout(() => notice(""), 6000);
  }
});

// ---------- Galerie einer Pinnadel ----------
const thumbQueue = { active: 0, waiting: [], max: 6 };
function queueThumb(img, id) {
  const run = async () => {
    thumbQueue.active++;
    try {
      img.src = await blobUrl(`photos/${id}/thumb/sm`);
      img.onload = () => img.classList.add("loaded");
    } catch (e) {
      img.replaceWith(Object.assign(document.createElement("span"), { className: "noimg", textContent: "keine Vorschau" }));
    } finally {
      thumbQueue.active--;
      const next = thumbQueue.waiting.shift();
      if (next) next();
    }
  };
  thumbQueue.active < thumbQueue.max ? run() : thumbQueue.waiting.push(run);
}
const lazy = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  for (const en of entries) {
    if (!en.isIntersecting) continue;
    lazy.unobserve(en.target);
    queueThumb(en.target.querySelector("img"), en.target.dataset.id);
  }
}, { root: $("grid"), rootMargin: "300px" }) : null;

function placeTitle(photos, total) {
  const counts = new Map();
  for (const p of photos) if (p.place_label) counts.set(p.place_label, (counts.get(p.place_label) || 0) + 1);
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return `${nf.format(total)} Foto${total === 1 ? "" : "s"}`;
  return sorted.length === 1 ? sorted[0][0] : `${sorted[0][0]} + ${sorted.length - 1} weitere${sorted.length === 2 ? "r Ort" : " Orte"}`;
}
function countText(photos) {
  const v = photos.filter(p => p.media === "video").length, f = photos.length - v;
  return [f ? `${nf.format(f)} Foto${f === 1 ? "" : "s"}` : "", v ? `${nf.format(v)} Video${v === 1 ? "" : "s"}` : ""].filter(Boolean).join(", ");
}
const fmtDur = (s) => s == null ? "" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
function rangeText(photos) {
  const dates = photos.map(p => p.taken_at).filter(Boolean).sort();
  if (!dates.length) return "";
  const a = monthYear(dates[0]), b = monthYear(dates[dates.length - 1]);
  return a === b ? a : `${a} – ${b}`;
}

async function openPanel(ids, center, clusterId, total, title) {
  thumbQueue.waiting.length = 0;
  for (const img of $$("#grid img")) if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
  state.panel = { photos: [], center, clusterId };
  if (window.innerWidth < 720) $("stats").classList.add("hidden");
  $("panel").classList.remove("hidden");
  $("panelTitle").textContent = `${nf.format(total)} Foto${total === 1 ? "" : "s"}`;
  $("panelSub").textContent = "wird geladen …";
  $("grid").innerHTML = "";
  $("gridMore").textContent = "";
  $("zoomHere").classList.toggle("hidden", clusterId === null);
  let photos = [];
  try { photos = await api("photos/info", { method: "POST", body: { ids: ids.slice(0, 2000) } }); }
  catch (e) { $("panelSub").textContent = e.message; return; }
  state.panel.photos = photos;
  $("panelTitle").textContent = title || placeTitle(photos, total);
  $("panelSub").textContent = [countText(photos), rangeText(photos)].filter(Boolean).join(" · ");
  if (total > photos.length) $("gridMore").textContent = `Hier werden die ersten ${nf.format(photos.length)} gezeigt – hineinzoomen für den Rest.`;
  // Überschriften: bei wenigen Tagen pro Tag, sonst pro Monat
  const days = new Set(photos.map(p => (p.taken_at || "").slice(0, 10)));
  const byMonth = days.size > 6;
  const groupOf = (p) => (p.taken_at || "").slice(0, byMonth ? 7 : 10);
  const groupName = (g) => !g ? "Ohne Datum" : byMonth ? monthYear(g + "-01") : deDate(g);
  let lastGroup = null;
  const frag = document.createDocumentFragment();
  photos.forEach((p, i) => {
    const g = groupOf(p);
    if (g !== lastGroup && photos.length > 1) {
      frag.appendChild(Object.assign(document.createElement("div"), { className: "day", textContent: groupName(g) }));
      lastGroup = g;
    }
    // div statt button: Buttons ignorieren in manchen Browsern das quadratische Seitenverhältnis
    const b = document.createElement("div");
    b.className = "tile"; b.dataset.id = p.id; b.title = p.name;
    b.tabIndex = 0; b.setAttribute("role", "button");
    b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightbox(i); } });
    b.innerHTML = `<img alt="${esc(p.name)}">${p.scope === "personal" ? "" : '<span class="badge">gemeinsam</span>'}` +
      (p.media === "video" ? `<span class="play"><i>▶</i></span><span class="dur">${fmtDur(p.duration)}</span>` : "");
    b.addEventListener("click", () => openLightbox(i));
    frag.appendChild(b);
    if (lazy) lazy.observe(b); else queueThumb(b.querySelector("img"), p.id);
  });
  $("grid").appendChild(frag);
  $("grid").scrollTop = 0;
}

$("panelClose").addEventListener("click", () => $("panel").classList.add("hidden"));
$("zoomHere").addEventListener("click", async () => {
  const { clusterId, center } = state.panel;
  if (clusterId === null) return;
  const zoom = await state.map.getSource("photos").getClusterExpansionZoom(clusterId);
  state.map.flyTo({ center, zoom: Math.min(zoom + 0.5, 18), duration: 1400 });
  $("panel").classList.add("hidden");
});

// ---------- Großansicht ----------
let lbUrl = null;
async function showLb(i) {
  const photos = state.panel.photos;
  if (i < 0 || i >= photos.length) return;
  state.lb = i;
  const p = photos[i];
  $("lightbox").classList.remove("hidden");
  $("lbName").textContent = p.name;
  $("lbPos").textContent = photos.length > 1 ? `${i + 1} / ${photos.length}` : "";
  const bits = [];
  if (p.place_label) bits.push(`<b>${esc(p.place_label)}</b>`);
  bits.push(deDateTime(p.taken_at));
  if (p.media === "video" && p.duration) bits.push(`Video ${fmtDur(p.duration)}`);
  if (p.camera) bits.push(esc(p.camera));
  if (p.width && p.height) bits.push(`${p.width} × ${p.height}`);
  bits.push(`${p.scope === "personal" ? "Meine Fotos" : "Gemeinsame Fotos"}${p.folder ? " / " + esc(p.folder) : ""}`);
  bits.push(`${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}${p.alt ? ` · ${Math.round(p.alt)} m` : ""}`);
  $("lbMeta").innerHTML = bits.join(" · ");
  $("lbPhotos").classList.toggle("hidden", !(PROXY || (state.mapCfg && state.mapCfg.photos_url)));
  $("lbPrev").disabled = i === 0;
  $("lbNext").disabled = i === photos.length - 1;
  const img = $("lbImg"), vid = $("lbVideo");
  img.removeAttribute("src");
  vid.pause(); vid.removeAttribute("src"); vid.load();
  vid.classList.add("hidden"); $("lbVideoMsg").classList.add("hidden"); img.classList.remove("hidden");
  if (p.media === "video") return showVideo(p, i);
  try {
    const u = await blobUrl(`photos/${p.id}/thumb/xl`);
    if (state.lb !== i) { URL.revokeObjectURL(u); return; }
    if (lbUrl) URL.revokeObjectURL(lbUrl);
    lbUrl = u; img.src = u;
  } catch (e) { img.alt = "Keine Vorschau vorhanden"; }
}
async function showVideo(p, i) {
  const img = $("lbImg"), vid = $("lbVideo"), msg = $("lbVideoMsg");
  try {
    const t = await api(`photos/${p.id}/video-token`);
    if (state.lb !== i) return;
    if (!t.playable) throw new Error("Dieses Video kann der Browser nicht abspielen – bitte herunterladen.");
    img.classList.add("hidden");
    try { vid.poster = await blobUrl(`photos/${p.id}/thumb/xl`); } catch (e) { vid.removeAttribute("poster"); }
    vid.src = url(`api/v1/photos/${p.id}/video?vt=${encodeURIComponent(t.token)}`);
    vid.classList.remove("hidden");
    vid.onerror = () => {
      vid.classList.add("hidden");
      msg.textContent = "Das Video lässt sich hier nicht abspielen (z. B. HEVC/H.265 in diesem Browser). Bitte herunterladen.";
      msg.classList.remove("hidden");
    };
  } catch (e) {
    img.classList.add("hidden");
    msg.textContent = e.message; msg.classList.remove("hidden");
  }
}
function openLightbox(i) { showLb(i); }
function closeLightbox() { $("lightbox").classList.add("hidden"); state.lb = -1; const v = $("lbVideo"); v.pause(); v.removeAttribute("src"); v.load(); }
$("lbClose").addEventListener("click", closeLightbox);
$("lbPrev").addEventListener("click", () => showLb(state.lb - 1));
$("lbNext").addEventListener("click", () => showLb(state.lb + 1));
$("lbMap").addEventListener("click", () => {
  const p = state.panel.photos[state.lb];
  closeLightbox();
  state.map.flyTo({ center: [p.lon, p.lat], zoom: 14, duration: 1800 });
  $("stats").classList.add("hidden");
});
$("lbDownload").addEventListener("click", async () => {
  const p = state.panel.photos[state.lb];
  const btn = $("lbDownload");
  btn.disabled = true;
  try {
    const u = await blobUrl(`photos/${p.id}/original`);
    const a = Object.assign(document.createElement("a"), { href: u, download: p.name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 10000);
  } catch (e) { alert("Download fehlgeschlagen: " + e.message); } finally { btn.disabled = false; }
});
// In Synology Photos öffnen: im DSM-Fenster den Ordner des Fotos (Ordner-ID über die Photos-Schnittstelle, nur lesend),
// sonst bzw. wenn das nicht klappt den richtigen Bereich (persönlich/gemeinsam).
async function photosFolderId(space, folder) {
  const apiName = space === "personal_space" ? "SYNO.Foto.Browse.Folder" : "SYNO.FotoTeam.Browse.Folder";
  const call = async (params) => {
    const q = new URLSearchParams({ api: apiName, version: "1", ...params });
    if (SYNO_TOKEN) q.set("SynoToken", SYNO_TOKEN);
    const res = await fetch(`/webapi/entry.cgi?${q}`, { credentials: "same-origin", headers: SYNO_TOKEN ? { "X-SYNO-TOKEN": SYNO_TOKEN } : {} });
    const j = await res.json();
    if (!j.success) throw new Error("Photos-API: " + JSON.stringify(j.error || {}));
    return (j.data && j.data.list) || [];
  };
  const parts = folder.split("/").filter(Boolean);
  let level = await call({ method: "list_parents" });
  let found = null;
  for (let k = 0; k < parts.length; k++) {
    const want = "/" + parts.slice(0, k + 1).join("/");
    found = level.find(f => f.name === want);
    if (!found) return null;
    if (k < parts.length - 1) {
      level = [];
      for (let off = 0; ; off += 500) {
        const page = await call({ method: "list", id: String(found.id), offset: String(off), limit: "500" });
        level = level.concat(page);
        if (page.length < 500) break;
      }
    }
  }
  return found ? found.id : null;
}
$("lbPhotos").addEventListener("click", async () => {
  const p = state.panel.photos[state.lb];
  const space = p.scope === "personal" ? "personal_space" : "shared_space";
  const tab = window.open("about:blank", "_blank");  // sofort öffnen, sonst blockt der Browser das Fenster
  let target;
  if (PROXY) {
    let id = null;
    try { id = p.folder ? await photosFolderId(space, p.folder) : null; } catch (e) { console.warn(e); }
    target = `/photo/#/${space}${id ? "/folder/" + id : ""}`;
  } else {
    target = `${state.mapCfg.photos_url}/#/${space}`;
  }
  if (tab) tab.location.href = new URL(target, location.href).href; else location.href = target;
});

// Wischen auf dem Handy
(() => {
  let x0 = null;
  $("lightbox").addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  $("lightbox").addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50) showLb(state.lb + (dx < 0 ? 1 : -1));
    x0 = null;
  });
})();
document.addEventListener("keydown", (e) => {
  if (!$("lightbox").classList.contains("hidden")) {
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") showLb(state.lb - 1);
    if (e.key === "ArrowRight") showLb(state.lb + 1);
  } else if (e.key === "Escape") {
    if (!$("dialog").classList.contains("hidden")) closeDialog();
    else if (!$("menu").classList.contains("hidden")) $("menu").classList.add("hidden");
    else $("panel").classList.add("hidden");
  }
});

// ---------- Menü ----------
$("menuBtn").addEventListener("click", (e) => { e.stopPropagation(); $("menu").classList.toggle("hidden"); });
document.addEventListener("click", (e) => { if (!$("menu").contains(e.target)) $("menu").classList.add("hidden"); });
$("logoutBtn").addEventListener("click", async () => {
  try { await api("auth/logout", { method: "POST" }); } catch (e) { /* egal */ }
  session.set("");
  location.reload();
});
$$("[data-open]").forEach(b => b.addEventListener("click", () => {
  $("menu").classList.add("hidden");
  b.dataset.open === "profile" ? openProfile() : openSettings();
}));

function openDialog(title, html) {
  $("dialogTitle").textContent = title;
  $("dialogBody").innerHTML = html;
  $("dialog").classList.remove("hidden");
}
function closeDialog() { $("dialog").classList.add("hidden"); clearInterval(state.scanTimer); }
$("dialogClose").addEventListener("click", closeDialog);
$("dialog").addEventListener("click", (e) => { if (e.target === $("dialog")) closeDialog(); });

const THEMES = [["classic", "Klassisch", ["#f4f5f7", "#0f766e", "#e11d48"]], ["dsm", "Synology DSM", ["#eef2f7", "#057feb", "#d1342c"]],
                ["dark", "Nacht (dunkel)", ["#0b0d10", "#f5a524", "#34d399"]], ["warm", "Warm & groß", ["#f6efe4", "#b5400b", "#13702f"]]];
function themePicker(current, withDefault) {
  return `<div class="themes">${withDefault ? `<button class="theme-opt${current ? "" : " on"}" data-theme=""><div class="sw" style="background:linear-gradient(135deg,#ddd,#999)"></div>Standard</button>` : ""}
    ${THEMES.map(([k, n, c]) => `<button class="theme-opt${current === k ? " on" : ""}" data-theme="${k}"><div class="sw">${c.map(x => `<i style="background:${x}"></i>`).join("")}</div>${n}</button>`).join("")}</div>`;
}
function openProfile() {
  openDialog("Design", `<p class="muted small">Gilt nur für dich. „Standard“ übernimmt die Vorgabe des Admins.</p>${themePicker(state.me.theme, true)}<div class="err" id="profErr"></div>`);
  $$("#dialogBody .theme-opt").forEach(b => b.addEventListener("click", async () => {
    try {
      state.me = await api("me", { method: "PATCH", body: { theme: b.dataset.theme || null } });
      fgTheme(state.me.theme_effective);
      $$("#dialogBody .theme-opt").forEach(x => x.classList.toggle("on", x === b));
      repaintMap();
    } catch (e) { $("profErr").textContent = e.message; }
  }));
}
function repaintMap() {
  // Pins und Offline-Kugel an die neuen Farben anpassen
  const map = state.map;
  if (!map) return;
  for (const id of map.listImages()) if (id.startsWith("pin|")) map.removeImage(id);
  if (!state.styleOnline && map.getLayer("ocean")) {
    const s = offlineStyle();
    map.setPaintProperty("ocean", "background-color", s.layers[0].paint["background-color"]);
    map.setPaintProperty("land", "fill-color", s.layers[1].paint["fill-color"]);
    map.setPaintProperty("borders", "line-color", s.layers[2].paint["line-color"]);
  }
  map.getSource("photos").setData(geojson(state.filtered));
  updateVisited();
}

// ---------- Einstellungen (Admins) ----------
const TABS = [["scan", "Suche"], ["folders", "Ordner & Rechte"], ["general", "Karte & Anmeldung"], ["look", "Darstellung"],
              ["backup", "Sicherung"], ["users", "Benutzer"], ["audit", "Protokoll"], ["updates", "Updates"]];
async function openSettings(tab = "scan") {
  openDialog("Einstellungen", `<div class="subnav">${TABS.map(([k, n]) => `<button data-tab="${k}"${k === tab ? ' class="on"' : ""}>${n}</button>`).join("")}</div><div id="tabBody"></div>`);
  $$("#dialogBody [data-tab]").forEach(b => b.addEventListener("click", () => {
    $$("#dialogBody [data-tab]").forEach(x => x.classList.toggle("on", x === b));
    showTab(b.dataset.tab);
  }));
  showTab(tab);
}
async function showTab(tab) {
  clearInterval(state.scanTimer);
  const body = $("tabBody");
  body.innerHTML = '<p class="muted">Lädt …</p>';
  try { await ({ scan: tabScan, folders: tabFolders, general: tabGeneral, look: tabLook, backup: tabBackup,
                 users: tabUsers, audit: tabAudit, updates: tabUpdates })[tab](body); }
  catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
const chk = (id, on, text) => `<label class="inline"><input type="checkbox" id="${id}"${on ? " checked" : ""}> ${text}</label>`;
async function saveSettings(patch, msgEl) {
  try { const s = await api("settings", { method: "PATCH", body: patch }); okMsg(msgEl, "Gespeichert"); return s; }
  catch (e) { msgEl.innerHTML = `<span class="err">${esc(e.message)}</span>`; return null; }
}

async function tabScan(body) {
  const render = (s) => {
    const t = s.totals;
    const runs = s.runs.map(r => `<tr><td>${deDateTime(r.started_at)}</td><td>${esc(r.trigger || "")}</td><td>${esc(r.status)}</td>
      <td>${nf.format(r.files_seen)}</td><td>${nf.format(r.files_new)} / ${nf.format(r.files_changed)} / ${nf.format(r.files_removed)}</td>
      <td>${r.errors ? `<details><summary>${r.errors}</summary><pre class="raw">${esc(r.error_text || "")}</pre></details>` : "–"}</td></tr>`).join("");
    body.innerHTML = `
      <div class="stats">
        <div class="stat"><b>${nf.format(t.photos)}</b>Fotos im Index</div>
        <div class="stat"><b>${nf.format(t.with_gps)}</b>mit Aufnahmeort</div>
        <div class="stat"><b>${nf.format(t.shared)}</b>gemeinsam</div>
        <div class="stat"><b>${nf.format(t.personal)}</b>persönlich</div>
        <div class="stat" title="Exakte Kopien (gleicher Inhalt) werden auf dem Globus, in Galerie, Statistik und Reisen nur einmal gezählt – die eigene Kopie zuerst."><b>${nf.format(t.duplicates || 0)}</b>doppelte Dateien (nur einmal gezeigt)</div>
      </div>
      <div class="row">${s.running
        ? `<b>Suche läuft …</b> <span class="muted">${nf.format(s.files_done || 0)} Dateien, ${s.seconds || 0} s</span> <span class="muted small">${esc(s.root || "")}</span> <button id="scanStop" class="danger">Abbrechen</button>`
        : `<button id="scanNow" class="primary">Jetzt nach Fotos suchen</button><span class="muted small">Beim zweiten Mal werden nur neue und geänderte Dateien gelesen.</span>`}</div>
      <h3>Letzte Durchläufe</h3>
      <div class="scroll"><table><tr><th>Start</th><th>Anlass</th><th>Status</th><th>Dateien</th><th>neu / geändert / entfernt</th><th>Fehler</th></tr>${runs || '<tr><td colspan="6" class="muted">Noch keine</td></tr>'}</table></div>
      <div class="err" id="scanErr"></div>`;
    if ($("scanNow")) $("scanNow").addEventListener("click", async () => {
      try { render(await api("scan", { method: "POST" })); } catch (e) { $("scanErr").textContent = e.message; }
    });
    if ($("scanStop")) $("scanStop").addEventListener("click", async () => render(await api("scan", { method: "DELETE" })));
  };
  let wasRunning = false;
  const refresh = async () => {
    const s = await api("scan");
    render(s);
    if (wasRunning && !s.running) loadPoints();  // fertig → Globus neu laden
    wasRunning = s.running;
  };
  await refresh();
  state.scanTimer = setInterval(() => { if ($("tabBody") && !$("dialog").classList.contains("hidden")) refresh().catch(() => {}); }, 2000);
}

async function tabFolders(body) {
  const s = await api("settings");
  body.innerHTML = `
    <div class="setgrid">
      <fieldset><legend>Fotoordner</legend>
        ${chk("sShared", s.scan_shared === "1", "Gemeinsame Fotos durchsuchen")}
        <label>Ordner der gemeinsamen Fotos <input id="sSharedRoot" value="${esc(s.shared_root)}" placeholder="automatisch: ${esc(s.detected.shared_root || "nicht gefunden")}"></label>
        ${chk("sPersonal", s.scan_personal === "1", "Persönliche Fotos aller Benutzer durchsuchen")}
        <label>Ordner der Benutzer-Verzeichnisse <input id="sHomesRoot" value="${esc(s.homes_root)}" placeholder="automatisch: ${esc(s.detected.homes_root || "nicht gefunden")}"></label>
        <p class="muted small">Leer = automatisch (<code>/volume*/photo</code> und <code>/volume*/homes/&lt;benutzer&gt;/Photos</code>).
          Der Paketbenutzer <b>fotoglobus</b> braucht dafür Leserechte: DSM → Systemsteuerung → Freigegebener Ordner → <i>photo</i> bzw. <i>homes</i> → Bearbeiten → Berechtigungen → „Interner Systembenutzer“ → bei <b>fotoglobus</b> den Haken bei <b>Schreibgeschützt</b> setzen.</p>
      </fieldset>
      <fieldset><legend>Nächtliche Suche</legend>
        ${chk("sScanOn", s.scan_enabled === "1", "Jede Nacht nach neuen Fotos suchen")}
        <label>Uhrzeit <select id="sScanHour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}"${String(h) === s.scan_hour ? " selected" : ""}>${String(h).padStart(2, "0")}:00 Uhr</option>`).join("")}</select></label>
      </fieldset>
      <fieldset><legend>Wer sieht gemeinsame Fotos?</legend>
        <label class="inline"><input type="radio" name="sAccess" value="acl"${s.share_access === "acl" ? " checked" : ""}> Nach den Ordnerrechten in DSM (empfohlen)</label>
        <label class="inline"><input type="radio" name="sAccess" value="all"${s.share_access === "all" ? " checked" : ""}> Alle angemeldeten DSM-Benutzer</label>
        <p class="muted small">Persönliche Fotos sieht immer nur der Besitzer. Das lokale Konto „admin“ sieht keine Fotos.</p>
      </fieldset>
      <fieldset><legend>Rechte testen</legend>
        <p class="muted small">Zeigt, was DSM zu einem Ordner sagt – hilfreich, wenn jemand Fotos nicht sieht.</p>
        <label>DSM-Benutzer <input id="tUser" placeholder="z. B. anna"></label>
        <label>Ordner unterhalb der gemeinsamen Fotos <input id="tFolder" placeholder="z. B. Urlaub/2024"></label>
        <button id="tRun">Prüfen</button>
        <div id="tOut" class="small"></div>
      </fieldset>
    </div>
    <p class="muted small">Gefundene Bereiche: ${s.roots.length ? s.roots.map(r => `<code>${esc(r.path)}</code>`).join(" ") : "keine"}</p>
    <div class="savebar"><button class="primary" id="sSave">Speichern</button><span id="sMsg"></span></div>`;
  $("sSave").addEventListener("click", async () => {
    const r = await saveSettings({
      scan_shared: $("sShared").checked, scan_personal: $("sPersonal").checked,
      shared_root: $("sSharedRoot").value.trim(), homes_root: $("sHomesRoot").value.trim(),
      scan_enabled: $("sScanOn").checked, scan_hour: Number($("sScanHour").value),
      share_access: ($$("[name=sAccess]").find(x => x.checked) || {}).value || "acl",
    }, $("sMsg"));
    if (r) loadPoints();
  });
  $("tRun").addEventListener("click", async () => {
    $("tOut").textContent = "Prüfe …";
    try {
      const r = await api(`access-test?user=${encodeURIComponent($("tUser").value.trim())}&folder=${encodeURIComponent($("tFolder").value.trim())}`);
      $("tOut").innerHTML = `<p><b class="${r.allowed ? "ok" : "err"}">${r.allowed ? "✓ darf sehen" : "✗ darf nicht sehen"}</b>
        ${r.mode === "all" ? '<span class="muted">(Einstellung „alle“ ist aktiv – Ordnerrechte werden derzeit nicht beachtet)</span>' : ""}</p>` +
        r.chain.map(c => `<div>${c.read ? "✓" : "✗"} <code>${esc(c.folder)}</code><pre class="raw">${esc(c.output || "")}</pre></div>`).join("");
    } catch (e) { $("tOut").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
}

async function tabGeneral(body) {
  const s = await api("settings");
  body.innerHTML = `
    <div class="setgrid">
      <fieldset><legend>Karte</legend>
        <label>Kartenstil (https-Adresse) <input id="gStyle" value="${esc(s.map_style)}" placeholder="leer = nur Offline-Kugel"></label>
        <p class="muted small">Standard: OpenFreeMap (<code>https://tiles.openfreemap.org/styles/liberty</code>), ohne Schlüssel.
          Der Browser lädt die Kartenkacheln direkt dort – die Fotos und ihre Orte verlassen die NAS nicht.
          Ist der Dienst nicht erreichbar, zeigt der Globus eine schlichte Kugel mit Ländergrenzen.</p>
      </fieldset>
      <fieldset><legend>Satellitenbild</legend>
        <label class="inline"><input type="radio" name="gSat" value="esri"${s.satellite === "esri" ? " checked" : ""}> Esri (ohne Schlüssel, nicht-kommerziell)</label>
        <label class="inline"><input type="radio" name="gSat" value="maptiler"${s.satellite === "maptiler" ? " checked" : ""}> MapTiler (mit Schlüssel)</label>
        <label class="inline"><input type="radio" name="gSat" value="off"${s.satellite === "off" ? " checked" : ""}> Aus</label>
        <label>MapTiler-Schlüssel <input id="gMtKey" value="${esc(s.maptiler_key)}" placeholder="aus cloud.maptiler.com → API keys" autocomplete="off"></label>
        <p class="muted small">Der Schlüssel ist im Browser sichtbar – bei MapTiler unter „Allowed HTTP origins“ auf die eigene Adresse beschränken.
          Der Knopf 🛰️ oben schaltet zwischen Karte und Satellit um.</p>
      </fieldset>
      <fieldset><legend>Synology Photos</legend>
        <label>Adresse von Synology Photos <input id="gPhotosUrl" value="${esc(s.photos_url)}" placeholder="https://nas.meinedomain.de:5001/photo"></label>
        <p class="muted small">Im DSM-Fenster öffnet „In Synology Photos öffnen“ direkt den Ordner des Fotos. Außerhalb von DSM
          (eigene Adresse, Handy) braucht es diese Adresse; dann öffnet sich der richtige Bereich, aber nicht der Ordner.</p>
      </fieldset>
      <fieldset><legend>Anmeldung</legend>
        ${chk("gDsmLogin", s.dsm_login === "1", "Anmeldung mit DSM-Konten (Benutzername/Passwort, auch 2FA)")}
        ${chk("gAuto", s.dsm_auto_create === "1", "DSM-Benutzer beim ersten Besuch automatisch zulassen")}
        ${chk("gAdmins", s.dsm_admins === "1", "DSM-Administratoren sind auch hier Admins")}
        <label>DSM-Adresse für die Passwortprüfung <input id="gDsmUrl" value="${esc(s.dsm_url)}"></label>
        <p class="muted small">Nur Adressen auf der NAS selbst (127.0.0.1, localhost).</p>
      </fieldset>
      <fieldset><legend>Adresse &amp; Port</legend>
        <label>Öffentliche Adresse (Reverse Proxy) <input id="gPublic" value="${esc(s.public_url)}" placeholder="https://fotos.meinedomain.de"></label>
        <p class="muted small">Für das DSM-Fenster bei https-DSM und für den Zugriff von unterwegs.</p>
        <label>Port <input id="gPort" type="number" min="1024" max="65535" value="${s.port_configured}"></label>
        <p class="muted small">Läuft gerade auf Port ${s.port}.${s.port_configured !== s.port ? ` <b>Port ${s.port_configured} gilt nach dem Neustart des Pakets</b> (Paket-Zentrum → Foto-Globus → Stoppen/Ausführen).` : " Eine Änderung gilt nach dem Neustart des Pakets; Reverse Proxy und Firewall ggf. anpassen."}</p>
      </fieldset>
    </div>
    <div class="savebar"><button class="primary" id="gSave">Speichern</button><span id="gMsg"></span></div>`;
  $("gSave").addEventListener("click", async () => {
    const r = await saveSettings({
      map_style: $("gStyle").value.trim(), dsm_login: $("gDsmLogin").checked, dsm_auto_create: $("gAuto").checked,
      dsm_admins: $("gAdmins").checked, dsm_url: $("gDsmUrl").value.trim(), public_url: $("gPublic").value.trim(),
      port: Number($("gPort").value),
      satellite: ($$("[name=gSat]").find(x => x.checked) || {}).value || "esri",
      maptiler_key: $("gMtKey").value.trim(), photos_url: $("gPhotosUrl").value.trim(),
    }, $("gMsg"));
    if (r && r.port_configured !== s.port_configured) tabGeneral(body);
  });
}

async function tabLook(body) {
  const [s, b] = await Promise.all([api("settings"), api("branding")]);
  body.innerHTML = `
    <div class="setgrid">
      <fieldset><legend>Firmenname &amp; Logo</legend>
        <label>Firmenname (Kopfzeile, Anmeldung) <input id="lName" value="${esc(b.company_name)}" maxlength="80"></label>
        <div class="row">${b.logo ? '<img class="logoPrev" id="lPrev" alt="Logo">' : '<span class="muted small">Kein Logo</span>'}
          <label class="btn">Logo wählen (PNG/JPEG, max. 1 MB)<input type="file" id="lFile" accept="image/png,image/jpeg" class="hidden"></label>
          ${b.logo ? '<button class="danger" id="lDel">Logo entfernen</button>' : ""}</div>
        <div class="savebar"><button class="primary" id="lSave">Speichern</button><span id="lMsg"></span></div>
      </fieldset>
      <fieldset><legend>Standard-Design für alle</legend>${themePicker(s.theme_default, false)}<span id="tMsg"></span></fieldset>
    </div>`;
  if (b.logo) blobUrl("branding/logo").then(u => { $("lPrev").src = u; }).catch(() => {});
  $("lSave").addEventListener("click", async () => {
    try { await api("branding", { method: "PATCH", body: { company_name: $("lName").value.trim() } }); okMsg($("lMsg"), "Gespeichert"); loadBranding(); }
    catch (e) { $("lMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
  $("lFile").addEventListener("change", () => {
    const f = $("lFile").files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = async () => {
      try { await api("branding/logo", { method: "PUT", body: { data_url: rd.result } }); await loadBranding(); tabLook(body); }
      catch (e) { $("lMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
    };
    rd.readAsDataURL(f);
  });
  if ($("lDel")) $("lDel").addEventListener("click", async () => { await api("branding/logo", { method: "DELETE" }); await loadBranding(); tabLook(body); });
  $$("#tabBody .theme-opt").forEach(btn => btn.addEventListener("click", async () => {
    if (await saveSettings({ theme_default: btn.dataset.theme }, $("tMsg"))) {
      $$("#tabBody .theme-opt").forEach(x => x.classList.toggle("on", x === btn));
      state.me = await api("me");
      fgTheme(state.me.theme_effective);
      repaintMap();
    }
  }));
}

async function tabBackup(body) {
  const b = await api("backups");
  const kb = (n) => nf.format(Math.round(n / 1024)) + " KB";
  body.innerHTML = `
    <div class="setgrid">
      <fieldset><legend>Automatische Sicherung</legend>
        ${chk("bOn", b.enabled, "Jede Nacht sichern")}
        <label>Uhrzeit <select id="bHour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}"${h === b.hour ? " selected" : ""}>${String(h).padStart(2, "0")}:00 Uhr</option>`).join("")}</select></label>
        <label>Freigegebener Ordner (für Hyper Backup) <input id="bDir" value="${esc(b.dir)}" placeholder="z. B. /volume1/backup/fotoglobus"></label>
        <label>Dort aufheben (Tage) <input id="bKeep" type="number" min="1" max="3650" value="${b.keep_days}"></label>
        <p class="muted small">Gesichert werden Index, Einstellungen und Benutzer – nicht die Fotos selbst (die sichert Hyper Backup über die Fotoordner).
          Zusätzlich liegen die letzten ${b.local_keep} Sicherungen im Paketordner.</p>
        <div class="savebar"><button class="primary" id="bSave">Speichern</button><span id="bMsg"></span></div>
      </fieldset>
      <fieldset><legend>Sicherungen</legend>
        <div class="row"><button id="bNow">Jetzt sichern</button><span class="muted small">Zuletzt: ${esc(b.last || "noch nie")} ${esc(b.last_status || "")}</span></div>
        <div class="scroll"><table><tr><th></th><th>Datum</th><th>Größe</th><th>Ort</th><th></th></tr>
          ${b.backups.map((x, i) => `<tr><td>${i ? `<input type="checkbox" class="bSel" value="${esc(x.name)}">` : ""}</td><td>${deDate(x.date)} ${x.time}${x.reason ? ` <span class="muted small">${esc(x.reason)}</span>` : ""}</td>
            <td>${kb(x.size)}</td><td>${x.where.join(", ")}</td><td class="row"><button class="mini" data-dl="${esc(x.name)}">⬇</button><button class="mini" data-rs="${esc(x.name)}">Wiederherstellen</button></td></tr>`).join("") || '<tr><td colspan="5" class="muted">Noch keine</td></tr>'}
        </table></div>
        <div class="row"><button class="danger mini" id="bDel">Ausgewählte löschen</button><span class="muted small">Die neueste Sicherung bleibt immer erhalten.</span></div>
        <div id="bOut"></div>
      </fieldset>
    </div>`;
  const out = (m, err) => { $("bOut").innerHTML = `<span class="${err ? "err" : "ok"}">${esc(m)}</span>`; };
  $("bSave").addEventListener("click", async () => {
    try { await api("backups/settings", { method: "PATCH", body: { enabled: $("bOn").checked, hour: Number($("bHour").value), dir: $("bDir").value.trim(), keep_days: Number($("bKeep").value) } }); okMsg($("bMsg"), "Gespeichert"); }
    catch (e) { $("bMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
  $("bNow").addEventListener("click", async () => { try { await api("backups", { method: "POST" }); tabBackup(body); } catch (e) { out(e.message, true); } });
  $("bDel").addEventListener("click", async () => {
    const names = $$(".bSel").filter(x => x.checked).map(x => x.value);
    if (!names.length || !confirm(`${names.length} Sicherung(en) löschen?`)) return;
    try { await api("backups/delete", { method: "POST", body: { names } }); tabBackup(body); } catch (e) { out(e.message, true); }
  });
  $$("[data-dl]").forEach(x => x.addEventListener("click", async () => {
    const u = await blobUrl(`backups/${encodeURIComponent(x.dataset.dl)}/download`);
    const a = Object.assign(document.createElement("a"), { href: u, download: x.dataset.dl });
    document.body.appendChild(a); a.click(); a.remove();
  }));
  $$("[data-rs]").forEach(x => x.addEventListener("click", async () => {
    const name = x.dataset.rs;
    if (prompt(`Wirklich zurückspielen? Der aktuelle Stand wird vorher gesichert.\nZur Bestätigung den Namen eingeben:\n${name}`) !== name) return;
    try { const r = await api(`backups/${encodeURIComponent(name)}/restore`, { method: "POST", body: { confirm: name } }); out(`Wiederhergestellt. Vorheriger Stand gesichert als ${r.safety_backup}.`); loadPoints(); }
    catch (e) { out(e.message, true); }
  }));
}

async function tabUsers(body) {
  const users = await api("users");
  const render = (list) => {
    body.innerHTML = `<p class="muted small">DSM-Benutzer erscheinen hier nach ihrem ersten Besuch. Wer welche Fotos sieht, regeln die Rechte in DSM.</p>
      <div class="scroll"><table><tr><th>Benutzer</th><th>Art</th><th>Zuletzt da</th><th>Admin</th><th>Aktiv</th></tr>
      ${list.map(u => `<tr><td>${esc(u.display_name)} <span class="muted small">${esc(u.username)}</span></td><td>${u.is_dsm ? "DSM-Konto" : "lokal"}</td>
        <td>${u.last_login ? deDateTime(u.last_login) : "–"}</td>
        <td><input type="checkbox" data-u="${u.id}" data-f="is_admin"${u.is_admin ? " checked" : ""}></td>
        <td><input type="checkbox" data-u="${u.id}" data-f="active"${u.active ? " checked" : ""}></td></tr>`).join("")}</table></div><div class="err" id="uErr"></div>`;
    $$("[data-u]").forEach(cb => cb.addEventListener("change", async () => {
      try { render(await api(`users/${cb.dataset.u}`, { method: "PATCH", body: { [cb.dataset.f]: cb.checked } })); }
      catch (e) { cb.checked = !cb.checked; $("uErr").textContent = e.message; }
    }));
  };
  render(users);
}

async function tabAudit(body) {
  const rows = await api("audit?limit=300");
  body.innerHTML = `<div class="scroll"><table><tr><th>Zeit</th><th>Wer</th><th>Aktion</th><th>Details</th></tr>
    ${rows.map(r => `<tr><td>${deDateTime(r.ts)}</td><td>${esc(r.user || "System")}</td><td>${esc(r.action)}</td><td class="small">${esc(r.target || "")} ${esc(r.details || "")}</td></tr>`).join("")}</table></div>`;
}

async function tabUpdates(body) {
  const show = (u) => {
    body.innerHTML = `<p>Installiert: <b>${esc(u.installed)}</b> · Neueste: <b>${esc(u.latest || "–")}</b>
      ${u.update_available ? '<span class="ok"> – Update verfügbar</span>' : ""}</p>
      <p class="muted small">Updates kommen übers Paket-Zentrum. Einmalig als Paketquelle eintragen:
        Paket-Zentrum → Einstellungen → Paketquellen → Hinzufügen → <code>${esc(u.source_url)}</code></p>
      ${u.error ? `<p class="err">${esc(u.error)}</p>` : ""}
      <button id="uCheck">Jetzt prüfen</button>`;
    $("uCheck").addEventListener("click", async () => { $("uCheck").disabled = true; show(await api("updates/check", { method: "POST" })); });
  };
  show(await api("updates"));
}


// ---------- Suche, Statistik, Länder/Orte öffnen ----------
function filterQuery() {
  const q = new URLSearchParams();
  if (state.yearFrom) q.set("year_from", state.yearFrom);
  if (state.yearTo) q.set("year_to", state.yearTo);
  if (state.scope !== "all") q.set("scope", state.scope);
  return q;
}
const flag = (cc) => cc && /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map(c => 0x1F1E6 + c.charCodeAt(0) - 65)) : "🌐";

function flyToBbox(b) {
  if (!b || !state.map) return;
  let [w, s, e, n] = b;
  const pad = 0.02;  // ein einzelner Punkt soll nicht bis ins letzte Haus zoomen
  if (e - w < pad) { w -= pad; e += pad; }
  if (n - s < pad) { s -= pad; n += pad; }
  state.map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 });  // Reste der Kamerafahrt entfernen
  const narrow = window.innerWidth < 720;
  const leftOpen = !$("trips").classList.contains("hidden") || !$("stats").classList.contains("hidden");
  const top = narrow ? document.querySelector(".topbar").getBoundingClientRect().bottom + 40 : 110;
  const playing = document.body.classList.contains("playing");
  const fitPad = playing ? { top: 60, bottom: 140, left: 40, right: 40 }
    : narrow ? { top, bottom: window.innerHeight * 0.62 + 20, left: 40, right: 40 }
    : { top, bottom: 60, left: leftOpen ? 430 : 60, right: 460 };
  try {
    state.map.fitBounds([[w, s], [e, n]], { padding: fitPad, maxZoom: state.styleOnline ? 13 : 6, duration: 1800 });
  } catch (err) {  // Fenster zu klein für die Abstände → einfach mittig hinfliegen
    state.map.flyTo({ center: [(w + e) / 2, (s + n) / 2], zoom: 4, duration: 1800 });
  }
}

// Land oder Ort: hinfliegen und die Galerie öffnen
async function openWhere(cc, place) {
  const q = filterQuery();
  q.set("cc", cc);
  if (place) q.set("place", place);
  try {
    const r = await api(`photos/where?${q}`);
    if (window.innerWidth < 720) $("stats").classList.add("hidden");
    flyToBbox(r.bbox);
    openPanel(r.ids, null, null, r.count);
  } catch (e) { notice(esc(e.message)); setTimeout(() => notice(""), 4000); }
}

const search = { timer: null, hits: [], sel: -1, seq: 0 };
function renderHits() {
  const box = $("searchHits");
  if (!$("search").value.trim()) { box.classList.add("hidden"); return; }
  box.innerHTML = search.hits.length
    ? search.hits.map((h, i) => `<button role="option" data-i="${i}" class="${i === search.sel ? "sel" : ""}">
        <span>${h.type === "country" ? flag(h.cc) : "📍"} ${esc(h.label)}</span><span class="muted small">${nf.format(h.count)}</span></button>`).join("")
    : '<div class="empty">Kein Ort mit deinen Fotos gefunden</div>';
  box.classList.remove("hidden");
  $$("#searchHits button").forEach(b => b.addEventListener("mousedown", (e) => { e.preventDefault(); pickHit(Number(b.dataset.i)); }));
}
function pickHit(i) {
  const h = search.hits[i];
  if (!h) return;
  $("searchHits").classList.add("hidden");
  $("search").value = h.label;
  $("search").blur();
  openWhere(h.cc, h.type === "place" ? h.place : null);
}
$("search").addEventListener("input", () => {
  clearTimeout(search.timer);
  const q = $("search").value.trim();
  if (!q) { search.hits = []; renderHits(); return; }
  search.timer = setTimeout(async () => {
    const seq = ++search.seq;
    const params = filterQuery(); params.set("q", q);
    try { const hits = await api(`search?${params}`); if (seq === search.seq) { search.hits = hits; search.sel = hits.length ? 0 : -1; renderHits(); } }
    catch (e) { /* z. B. lokales Admin-Konto */ }
  }, 220);
});
$("search").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!search.hits.length) return;
    search.sel = (search.sel + (e.key === "ArrowDown" ? 1 : -1) + search.hits.length) % search.hits.length;
    renderHits();
  } else if (e.key === "Enter") { e.preventDefault(); pickHit(Math.max(0, search.sel)); }
  else if (e.key === "Escape") { $("search").value = ""; search.hits = []; renderHits(); }
});
$("search").addEventListener("blur", () => setTimeout(() => $("searchHits").classList.add("hidden"), 150));
$("search").addEventListener("focus", () => { if (search.hits.length) renderHits(); });

async function loadStats() {
  const body = $("statsBody");
  let s;
  try { s = await api(`stats?${filterQuery()}`); }
  catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const filt = [state.yearFrom || state.yearTo ? `${state.yearFrom || "…"}–${state.yearTo || "…"}` : "",
                state.scope === "p" ? "nur meine" : state.scope === "s" ? "nur gemeinsame" : ""].filter(Boolean).join(", ");
  $("statsSub").textContent = filt ? `Filter: ${filt}` : "alle Fotos mit Aufnahmeort";
  const maxY = Math.max(1, ...s.years.map(y => y.count));
  const maxC = Math.max(1, ...s.countries.map(c => c.count));
  const yearOn = (y) => (!state.yearFrom || y >= state.yearFrom) && (!state.yearTo || y <= state.yearTo);
  body.innerHTML = `
    <div class="kpis">
      <div><b>${nf.format(s.countries.length)}</b>${s.countries.length === 1 ? "Land" : "Länder"}</div>
      <div><b>${nf.format(s.places)}</b>Ort${s.places === 1 ? "" : "e"}</div>
      <div><b>${nf.format(s.photos - s.videos)}</b>Fotos mit Ort</div>
      <div><b>${nf.format(s.videos)}</b>Video${s.videos === 1 ? "" : "s"} mit Ort</div>
    </div>
    <label class="inline small" style="margin-top:10px"><input type="checkbox" id="visitedToggle"${showVisited() ? " checked" : ""}> Besuchte Länder auf dem Globus einfärben</label>
    ${s.years.length ? `<h3>Fotos pro Jahr</h3>
      <div class="bars">${s.years.map(y => `<button data-y="${y.year}" class="${state.yearFrom === y.year && state.yearTo === y.year ? "on" : yearOn(y.year) ? "" : "off"}"
        style="height:${Math.max(3, Math.round(y.count / maxY * 100))}%" title="${y.year}: ${nf.format(y.count)} – klicken, um nur dieses Jahr zu zeigen"><span>${y.count >= maxY * 0.5 ? nf.format(y.count) : ""}</span></button>`).join("")}</div>
      <div class="barLabels">${s.years.map((y, i) => `<span>${s.years.length <= 12 || i % Math.ceil(s.years.length / 8) === 0 ? "’" + String(y.year).slice(2) : ""}</span>`).join("")}</div>` : ""}
    ${s.top_places.length ? `<h3>Top-Orte</h3><div class="rows">${s.top_places.map(p => `<button data-cc="${esc(p.cc)}" data-place="${esc(p.place)}">
        <span class="flag">📍</span><span class="name">${esc(p.label)}</span><span class="n">${nf.format(p.count)}</span></button>`).join("")}</div>` : ""}
    ${s.countries.length ? `<h3>Länder</h3><div class="rows">${s.countries.map(c => `<button data-cc="${esc(c.cc)}">
        <span class="flag">${flag(c.cc)}</span><span class="name">${esc(c.name)}</span><span class="n">${nf.format(c.count)} · ${c.places} Ort${c.places === 1 ? "" : "e"}</span></button>
        <div class="meter" style="width:calc((100% - 38px) * ${(c.count / maxC).toFixed(3)})"></div>`).join("")}</div>` :
      '<p class="muted">Noch keine Fotos mit Ortsnamen. Die Namen kommen nach der nächsten Suche dazu.</p>'}
    <p class="muted small" style="margin-top:14px">Ortsnamen: <a href="https://www.geonames.org" target="_blank" rel="noopener">GeoNames</a> (CC BY 4.0), offline auf der NAS.</p>`;
  $("visitedToggle").addEventListener("change", () => { store.set("fg_visited", $("visitedToggle").checked ? "1" : "0"); updateVisited(); });
  $$("#statsBody .bars button").forEach(b => b.addEventListener("click", () => {
    const y = Number(b.dataset.y);
    const only = state.yearFrom === y && state.yearTo === y;
    state.yearFrom = only ? null : y; state.yearTo = only ? null : y;
    fillYears(state.years || []);
    applyFilter();
  }));
  $$("#statsBody .rows button").forEach(b => b.addEventListener("click", () => openWhere(b.dataset.cc, b.dataset.place || null)));
}
$("statsBtn").addEventListener("click", () => {
  const box = $("stats");
  closePanelsExcept("stats");
  if (tripsState.current) leaveTrip();
  box.classList.toggle("hidden");
  if (!box.classList.contains("hidden")) { if (window.innerWidth < 720) $("panel").classList.add("hidden"); loadStats(); }
});
$("statsClose").addEventListener("click", () => $("stats").classList.add("hidden"));


// ---------- Reisen ----------
const tripsState = { data: null, showHidden: false, current: null };
function dayRange(a, b) {
  const [ya, ma, da] = a.split("-").map(Number), [yb, mb, db] = b.split("-").map(Number);
  if (a === b) return `${da}. ${MONTHS[ma - 1]} ${ya}`;
  if (ya === yb && ma === mb) return `${da}.–${db}. ${MONTHS[ma - 1]} ${ya}`;
  if (ya === yb) return `${da}. ${MONTHS[ma - 1]} – ${db}. ${MONTHS[mb - 1]} ${ya}`;
  return `${deDate(a)} – ${deDate(b)}`;
}
function closePanelsExcept(id) {
  for (const p of ["stats", "trips"]) if (p !== id) $(p).classList.add("hidden");
}
function setRoute(route) {
  if (!route || route.length === 0) { state.routeData = null; }
  else {
    const feats = [];
    if (route.length > 1) feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: route.map(s => [s.lon, s.lat]) }, properties: {} });
    route.forEach((s, i) => feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [s.lon, s.lat] },
                                        properties: { end: i === 0 || i === route.length - 1 } }));
    state.routeData = { type: "FeatureCollection", features: feats };
  }
  const src = state.map && state.map.getSource("route");
  if (src) src.setData(state.routeData || { type: "FeatureCollection", features: [] });
}
function leaveTrip() {
  if (!tripsState.current) return;
  tripsState.current = null;
  state.tripIds = null;
  setRoute(null);
  applyFilter();
}

async function loadTrips() {
  const body = $("tripsBody");
  $("tripsTitle").textContent = "Reisen";
  try { tripsState.data = await api(`trips?${filterQuery()}`); }
  catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  renderTrips();
}

function renderTrips() {
  const d = tripsState.data, body = $("tripsBody");
  const h = d.home;
  $("tripsSub").textContent = `${d.trips.filter(t => !t.hidden).length} Reisen · mehr als ${d.away_km} km von Zuhause`;
  const visible = d.trips.filter(t => !t.hidden), hidden = d.trips.filter(t => t.hidden);
  const row = (t) => `<button class="trip${t.hidden ? " hiddenTrip" : ""}" data-trip="${t.id}">
      <span class="cover">${t.cover ? `<img data-cover="${t.cover}" alt="">` : ""}</span>
      <span class="txt"><b>${esc(t.title)}</b><span>${dayRange(t.start, t.end)} · ${t.days} Tag${t.days === 1 ? "" : "e"} · ${t.countries.map(c => flag(c.cc)).join(" ")}</span></span>
      <span class="muted small">${nf.format(t.count)}</span></button>`;
  let html = `<div class="homeLine"><span>🏠</span><span class="grow">Zuhause: <b>${esc(h ? h.label || "unbekannt" : "noch unbekannt")}</b>
      <span class="muted small">${h ? (h.source === "auto" ? "(automatisch)" : "(selbst gesetzt)") : ""}</span></span>
      <button class="mini" id="homePick">Ändern</button>${h && h.source === "manual" ? '<button class="mini" id="homeAuto">Automatisch</button>' : ""}</div>`;
  if (!visible.length) html += `<p class="muted">Noch keine Reisen erkannt. Eine Reise sind mindestens 3 Fotos mehr als ${d.away_km} km von Zuhause,
      mit höchstens 2 Tagen ohne Fotos dazwischen.</p>`;
  let year = null;
  for (const t of visible) {
    const y = t.start.slice(0, 4);
    if (y !== year) { html += `<h3 class="yearHead">${y} <button class="mini" data-playyear="${y}" title="Alle Reisen ${y} nachspielen">▶ Jahresrückblick</button></h3>`; year = y; }
    html += row(t);
  }
  if (hidden.length) {
    html += `<h3><button class="backLink" id="toggleHidden">${tripsState.showHidden ? "▾" : "▸"} Ausgeblendet (${hidden.length})</button></h3>`;
    if (tripsState.showHidden) html += hidden.map(row).join("");
  }
  html += `<p style="margin-top:18px"><button class="mini danger" id="tripsReset">Alle Änderungen an Reisen zurücksetzen</button></p>`;
  body.innerHTML = html;
  $$("#tripsBody [data-trip]").forEach(b => b.addEventListener("click", () => openTrip(Number(b.dataset.trip))));
  $$("#tripsBody [data-playyear]").forEach(b => b.addEventListener("click", () => {
    const y = b.dataset.playyear;
    const ids = visible.filter(t => t.start.slice(0, 4) === y).sort((a, c) => a.start.localeCompare(c.start)).map(t => t.id);
    startPlayer(ids, `Jahresrückblick ${y}`);
  }));
  $$("#tripsBody img[data-cover]").forEach(img => queueThumb(img, img.dataset.cover));
  $("homePick").addEventListener("click", pickHome);
  if ($("homeAuto")) $("homeAuto").addEventListener("click", async () => { tripsState.data = await api("home", { method: "PUT", body: { auto: true } }); renderTrips(); });
  if ($("toggleHidden")) $("toggleHidden").addEventListener("click", () => { tripsState.showHidden = !tripsState.showHidden; renderTrips(); });
  $("tripsReset").addEventListener("click", async () => {
    if (!confirm("Alle umbenannten, geteilten, zusammengeführten und ausgeblendeten Reisen zurücksetzen? Danach werden die Reisen neu erkannt.")) return;
    tripsState.data = await api("trips/reset", { method: "POST" }); renderTrips();
  });
}

function pickHome() {
  notice("Klicke auf dem Globus auf dein Zuhause. <button class='mini' id='pickCancel'>Abbrechen</button>");
  $("map").classList.add("pickNotice");
  if (window.innerWidth < 720) $("trips").classList.add("hidden");
  const done = () => { state.pickHome = null; $("map").classList.remove("pickNotice"); notice(""); };
  $("pickCancel").addEventListener("click", () => { done(); $("trips").classList.remove("hidden"); });
  state.pickHome = async (ll) => {
    done();
    try { tripsState.data = await api("home", { method: "PUT", body: { lat: ll.lat, lon: ((ll.lng + 540) % 360) - 180 } }); }
    catch (e) { notice(esc(e.message)); return; }
    $("trips").classList.remove("hidden");
    renderTrips();
  };
}

async function openTrip(id) {
  let t;
  try { t = await api(`trips/${id}`); } catch (e) { notice(esc(e.message)); return; }
  tripsState.current = t;
  state.tripIds = new Set(t.ids);
  applyFilter();
  setRoute(t.route);
  flyToBbox(t.bbox);
  renderTripDetail();
  if (window.innerWidth >= 720) openPanel(t.ids, null, null, t.count, t.title);
}

function renderTripDetail() {
  const t = tripsState.current, body = $("tripsBody");
  $("tripsTitle").textContent = t.title;
  $("tripsSub").textContent = `${dayRange(t.start, t.end)} · ${t.days} Tag${t.days === 1 ? "" : "e"}`;
  const start = new Date(t.start + "T00:00:00");
  const dayNo = (iso) => Math.round((new Date(iso.slice(0, 10) + "T00:00:00") - start) / 86400000) + 1;
  const splitDays = t.photo_days.filter(d => d > t.start);
  body.innerHTML = `
    <button class="backLink" id="tripBack">← Alle Reisen</button>
    <div class="kpis" style="margin-top:8px">
      <div><b>${nf.format(t.count - t.videos)}</b>Fotos</div><div><b>${nf.format(t.videos)}</b>Videos</div>
      <div><b>${t.route.length}</b>Halt${t.route.length === 1 ? "" : "e"}</div>
      <div><b>${t.countries.map(c => flag(c.cc)).join(" ")}</b>${t.countries.map(c => esc(c.name)).join(", ")}</div>
    </div>
    <div class="row" style="margin-top:10px">
      <button class="primary" id="tripPlay" style="flex:1">▶ Reise nachspielen</button>
      <button id="tripPhotos" style="flex:1">🖼 Fotos ansehen</button>
    </div>
    <h3>Route</h3>
    <ol class="stops">${t.route.map((s, i) => `<li><button data-stop="${i}"><span class="day">Tag ${dayNo(s.first)}</span>
      <span>${esc(s.label || "Unterwegs")}</span><span class="n">${s.count}</span></button></li>`).join("")}</ol>
    <h3>Bearbeiten</h3>
    <div class="actions">
      <button id="tripRename">✏️ Umbenennen${t.renamed ? ` <span class="muted small">(automatisch: ${esc(t.auto_title)})</span>` : ""}</button>
      ${splitDays.length ? `<div class="row"><select id="tripSplitDay">${splitDays.map(d => `<option value="${d}">ab ${deDate(d)} (Tag ${dayNo(d)})</option>`).join("")}</select>
        <button id="tripSplit">✂️ Teilen</button></div>` : ""}
      <div class="row">
        <button id="tripMergePrev"${t.prev ? "" : " disabled"}>🔗 Mit vorheriger</button>
        <button id="tripMergeNext"${t.next ? "" : " disabled"}>🔗 Mit nächster</button>
      </div>
      <button id="tripHide">${t.hidden ? "👁 Wieder einblenden" : "🙈 Ausblenden"}</button>
    </div>
    <div class="err" id="tripErr"></div>`;
  const err = (e) => { $("tripErr").textContent = e.message; };
  $("tripBack").addEventListener("click", () => { leaveTrip(); $("panel").classList.add("hidden"); loadTrips(); });
  $("tripPlay").addEventListener("click", () => startPlayer([t.id], "", t.id));
  $("tripPhotos").addEventListener("click", () => {
    if (window.innerWidth < 720) $("trips").classList.add("hidden");
    openPanel(t.ids, null, null, t.count, t.title);
  });
  $$("#tripsBody [data-stop]").forEach(b => b.addEventListener("click", () => {
    const s = t.route[Number(b.dataset.stop)];
    state.map.flyTo({ center: [s.lon, s.lat], zoom: state.styleOnline ? 12 : 6, duration: 1400 });
  }));
  $("tripRename").addEventListener("click", async () => {
    const name = prompt("Name der Reise (leer = automatischer Name):", t.renamed ? t.title : "");
    if (name === null) return;
    try { tripsState.current = await api(`trips/${t.id}`, { method: "PATCH", body: { title: name } }); renderTripDetail(); } catch (e) { err(e); }
  });
  if ($("tripSplit")) $("tripSplit").addEventListener("click", async () => {
    try { await api(`trips/${t.id}/split`, { method: "POST", body: { day: $("tripSplitDay").value } }); openTrip(t.id); } catch (e) { err(e); }
  });
  const merge = async (other) => {
    try { const m = await api(`trips/${t.id}/merge`, { method: "POST", body: { other } }); openTrip(m.id); } catch (e) { err(e); }
  };
  $("tripMergePrev").addEventListener("click", () => t.prev && merge(t.prev));
  $("tripMergeNext").addEventListener("click", () => t.next && merge(t.next));
  $("tripHide").addEventListener("click", async () => {
    try { tripsState.current = await api(`trips/${t.id}`, { method: "PATCH", body: { hidden: !t.hidden } }); renderTripDetail(); } catch (e) { err(e); }
  });
}

$("tripsBtn").addEventListener("click", () => {
  const box = $("trips");
  const open = box.classList.contains("hidden");
  closePanelsExcept("trips");
  box.classList.toggle("hidden", !open);
  if (open) { if (window.innerWidth < 720) $("panel").classList.add("hidden"); if (!tripsState.current) loadTrips(); }
});
$("tripsClose").addEventListener("click", () => { $("trips").classList.add("hidden"); leaveTrip(); });

// ---------- los ----------
loadBranding();
start().catch((e) => { if (e.status !== 401) { showLogin(); $("loginErr").textContent = e.message; } });
