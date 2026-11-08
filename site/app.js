(() => {
  "use strict";

  const CATS = {
    concert:   { label: "Concerts",   one: "Concert",   emoji: "🎤" },
    football:  { label: "Football",   one: "Football",  emoji: "⚽" },
    rugby:     { label: "Rugby",      one: "Rugby",     emoji: "🏉" },
    basket:    { label: "Basket",     one: "Basket",    emoji: "🏀" },
    hockey:    { label: "Hockey",     one: "Hockey",    emoji: "🏒" },
    sport:     { label: "Autres sports", one: "Sport",  emoji: "🏟️" },
    spectacle: { label: "Spectacles", one: "Spectacle", emoji: "🎭" },
    autre:     { label: "Autres",     one: "Événement", emoji: "✨" },
  };
  const PAGE = 60;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
  const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // Dates calculées à l'heure de Paris, quel que soit le fuseau du visiteur.
  const parisISO = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const weekday = (iso) => new Date(iso + "T12:00:00Z").getUTCDay(); // 0 = dimanche
  const TODAY = parisISO(new Date());

  const fmtDay = (iso) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: iso.slice(0, 4) !== TODAY.slice(0, 4) ? "numeric" : undefined, timeZone: "UTC" });
  const relDay = (iso) => iso === TODAY ? "Aujourd'hui" : iso === addDays(TODAY, 1) ? "Demain" : "";

  const DATE_FILTERS = [
    { id: "all", label: "Toutes les dates", test: () => true },
    { id: "today", label: "Aujourd'hui", test: (d) => d === TODAY },
    { id: "weekend", label: "Ce week-end", test: (d) => {
      const wd = weekday(TODAY);
      const fri = wd === 0 ? addDays(TODAY, -2) : wd === 6 ? addDays(TODAY, -1) : addDays(TODAY, 5 - wd);
      const sun = addDays(fri, 2);
      return d >= (TODAY > fri ? TODAY : fri) && d <= sun;
    } },
    { id: "7", label: "7 jours", test: (d) => d <= addDays(TODAY, 6) },
    { id: "30", label: "30 jours", test: (d) => d <= addDays(TODAY, 29) },
    { id: "pick", label: "Choisir une date", test: (d) => !state.pick || d === state.pick },
  ];

  const state = { q: "", cat: "", date: "all", pick: "", venue: "", onlyNew: false, view: "agenda", limit: PAGE };
  let DATA = { events: [], venues: [], sources: {} };
  let venueById = {};

  // ------------------------------------------------------------ URL state
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.q = p.get("q") || "";
    state.cat = p.get("cat") || "";
    state.date = p.get("date") || "all";
    state.pick = p.get("jour") || "";
    state.venue = p.get("lieu") || "";
    state.onlyNew = p.get("new") === "1";
    state.view = p.get("vue") === "lieux" ? "venues" : "agenda";
  }
  function writeHash() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.cat) p.set("cat", state.cat);
    if (state.date !== "all") p.set("date", state.date);
    if (state.date === "pick" && state.pick) p.set("jour", state.pick);
    if (state.venue) p.set("lieu", state.venue);
    if (state.onlyNew) p.set("new", "1");
    if (state.view === "venues") p.set("vue", "lieux");
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  // ------------------------------------------------------------ filtering
  const isNew = (e) => e.firstSeen && e.firstSeen >= addDays(TODAY, -2);
  function baseFilter(e, skip) {
    if (e.date < TODAY) return false;
    if (skip !== "cat" && state.cat && e.category !== state.cat) return false;
    if (state.venue && e.venueId !== state.venue && e.venue !== state.venue) return false;
    if (state.onlyNew && !isNew(e)) return false;
    const df = DATE_FILTERS.find((f) => f.id === state.date) || DATE_FILTERS[0];
    if (!df.test(e.date)) return false;
    if (state.q) {
      const hay = fold([e.title, e.venue, e.city, e.genre, e.competition, CATS[e.category]?.one].join(" "));
      if (!fold(state.q).split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  // ------------------------------------------------------------ rendering
  function renderCats() {
    const counts = {};
    let total = 0;
    for (const e of DATA.events) if (baseFilter(e, "cat")) { counts[e.category] = (counts[e.category] || 0) + 1; total++; }
    const order = Object.keys(CATS).filter((c) => counts[c] || c === state.cat);
    $("#cats").innerHTML =
      `<button class="chip ${state.cat ? "" : "active"}" data-cat="">Tout <span class="n">${total}</span></button>` +
      order.map((c) => `<button class="chip ${state.cat === c ? "active" : ""}" data-cat="${c}" style="--c:var(--c-${c})"><span class="dot"></span>${CATS[c].label} <span class="n">${counts[c] || 0}</span></button>`).join("");
  }

  function renderDates() {
    $("#dates").innerHTML = DATE_FILTERS.map((f) =>
      f.id === "pick"
        ? `<input type="date" id="pick" min="${TODAY}" value="${esc(state.pick)}" aria-label="Choisir une date" class="${state.date === "pick" ? "active" : ""}">`
        : `<button class="chip ${state.date === f.id ? "active" : ""}" data-date="${f.id}">${f.label}</button>`).join("");
  }

  function renderVenueSelect() {
    const counts = {};
    for (const e of DATA.events) if (e.date >= TODAY) { const k = e.venueId || e.venue; counts[k] = (counts[k] || 0) + 1; }
    const known = DATA.venues.filter((v) => counts[v.id]).map((v) => ({ id: v.id, name: v.name, n: counts[v.id] }));
    const others = Object.keys(counts).filter((k) => !venueById[k] && k !== "Lieu à confirmer")
      .map((k) => ({ id: k, name: k, n: counts[k] })).sort((a, b) => b.n - a.n);
    const opt = (v) => `<option value="${esc(v.id)}" ${state.venue === v.id ? "selected" : ""}>${esc(v.name)} (${v.n})</option>`;
    $("#venue").innerHTML = `<option value="">Tous les lieux</option>` +
      (known.length ? `<optgroup label="Grandes salles et stades">${known.sort((a, b) => b.n - a.n).map(opt).join("")}</optgroup>` : "") +
      (others.length ? `<optgroup label="Autres lieux">${others.map(opt).join("")}</optgroup>` : "");
  }

  const PIN = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a7 7 0 0 1 7 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 0 1 7-7Zm0 4.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z"/></svg>`;
  const MAP = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5.5-6-2-6 2.25v15l6-2.25 6 2 6-2.25v-15L15 5.5Zm-1 12.6-4-1.33V5.9l4 1.33v10.87Z"/></svg>`;
  const CAL = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 2h2v2h6V2h2v2h3a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3V2Zm12 8H5v9h14v-9Z"/></svg>`;
  const TICKET = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v3a3 3 0 0 0 0 6v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a3 3 0 0 0 0-6V6Zm11 1v2h2V7h-2Zm0 4v2h2v-2h-2Zm0 4v2h2v-2h-2Z"/></svg>`;

  function price(e) {
    if (e.priceMin == null) return "";
    const f = (n) => Number(n).toLocaleString("fr-FR", { style: "currency", currency: e.currency || "EUR", maximumFractionDigits: Number(n) % 1 ? 2 : 0 });
    return e.priceMax && e.priceMax !== e.priceMin ? `De ${f(e.priceMin)} à ${f(e.priceMax)}` : `À partir de ${f(e.priceMin)}`;
  }

  function mapsUrl(e) {
    const q = e.lat && e.lng ? `${e.lat},${e.lng}` : [e.venue, e.address, e.city || "Lyon"].filter(Boolean).join(", ");
    return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(q);
  }

  function card(e) {
    const c = CATS[e.category] ? e.category : "autre";
    const img = safeUrl(e.image);
    const sport = ["football", "rugby", "basket", "hockey"].includes(c);
    const media = img
      ? `<div class="media ${sport && /crest|badge|logo|\.svg|\.png$/i.test(img) ? "crest" : ""}" style="--c:var(--c-${c})"><img src="${esc(img)}" alt="" loading="lazy" onerror="this.parentNode.classList.add('placeholder');this.parentNode.classList.remove('crest');this.outerHTML='${CATS[c].emoji}'"></div>`
      : `<div class="media placeholder" style="--c:var(--c-${c})">${CATS[c].emoji}</div>`;
    const tUrl = safeUrl(e.ticketUrl);
    const vendor = e.vendor || "la billetterie";
    const alts = (e.altTickets || []).filter((a) => safeUrl(a.url));
    return `<article class="card">
      <div class="mwrap">${media}</div>
      <div class="body">
        <div class="meta-top"><span class="time">${e.time ? esc(e.time.replace(":", "h")) : "Horaire à venir"}</span>
          <span class="badge cat" style="--c:var(--c-${c})">${esc(e.genre && c === "concert" ? e.genre : CATS[c].one)}</span>
          ${e.competition ? `<span class="tag">${esc(e.competition)}</span>` : ""}</div>
        ${isNew(e) || e.status ? `<div class="tags">${isNew(e) ? `<span class="badge new">Nouveau</span>` : ""}${e.status ? `<span class="badge warn">${esc(e.status)}</span>` : ""}</div>` : ""}
        <h3 class="title">${esc(e.title)}</h3>
        <div class="place">${PIN}<span><b>${esc(e.venue)}</b>${e.city ? ` · ${esc(e.city)}` : ""}</span></div>
        ${price(e) ? `<div class="price">${price(e)}</div>` : ""}
        <div class="actions">
          ${tUrl ? `<a class="btn primary" href="${esc(tUrl)}" target="_blank" rel="noopener">${TICKET} Billets sur ${esc(vendor)}</a>` : ""}
          <a class="btn icon" href="${esc(mapsUrl(e))}" target="_blank" rel="noopener" title="Itinéraire" aria-label="Itinéraire vers ${esc(e.venue)}">${MAP}</a>
          <button class="btn icon" data-ics="${esc(e.id)}" title="Ajouter à mon agenda" aria-label="Ajouter à mon agenda">${CAL}</button>
        </div>
        ${alts.length ? `<div class="alt">Aussi sur ${alts.map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.vendor)}</a>`).join(", ")}</div>` : ""}
      </div>
    </article>`;
  }

  function renderAgenda() {
    const list = DATA.events.filter((e) => baseFilter(e));
    const shown = list.slice(0, state.limit);
    $("#count").textContent = list.length ? `${list.length} événement${list.length > 1 ? "s" : ""}` : "";
    if (!DATA.events.length) {
      $("#agenda").innerHTML = `<div class="empty"><strong>La première mise à jour n'a pas encore eu lieu</strong>Les événements apparaîtront ici après le prochain passage du robot quotidien.</div>`;
      return;
    }
    if (!list.length) {
      $("#agenda").innerHTML = `<div class="empty"><strong>Aucun événement ne correspond</strong>Essaie d'élargir la période ou de retirer un filtre.<div class="more"><button class="btn" id="reset">Réinitialiser les filtres</button></div></div>`;
      return;
    }
    const groups = new Map();
    for (const e of shown) { if (!groups.has(e.date)) groups.set(e.date, []); groups.get(e.date).push(e); }
    let html = "";
    for (const [d, evs] of groups) {
      evs.sort((a, b) => (a.time || "99").localeCompare(b.time || "99"));
      html += `<div class="day"><h2 class="day-head"><span class="d">${esc(fmtDay(d))}</span>${relDay(d) ? `<span class="rel">${relDay(d)}</span>` : ""}</h2><div class="grid">${evs.map(card).join("")}</div></div>`;
    }
    if (list.length > shown.length) html += `<div class="more"><button class="btn" id="more">Afficher plus (${list.length - shown.length} restants)</button></div>`;
    $("#agenda").innerHTML = html;
  }

  function renderVenues() {
    const by = {};
    for (const e of DATA.events) if (e.date >= TODAY && e.venueId) (by[e.venueId] ||= []).push(e);
    const vs = [...DATA.venues].sort((a, b) => (by[b.id]?.length || 0) - (by[a.id]?.length || 0));
    $("#count").textContent = `${vs.length} lieux suivis`;
    $("#venues").innerHTML = `<div class="venue-grid">${vs.map((v) => {
      const evs = by[v.id] || [];
      const next = evs[0];
      return `<div class="venue">
        <span class="kind">${esc(v.type || "Lieu")}</span>
        <h3>${esc(v.name)}</h3>
        <p class="addr">${esc(v.address || v.city)}</p>
        <p class="next">${next ? `Prochain : <b>${esc(next.title)}</b>, ${esc(fmtDay(next.date))}` : "Aucun événement trouvé pour l'instant"}</p>
        <div class="actions">
          ${evs.length ? `<button class="btn primary" data-venue="${esc(v.id)}">${evs.length} événement${evs.length > 1 ? "s" : ""}</button>` : ""}
          ${safeUrl(v.ticketing || v.website) ? `<a class="btn" href="${esc(v.ticketing || v.website)}" target="_blank" rel="noopener">Site officiel</a>` : ""}
          <a class="btn icon" href="${esc(mapsUrl({ lat: v.lat, lng: v.lng, venue: v.name, address: v.address }))}" target="_blank" rel="noopener" aria-label="Itinéraire">${MAP}</a>
        </div>
      </div>`;
    }).join("")}</div>`;
  }

  function render() {
    renderCats(); renderDates(); renderVenueSelect();
    $("#q").value = state.q;
    $("#onlyNew").checked = state.onlyNew;
    document.querySelectorAll(".tab").forEach((t) => { const on = t.dataset.view === state.view; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
    $("#agenda").hidden = state.view !== "agenda";
    $("#cats").hidden = $(".filters-row").hidden = state.view !== "agenda";
    $("#venues").hidden = state.view !== "venues";
    state.view === "agenda" ? renderAgenda() : renderVenues();
    writeHash();
  }

  // ------------------------------------------------------------ calendar (.ics)
  function ics(e) {
    const pad = (n) => String(n).padStart(2, "0");
    const stamp = (d) => `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}00Z`;
    const start = new Date(e.start);
    const end = e.end ? new Date(e.end) : new Date(start.getTime() + (e.category === "concert" ? 3 : 2) * 3600e3);
    const t = (s) => String(s || "").replace(/[\\,;]/g, (m) => "\\" + m).replace(/\n/g, "\\n");
    const dates = e.time
      ? `DTSTART:${stamp(start)}\r\nDTEND:${stamp(end)}`
      : `DTSTART;VALUE=DATE:${e.date.replace(/-/g, "")}\r\nDTEND;VALUE=DATE:${addDays(e.date, 1).replace(/-/g, "")}`;
    const body = `BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Lyon Events//FR\r\nBEGIN:VEVENT\r\nUID:${e.id}@lyon-events\r\nDTSTAMP:${stamp(new Date())}\r\n${dates}\r\nSUMMARY:${t(e.title)}\r\nLOCATION:${t([e.venue, e.address, e.city].filter(Boolean).join(", "))}\r\nURL:${t(e.ticketUrl)}\r\nDESCRIPTION:${t("Billets : " + (e.ticketUrl || ""))}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type: "text/calendar" }));
    a.download = (e.title || "evenement").replace(/[^\w\- ]+/g, "").slice(0, 50) + ".ics";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ------------------------------------------------------------ events
  let qTimer;
  $("#q").addEventListener("input", (ev) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = ev.target.value.trim(); state.limit = PAGE; render(); }, 150); });
  $("#venue").addEventListener("change", (ev) => { state.venue = ev.target.value; state.limit = PAGE; state.view = "agenda"; render(); });
  $("#onlyNew").addEventListener("change", (ev) => { state.onlyNew = ev.target.checked; state.limit = PAGE; render(); });
  document.addEventListener("change", (ev) => {
    if (ev.target.id === "pick") { state.pick = ev.target.value; state.date = ev.target.value ? "pick" : "all"; state.limit = PAGE; render(); }
  });
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.cat !== undefined) { state.cat = b.dataset.cat; state.limit = PAGE; render(); }
    else if (b.dataset.date) { state.date = b.dataset.date; state.pick = ""; state.limit = PAGE; render(); }
    else if (b.dataset.view) { state.view = b.dataset.view; render(); }
    else if (b.dataset.venue) { state.venue = b.dataset.venue; state.view = "agenda"; state.limit = PAGE; render(); window.scrollTo({ top: 0, behavior: "smooth" }); }
    else if (b.dataset.ics) { const e = DATA.events.find((x) => x.id === b.dataset.ics); if (e) ics(e); }
    else if (b.id === "more") { state.limit += PAGE; render(); }
    else if (b.id === "reset") { Object.assign(state, { q: "", cat: "", date: "all", pick: "", venue: "", onlyNew: false, limit: PAGE }); render(); }
  });

  // ------------------------------------------------------------ load
  readHash();
  fetch("events.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((d) => {
      DATA = { events: d.events || [], venues: d.venues || [], sources: d.sources || {} };
      venueById = Object.fromEntries(DATA.venues.map((v) => [v.id, v]));
      const g = d.generatedAt ? new Date(d.generatedAt) : null;
      $("#updated").textContent = g ? `Mis à jour le ${g.toLocaleDateString("fr-FR", { day: "numeric", month: "long", timeZone: "Europe/Paris" })} à ${g.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" })}` : "";
      $("#sources").innerHTML = Object.entries(DATA.sources).map(([n, s]) =>
        `<li class="${s.ok ? "ok" : "ko"}">${esc(n)} : ${s.ok ? `${s.count} événement${s.count > 1 ? "s" : ""}` : "non utilisée"}</li>`).join("");
      render();
    })
    .catch(() => { $("#updated").textContent = ""; render(); });
})();
