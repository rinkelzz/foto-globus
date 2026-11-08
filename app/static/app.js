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

async function initMap() {
  if (state.map) return;
  let cfg = { style: "" };
  try { cfg = await api("map-config"); } catch (e) { /* Offline-Kugel */ }
  const online = await onlineStyle(cfg.style);
  state.styleOnline = !!online;
  const map = new maplibregl.Map({
    container: "map",
    style: online || offlineStyle(),
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
  try { map.setProjection({ type: "globe" }); } catch (e) { /* ältere Browser: flache Karte */ }
  map.addSource("photos", {
    type: "geojson", data: { type: "FeatureCollection", features: [] },
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
  for (const layer of ["clusters", "photo"]) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", "clusters", async (e) => {
    const f = e.features[0];
    const src = map.getSource("photos");
    const leaves = await src.getClusterLeaves(f.properties.cluster_id, 2000, 0);
    openPanel(leaves.map(l => l.properties.id), f.geometry.coordinates, f.properties.cluster_id, f.properties.point_count);
  });
  map.on("click", "photo", (e) => {
    const f = e.features[0];
    openPanel([f.properties.id], f.geometry.coordinates, null, 1);
  });
}

function geojson(points) {
  return { type: "FeatureCollection", features: points.map(p => ({
    type: "Feature", geometry: { type: "Point", coordinates: [p[2], p[1]] }, properties: { id: p[0], s: p[4] } })) };
}

function applyFilter(fit = false) {
  const { yearFrom, yearTo, scope } = state;
  state.filtered = state.points.filter(p => (scope === "all" || p[4] === scope)
    && (!yearFrom || (p[5] || 0) >= yearFrom) && (!yearTo || (p[5] || 9999) <= yearTo));
  const src = state.map && state.map.getSource("photos");
  if (src) src.setData(geojson(state.filtered));
  const n = state.filtered.length;
  $("countChip").textContent = `${nf.format(n)} Foto${n === 1 ? "" : "s"}`;
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

function rangeText(photos) {
  const dates = photos.map(p => p.taken_at).filter(Boolean).sort();
  if (!dates.length) return "";
  const a = monthYear(dates[0]), b = monthYear(dates[dates.length - 1]);
  return a === b ? a : `${a} – ${b}`;
}

async function openPanel(ids, center, clusterId, total) {
  thumbQueue.waiting.length = 0;
  for (const img of $$("#grid img")) if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
  state.panel = { photos: [], center, clusterId };
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
  $("panelSub").textContent = rangeText(photos);
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
    b.innerHTML = `<img alt="${esc(p.name)}">${p.scope === "personal" ? "" : '<span class="badge">gemeinsam</span>'}`;
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
  const bits = [deDateTime(p.taken_at)];
  if (p.camera) bits.push(esc(p.camera));
  if (p.width && p.height) bits.push(`${p.width} × ${p.height}`);
  bits.push(`${p.scope === "personal" ? "Meine Fotos" : "Gemeinsame Fotos"}${p.folder ? " / " + esc(p.folder) : ""}`);
  bits.push(`${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}${p.alt != null ? ` · ${Math.round(p.alt)} m` : ""}`);
  $("lbMeta").innerHTML = bits.join(" · ");
  $("lbPrev").disabled = i === 0;
  $("lbNext").disabled = i === photos.length - 1;
  const img = $("lbImg");
  img.removeAttribute("src");
  try {
    const u = await blobUrl(`photos/${p.id}/thumb/xl`);
    if (state.lb !== i) { URL.revokeObjectURL(u); return; }
    if (lbUrl) URL.revokeObjectURL(lbUrl);
    lbUrl = u; img.src = u;
  } catch (e) { img.alt = "Keine Vorschau vorhanden"; }
}
function openLightbox(i) { showLb(i); }
function closeLightbox() { $("lightbox").classList.add("hidden"); state.lb = -1; }
$("lbClose").addEventListener("click", closeLightbox);
$("lbPrev").addEventListener("click", () => showLb(state.lb - 1));
$("lbNext").addEventListener("click", () => showLb(state.lb + 1));
$("lbMap").addEventListener("click", () => {
  const p = state.panel.photos[state.lb];
  closeLightbox();
  state.map.flyTo({ center: [p.lon, p.lat], zoom: 14, duration: 1800 });
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
  if (!state.styleOnline) {
    const s = offlineStyle();
    map.setPaintProperty("ocean", "background-color", s.layers[0].paint["background-color"]);
    map.setPaintProperty("land", "fill-color", s.layers[1].paint["fill-color"]);
    map.setPaintProperty("borders", "line-color", s.layers[2].paint["line-color"]);
  }
  map.getSource("photos").setData(geojson(state.filtered));
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

// ---------- los ----------
loadBranding();
start().catch((e) => { if (e.status !== 401) { showLogin(); $("loginErr").textContent = e.message; } });
