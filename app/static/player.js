"use strict";
/* Foto-Globus – „Reise nachspielen“: Kamerafahrt von Halt zu Halt, Route zeichnet sich mit, Diashow an jedem Halt.
   Nutzt die Helfer aus app.js (state, api, blobUrl, applyFilter, flyToBbox, dayRange …). */

const P = {
  queue: [], qi: 0, trip: null, stop: -1, slide: 0, phase: "idle",   // idle | intro | fly | slides | end
  playing: false, gen: 0, timers: [], raf: 0, speed: 1, cache: new Map(), returnTo: null, label: "",
};
const SLIDES_PER_STOP = 6;
const SLIDE_MS = 2600;

const pSpeed = () => P.speed;
function pWait(ms, gen) {
  return new Promise((resolve) => { P.timers.push(setTimeout(() => resolve(gen === P.gen), ms / pSpeed())); });
}
function pCancel() {
  P.gen++;
  P.timers.forEach(clearTimeout);
  P.timers = [];
  cancelAnimationFrame(P.raf);
  if (state.map) state.map.stop();
}

async function pImage(id) {
  if (P.cache.has(id)) return P.cache.get(id);
  const u = blobUrl(`photos/${id}/thumb/xl`).catch(() => null);
  P.cache.set(id, u);
  return u;
}
function pSample(ids, n) {
  if (ids.length <= n) return ids.slice();
  return Array.from({ length: n }, (_, k) => ids[Math.round(k * (ids.length - 1) / (n - 1))]);
}
function pKm(a, b) {
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.min(1, Math.sqrt(h)));
}

// Route bis zum aktuellen Halt; der letzte Abschnitt wächst während des Flugs mit (t = 0…1)
function pDrawRoute(upto, t = 1) {
  const route = P.trip.route;
  const coords = route.slice(0, Math.max(0, upto) + 1).map(s => [s.lon, s.lat]);
  if (upto > 0 && t < 1) {
    const a = route[upto - 1], b = route[upto];
    let dLon = b.lon - a.lon;
    if (dLon > 180) dLon -= 360; else if (dLon < -180) dLon += 360;
    coords[coords.length - 1] = [a.lon + dLon * t, a.lat + (b.lat - a.lat) * t];
  }
  const feats = [];
  if (coords.length > 1) feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} });
  route.slice(0, upto + (t >= 1 ? 1 : 0)).forEach((s, i) =>
    feats.push({ type: "Feature", geometry: { type: "Point", coordinates: [s.lon, s.lat] }, properties: { end: i === upto } }));
  state.routeData = { type: "FeatureCollection", features: feats };
  const src = state.map.getSource("route");
  if (src) src.setData(state.routeData);
}

function pUi() {
  const t = P.trip;
  $("pPlay").textContent = P.phase === "end" ? "⟲" : P.playing ? "⏸" : "▶";
  $("pPlay").title = P.phase === "end" ? "Nochmal" : P.playing ? "Pause (Leertaste)" : "Weiter (Leertaste)";
  if (!t) return;
  $("pTitle").textContent = t.title;
  const n = t.route.length;
  const s = t.route[P.stop];
  const start = new Date(t.start + "T00:00:00");
  const day = s ? Math.round((new Date(s.first.slice(0, 10) + "T00:00:00") - start) / 86400000) + 1 : null;
  $("pStop").textContent = P.phase === "end" ? "Ende der Reise" : s ? `Tag ${day} · ${s.label || "Unterwegs"} · Halt ${P.stop + 1}/${n}`
    : dayRange(t.start, t.end) + (P.queue.length > 1 ? ` · Reise ${P.qi + 1}/${P.queue.length}` : "");
  const done = P.phase === "end" ? 1 : Math.max(0, P.stop) / n + (P.phase === "slides" ? (P.slide + 1) / Math.max(1, P.slideIds.length) / n : 0);
  const overall = P.queue.length > 1 ? (P.qi + done) / P.queue.length : done;
  $("pProgress").style.width = `${Math.round(overall * 100)}%`;
}

function pShowSlide(url, caption) {
  const a = $("pImgA"), b = $("pImgB");
  const next = a.classList.contains("show") ? b : a, prev = next === a ? b : a;
  if (!url) { $("pSlide").classList.add("hidden"); return; }
  next.onload = () => { next.classList.add("show"); prev.classList.remove("show"); };
  next.src = url;
  $("pCaption").textContent = caption || "";
  $("pSlide").classList.remove("hidden");
}

async function pLoadTrip(gen) {
  const id = P.queue[P.qi];
  const t = await api(`trips/${id}`);
  if (gen !== P.gen) return false;
  P.trip = t;
  state.tripIds = new Set(t.ids);
  applyFilter();
  P.stop = -1;
  pDrawRoute(-1);
  t.route.slice(0, 2).forEach(s => pSample(s.ids, SLIDES_PER_STOP).forEach(pImage));
  return true;
}

async function pIntro(gen) {
  P.phase = "intro";
  pUi();
  const t = P.trip;
  $("pIntroSub").textContent = P.queue.length > 1 ? `${P.label} · Reise ${P.qi + 1} von ${P.queue.length}` : "Reise nachspielen";
  $("pIntroTitle").textContent = t.title;
  $("pIntroDates").textContent = `${dayRange(t.start, t.end)} · ${t.days} Tag${t.days === 1 ? "" : "e"} · ${t.route.length} Halt${t.route.length === 1 ? "" : "e"}`;
  $("pIntro").classList.remove("hidden");
  $("pSlide").classList.add("hidden");
  flyToBbox(t.bbox);
  const ok = await pWait(3200, gen);
  $("pIntro").classList.add("hidden");
  return ok;
}

async function pFly(i, gen) {
  P.phase = "fly";
  P.stop = i;
  pUi();
  const t = P.trip, s = t.route[i], prev = t.route[i - 1];
  const dist = prev ? pKm(prev, s) : 300;
  const duration = Math.min(7000, Math.max(1800, 1400 + dist * 6)) / pSpeed();
  const zoom = state.styleOnline ? (t.route.length > 1 && dist < 15 ? 13 : 11) : 5.5;
  // Halt in die freie Fläche neben (Desktop) bzw. unter (Handy) die Diashow rücken
  const narrow = window.innerWidth < 720;
  const slideW = Math.min(window.innerWidth * 0.46, 640) + 48;
  const padding = narrow ? { top: Math.min(window.innerWidth * 0.75, 420), bottom: 170, left: 0, right: 0 }
                         : { top: 0, bottom: 120, left: 0, right: slideW };
  state.map.flyTo({ center: [s.lon, s.lat], zoom, pitch: state.styleOnline ? 50 : 20, padding,
                    bearing: ((i * 37) % 80) - 40, duration, essential: true });
  const t0 = performance.now();
  const tick = () => {
    if (gen !== P.gen) return;
    const k = Math.min(1, (performance.now() - t0) / duration);
    pDrawRoute(i, k);
    if (k < 1) P.raf = requestAnimationFrame(tick);
  };
  if (i > 0) P.raf = requestAnimationFrame(tick); else pDrawRoute(0);
  // nächste Bilder schon laden
  pSample(s.ids, SLIDES_PER_STOP).forEach(pImage);
  if (t.route[i + 1]) pSample(t.route[i + 1].ids, SLIDES_PER_STOP).forEach(pImage);
  const ok = await pWait(duration * pSpeed() + 300, gen);
  pDrawRoute(i, 1);
  return ok;
}

async function pSlides(i, gen, from = 0) {
  P.phase = "slides";
  const s = P.trip.route[i];
  P.slideIds = pSample(s.ids, SLIDES_PER_STOP);
  const infoById = new Map((P.info || []).map(x => [x.id, x]));
  for (let k = from; k < P.slideIds.length; k++) {
    P.slide = k;
    pUi();
    const id = P.slideIds[k];
    const url = await pImage(id);
    if (gen !== P.gen) return false;
    const inf = infoById.get(id);
    pShowSlide(url, [s.label, inf ? deDateTime(inf.taken_at) : "", inf && inf.media === "video" ? "▶ Video" : ""].filter(Boolean).join(" · "));
    if (!(await pWait(SLIDE_MS, gen))) return false;
  }
  return true;
}

async function pRun(resume = false) {
  const gen = ++P.gen;
  P.playing = true;
  pUi();
  try {
    if (!P.trip) {
      if (!(await pLoadTrip(gen))) return;
      P.info = await api("photos/info", { method: "POST", body: { ids: P.trip.ids.slice(0, 2000) } });
      if (gen !== P.gen || !(await pIntro(gen))) return;
    }
    let i = P.stop < 0 ? 0 : P.stop;
    let fromSlide = resume && P.phase === "slides" ? P.slide : 0;
    let needFly = !(resume && P.phase === "slides");
    for (; i < P.trip.route.length; i++) {
      if (needFly && !(await pFly(i, gen))) return;
      if (!(await pSlides(i, gen, fromSlide))) return;
      fromSlide = 0;
      needFly = true;
    }
    // Reise fertig: Überblick, dann nächste Reise des Jahres oder Ende
    $("pSlide").classList.add("hidden");
    flyToBbox(P.trip.bbox);
    if (P.qi < P.queue.length - 1) {
      if (!(await pWait(2500, gen))) return;
      P.qi++;
      P.trip = null;
      return pRun();
    }
    P.phase = "end";
    P.playing = false;
    pUi();
  } catch (e) {
    notice(esc(e.message));
    P.playing = false;
    pUi();
  }
}

function pPause() {
  pCancel();
  P.playing = false;
  pUi();
}

function pJump(delta) {
  if (!P.trip) return;
  pCancel();
  $("pIntro").classList.add("hidden");
  let i = P.stop + delta;
  if (i < 0) {   // vor den ersten Halt: vorige Reise des Jahres
    if (P.qi > 0) { P.qi--; P.trip = null; P.stop = -1; return pRun(); }
    i = 0;
  }
  if (i >= P.trip.route.length) {   // hinter den letzten Halt: nächste Reise
    if (P.qi < P.queue.length - 1) { P.qi++; P.trip = null; P.stop = -1; return pRun(); }
    i = P.trip.route.length - 1;
  }
  P.stop = i;
  P.phase = "fly";
  pRun(true);
}

function startPlayer(tripIds, label, returnTo) {
  if (!tripIds.length) return;
  pCancel();
  P.queue = tripIds; P.qi = 0; P.trip = null; P.stop = -1; P.phase = "idle"; P.label = label || "";
  P.returnTo = returnTo || null;
  P.speed = Number(store.get("fg_speed") || 1);
  $("pSpeed").value = String(P.speed);
  closeLightbox();
  $("panel").classList.add("hidden");
  $("player").classList.remove("hidden");
  document.body.classList.add("playing");
  pRun();
}

function stopPlayer() {
  pCancel();
  P.playing = false;
  P.phase = "idle";
  $("player").classList.add("hidden");
  $("pSlide").classList.add("hidden");
  $("pIntro").classList.add("hidden");
  document.body.classList.remove("playing");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  state.map.easeTo({ pitch: 0, bearing: 0, padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 800 });
  for (const u of P.cache.values()) u.then(x => x && URL.revokeObjectURL(x));
  P.cache.clear();
  const back = P.returnTo;
  P.trip = null;
  if (back) openTrip(back); else { leaveTrip(); state.tripIds = null; setRoute(null); applyFilter(); }
}

$("pPlay").addEventListener("click", () => {
  if (P.phase === "end") { P.qi = 0; P.trip = null; P.stop = -1; P.phase = "idle"; return pRun(); }
  P.playing ? pPause() : pRun(true);
});
$("pPrev").addEventListener("click", () => pJump(-1));
$("pNext").addEventListener("click", () => pJump(1));
$("pClose").addEventListener("click", stopPlayer);
$("pSpeed").addEventListener("change", () => { P.speed = Number($("pSpeed").value) || 1; store.set("fg_speed", String(P.speed)); });
$("pFull").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else document.documentElement.requestFullscreen().catch(() => notice("Vollbild ist hier nicht erlaubt (z. B. im DSM-Fenster) – F11 im Browser hilft."));
});
document.addEventListener("keydown", (e) => {
  if ($("player").classList.contains("hidden") || !$("lightbox").classList.contains("hidden")) return;
  if (e.target && /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === " ") { e.preventDefault(); $("pPlay").click(); }
  else if (e.key === "ArrowRight") pJump(1);
  else if (e.key === "ArrowLeft") pJump(-1);
  else if (e.key === "Escape") stopPlayer();
  else if (e.key === "f" || e.key === "F") $("pFull").click();
}, true);
// Wer die Karte anfasst, pausiert die Fahrt
$("map").addEventListener("pointerdown", () => { if (P.playing && P.phase !== "intro") pPause(); });
