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
  const words = (s) => fold(s).replace(/[^a-z0-9]+/g, " ").trim();

  // ------------------------------------------------------------ recherche
  // Genres Ticketmaster (en anglais) affichés et cherchables en français.
  const GENRE_FR = {
    "Cultural": "Culture", "Theatre": "Théâtre", "Variety": "Variétés", "Circus & Specialty Acts": "Cirque",
    "Dance": "Danse", "Chanson Francaise": "Chanson française", "Children's Theatre": "Jeune public",
    "Music": "Musique", "Spectacular": "Grand spectacle", "Dance/Electronic": "Électro",
    "Magic & Illusion": "Magie", "World": "Musiques du monde", "Religious": "Religieux",
    "Children's Music": "Musique jeune public", "Ice Shows": "Spectacle sur glace", "Classical": "Classique",
    "Opera": "Opéra", "Miscellaneous": "", "Comedy": "Humour", "Family": "Famille", "Fairs & Festivals": "Festival",
    "Country": "Country", "Alternative": "Alternatif", "Folk": "Folk", "Soul": "Soul", "Funk": "Funk",
  };
  const genreFr = (g) => (g in GENRE_FR ? GENRE_FR[g] : g || "");

  // Familles de mots équivalents : taper l'un trouve les événements qui contiennent n'importe quel autre.
  const SYN_GROUPS = [
    ["sport", "sports", "sportif", "sportive"],
    ["foot", "football", "soccer", "ol", "olympique lyonnais", "ligue 1"],
    ["rugby", "lou", "top 14"],
    ["basket", "basketball", "asvel", "euroleague", "betclic elite"],
    ["hockey"],
    ["concert", "concerts", "musique", "music", "live", "tournee"],
    ["humour", "humoriste", "comique", "comedy", "stand up", "standup", "one man show", "one woman show", "sketch"],
    ["theatre", "piece", "comedie"],
    ["enfant", "enfants", "jeune public", "famille", "familial", "kids", "children", "jeunesse"],
    ["cirque", "circus", "acrobate", "acrobatie", "acrobaties"],
    ["danse", "dance", "ballet", "danseur", "danseurs", "choregraphie"],
    ["electro", "electronique", "electronic", "techno", "house", "dj", "clubbing"],
    ["rap", "hip hop", "hiphop", "rappeur"],
    ["classique", "classical", "orchestre", "symphonique", "philharmonique", "piano"],
    ["opera", "lyrique"],
    ["magie", "magicien", "magic", "illusion", "illusionniste", "mentaliste"],
    ["spectacle", "spectacles", "show"],
    ["chanson", "chanson francaise", "variete", "varietes", "variety"],
    ["metal", "hard rock", "heavy"],
    ["festival", "festivals", "fest"],
    ["jazz", "blues", "swing"],
    ["glace", "ice", "patinage"],
    ["expo", "exposition", "expositions", "musee", "galerie", "vernissage"],
    ["cinema", "film", "films", "projection", "documentaire"],
    ["conference", "debat", "rencontre", "dedicace"],
    ["atelier", "ateliers", "stage", "initiation"],
    ["visite", "visites", "balade", "patrimoine"],
  ];
  const SYN = {};
  for (const g of SYN_GROUPS) for (const w of g) SYN[w] = [...new Set([...(SYN[w] || []), ...g])];
  // Mots-clés ajoutés selon la catégorie de l'événement.
  const CAT_WORDS = {
    football: "sport match foot football", rugby: "sport match rugby", basket: "sport match basket",
    hockey: "sport match hockey", sport: "sport match", concert: "concert musique", spectacle: "spectacle",
  };
  const STOP = new Set(["de", "du", "des", "la", "le", "les", "l", "d", "un", "une", "et", "a", "au", "aux", "en", "pour", "sur", "avec", "a lyon", "lyon"]);

  function haystack(e) {
    if (!e._hay) {
      e._hay = " " + words([e.title, e.venue, e.city, e.genre, genreFr(e.genre), e.competition,
        CATS[e.category]?.one, CATS[e.category]?.label, CAT_WORDS[e.category], e.vendor, e.description,
        ...(e.seenOn || []).map((s) => "instagram " + s.account)].join(" ")) + " ";
    }
    return e._hay;
  }
  // Une alternative courte (« ol », « dj ») doit être un mot entier ; sinon le début d'un mot suffit.
  const hit = (hay, w) => hay.includes(" " + w + (w.length <= 3 ? " " : ""));
  function parseQuery(q) {
    let rest = " " + words(q) + " ";
    const terms = [];
    // Expressions de plusieurs mots d'abord (« stand up », « jeune public »).
    for (const k of Object.keys(SYN).filter((k) => k.includes(" ")).sort((a, b) => b.length - a.length)) {
      if (rest.includes(" " + k + " ")) { terms.push({ typed: k, alts: SYN[k] }); rest = rest.replace(" " + k + " ", " "); }
    }
    for (const w of rest.trim().split(" ")) {
      if (!w || STOP.has(w)) continue;
      const alts = [...(SYN[w] || [])];
      if (w.length > 3 && w.endsWith("s")) alts.push(w.slice(0, -1)); // pluriel : « concerts » -> « concert »
      terms.push({ typed: w, alts });
    }
    return terms;
  }
  // Le mot tapé peut être le début d'un mot (« transbo ») ; ses synonymes sont cherchés tels quels.
  const termHit = (hay, t) => (SYN[t.typed] ? hit(hay, t.typed) : hay.includes(" " + t.typed)) || t.alts.some((a) => hit(hay, a));

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
    state.view = p.get("vue") === "lieux" ? "venues" : p.get("vue") === "carte" ? "map" : "agenda";
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
    else if (state.view === "map") p.set("vue", "carte");
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  // ------------------------------------------------------------ filtering
  const isNew = (e) => e.firstSeen && e.firstSeen >= addDays(TODAY, -2);
  // loose = true : au moins un des mots suffit (résultats approchants quand la recherche exacte ne donne rien).
  let qTerms = [], loose = false;
  function baseFilter(e, skip) {
    if (e.date < TODAY) return false;
    if (skip !== "cat" && state.cat && e.category !== state.cat) return false;
    if (state.venue && e.venueId !== state.venue && e.venue !== state.venue) return false;
    if (state.onlyNew && !isNew(e)) return false;
    const df = DATE_FILTERS.find((f) => f.id === state.date) || DATE_FILTERS[0];
    if (!df.test(e.date)) return false;
    if (qTerms.length) {
      const hay = haystack(e);
      if (!(loose ? qTerms.some((t) => termHit(hay, t)) : qTerms.every((t) => termHit(hay, t)))) return false;
    }
    return true;
  }
  function prepareQuery() {
    qTerms = parseQuery(state.q);
    loose = false;
    if (qTerms.length > 1 && !DATA.events.some((e) => baseFilter(e))) loose = true;
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
    // Le champ date n'est créé qu'une fois : le recréer pendant la saisie fait perdre le focus.
    const pick = $("#pick");
    if (pick) {
      $("#dates").querySelectorAll("[data-date]").forEach((b) => b.classList.toggle("active", state.date === b.dataset.date));
      pick.classList.toggle("active", state.date === "pick");
      if (document.activeElement !== pick && pick.value !== state.pick) pick.value = state.pick;
      return;
    }
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

  // Agendas (pas des billetteries) : le bouton dit « Voir sur » plutôt que « Billets sur ».
  const INFO_SOURCES = new Set(["OpenAgenda", "Songkick", "Instagram"]);
  // Comptes Instagram qui ont annoncé l'événement (rapprochement fait par le robot quotidien).
  const seenOn = (e) => (e.seenOn || []).filter((s) => safeUrl(s.url));

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
          <span class="badge cat" style="--c:var(--c-${c})">${esc(genreFr(e.genre) || CATS[c].one)}</span>
          ${e.competition ? `<span class="tag">${esc(e.competition)}</span>` : ""}</div>
        ${isNew(e) || e.status ? `<div class="tags">${isNew(e) ? `<span class="badge new">Nouveau</span>` : ""}${e.status ? `<span class="badge warn">${esc(e.status)}</span>` : ""}</div>` : ""}
        <h3 class="title">${esc(e.title)}</h3>
        <div class="place">${PIN}<span><b>${esc(e.venue)}</b>${e.city ? ` · ${esc(e.city)}` : ""}</span></div>
        ${price(e) ? `<div class="price">${price(e)}</div>` : ""}
        <div class="actions">
          ${tUrl ? `<a class="btn primary" href="${esc(tUrl)}" target="_blank" rel="noopener">${TICKET} ${INFO_SOURCES.has(e.source) ? "Voir sur" : "Billets sur"} ${esc(vendor)}</a>` : ""}
          <a class="btn icon" href="${esc(mapsUrl(e))}" target="_blank" rel="noopener" title="Itinéraire" aria-label="Itinéraire vers ${esc(e.venue)}">${MAP}</a>
          <button class="btn icon" data-ics="${esc(e.id)}" title="Ajouter à mon agenda" aria-label="Ajouter à mon agenda">${CAL}</button>
        </div>
        ${alts.length ? `<div class="alt">Aussi sur ${alts.map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.vendor)}</a>`).join(", ")}</div>` : ""}
        ${e.source !== "Instagram" && seenOn(e).length ? `<div class="alt">Annoncé sur Instagram par ${seenOn(e).map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">@${esc(s.account)}</a>`).join(", ")}</div>` : ""}
      </div>
    </article>`;
  }

  function renderAgenda() {
    const list = DATA.events.filter((e) => baseFilter(e));
    const shown = list.slice(0, state.limit);
    $("#count").textContent = list.length
      ? `${list.length} événement${list.length > 1 ? "s" : ""}${loose ? ` contenant au moins un des mots de « ${state.q} » (aucun ne les contient tous)` : ""}`
      : "";
    if (!DATA.events.length) {
      $("#agenda").innerHTML = `<div class="empty"><strong>La première mise à jour n'a pas encore eu lieu</strong>Les événements apparaîtront ici après le prochain passage du robot quotidien.</div>`;
      return;
    }
    if (!list.length) {
      $("#agenda").innerHTML = `<div class="empty"><strong>Aucun événement ne correspond${state.q ? ` à « ${esc(state.q)} »` : ""}</strong>${state.q ? "Essaie un autre mot (par exemple « concert », « humour », « rugby », « enfants ») ou retire un filtre." : "Essaie d'élargir la période ou de retirer un filtre."}<div class="more"><button class="btn" id="reset">Réinitialiser les filtres</button></div></div>`;
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

  // ------------------------------------------------------------ carte
  const CENTER = [45.7578, 4.832]; // place Bellecour
  const NEAR_KM = 14; // cadrage de départ : la métropole, pas les villages à 40 km
  const LOCATE = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm8.94 3A9 9 0 0 0 13 3.06V1h-2v2.06A9 9 0 0 0 3.06 11H1v2h2.06A9 9 0 0 0 11 20.94V23h2v-2.06A9 9 0 0 0 20.94 13H23v-2h-2.06ZM12 19a7 7 0 1 1 0-14 7 7 0 0 1 0 14Z"/></svg>`;
  const FIT = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 3 2.3 2.3-2.89 2.87 1.42 1.42L18.7 6.7 21 9V3h-6ZM3 9l2.3-2.3 2.87 2.89 1.42-1.42L6.7 5.3 9 3H3v6Zm6 12-2.3-2.3 2.89-2.87-1.42-1.42L5.3 17.3 3 15v6h6Zm12-6-2.3 2.3-2.87-2.89-1.42 1.42 2.89 2.87L15 21h6v-6Z"/></svg>`;
  let map = null, clusters = null, legend = null, me = null, allBounds = null;
  const markers = new Map(); // clé du point -> { m: repère Leaflet, g: lieu et ses dates }
  const shortDay = (iso) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const when = (e) => shortDay(e.date) + (e.time ? " à " + e.time.replace(":", "h") : "");
  const pinCat = (c) => (CATS[c] ? c : "autre");
  const km = (a, b) => {
    const r = Math.PI / 180, x = (b[1] - a[1]) * r * Math.cos(((a[0] + b[0]) / 2) * r), y = (b[0] - a[0]) * r;
    return Math.hypot(x, y) * 6371;
  };

  function mapPopup(g) {
    const rows = g.evs.slice(0, 6).map((e) => {
      const t = safeUrl(e.ticketUrl);
      const name = t ? `<a href="${esc(t)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title);
      return `<li style="--c:var(--c-${pinCat(e.category)})"><span class="when">${esc(when(e))}</span>${name}</li>`;
    }).join("");
    const rest = g.evs.length - 6;
    return `<div class="map-pop">
      <h3>${esc(g.venue)}</h3><p class="muted">${esc(g.address || g.city)}</p>
      <ul>${rows}</ul>${rest > 0 ? `<p class="muted">et ${rest} autre${rest > 1 ? "s dates" : " date"}</p>` : ""}
      <div class="pop-actions">
        <button class="btn primary" data-venue="${esc(g.key)}">Voir l'agenda du lieu</button>
        <a class="btn icon" href="${esc(mapsUrl(g))}" target="_blank" rel="noopener" title="Itinéraire" aria-label="Itinéraire vers ${esc(g.venue)}">${MAP}</a>
      </div>
    </div>`;
  }

  // Repère d'un lieu : couleur de la catégorie la plus présente, taille selon le nombre de dates.
  function pinIcon(g) {
    const n = g.evs.length, s = n >= 50 ? 42 : n >= 10 ? 34 : 28;
    return L.divIcon({ className: "pin-wrap", html: `<span class="pin" style="--c:var(--c-${g.cat})">${n}</span>`, iconSize: [s, s] });
  }
  // Groupe de lieux proches : on affiche le total des dates, pas le nombre de lieux.
  function clusterIcon(cl) {
    const n = cl.getAllChildMarkers().reduce((t, m) => t + m.options.n, 0);
    const s = n >= 200 ? 48 : n >= 50 ? 42 : 36;
    return L.divIcon({ className: "pin-wrap", html: `<span class="cluster">${n}</span>`, iconSize: [s, s] });
  }

  function initMap() {
    map = L.map("mapbox").setView(CENTER, 12);
    // Fond OpenStreetMap, atténué en CSS pour que les repères ressortent (et assombri en thème sombre).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    }).addTo(map);
    clusters = L.markerClusterGroup
      ? L.markerClusterGroup({ maxClusterRadius: 60, showCoverageOnHover: false, disableClusteringAtZoom: 16, iconCreateFunction: clusterIcon })
      : L.layerGroup(); // si le module de regroupement ne charge pas, la carte marche quand même
    clusters.addTo(map);

    const tools = L.control({ position: "topleft" });
    tools.onAdd = () => {
      const box = L.DomUtil.create("div", "leaflet-bar map-tools");
      box.innerHTML = `<button type="button" data-tool="me" title="Autour de moi" aria-label="Autour de moi">${LOCATE}</button>` +
        `<button type="button" data-tool="all" title="Voir tous les lieux" aria-label="Voir tous les lieux">${FIT}</button>`;
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.on(box, "click", (ev) => {
        const b = ev.target.closest("button");
        if (b?.dataset.tool === "me") { $("#mapHead").textContent = "Recherche de ta position…"; map.locate({ setView: true, maxZoom: 14 }); }
        else if (b?.dataset.tool === "all" && allBounds) map.fitBounds(allBounds, { padding: [30, 30] });
      });
      return box;
    };
    tools.addTo(map);
    legend = L.control({ position: "bottomleft" });
    legend.onAdd = () => L.DomUtil.create("div", "map-legend");
    legend.addTo(map);

    map.on("moveend", renderMapList);
    map.on("locationfound", (ev) => {
      me?.remove();
      me = L.layerGroup([
        L.circle(ev.latlng, { radius: ev.accuracy, color: "#0a84ff", weight: 1, fillOpacity: 0.1, interactive: false }),
        L.circleMarker(ev.latlng, { radius: 7, color: "#fff", weight: 3, fillColor: "#0a84ff", fillOpacity: 1, interactive: false }),
      ]).addTo(map);
    });
    map.on("locationerror", () => { $("#mapHead").textContent = "Position introuvable : autorise la localisation dans ton navigateur, puis réessaie."; });

    // Liste à côté de la carte : un clic montre le lieu, le survol le met en avant.
    const list = $("#mapList");
    list.addEventListener("click", (ev) => {
      const x = markers.get(ev.target.closest("[data-pin]")?.dataset.pin);
      if (!x) return;
      if (matchMedia("(max-width: 860px)").matches) $("#mapbox").scrollIntoView({ behavior: "smooth", block: "center" });
      clusters.zoomToShowLayer ? clusters.zoomToShowLayer(x.m, () => x.m.openPopup()) : x.m.openPopup();
    });
    const hot = (ev, on) => markers.get(ev.target.closest("[data-pin]")?.dataset.pin)?.m.getElement()?.classList.toggle("hot", on);
    list.addEventListener("mouseover", (ev) => hot(ev, true));
    list.addEventListener("mouseout", (ev) => hot(ev, false));
  }

  function renderMap() {
    if (typeof L === "undefined") {
      $("#count").textContent = "La carte se charge depuis internet : vérifie ta connexion puis recharge la page.";
      return;
    }
    if (!map) initMap();
    // Un repère par lieu : les événements à venir (mêmes filtres que l'agenda) sont regroupés par coordonnées.
    const groups = new Map();
    let missing = 0;
    for (const e of DATA.events) {
      if (!baseFilter(e)) continue;
      if (e.lat == null || e.lng == null) { missing++; continue; }
      const k = e.lat.toFixed(4) + "," + e.lng.toFixed(4);
      if (!groups.has(k)) groups.set(k, { k, lat: e.lat, lng: e.lng, address: e.address || "", city: e.city || "", evs: [] });
      groups.get(k).evs.push(e);
    }
    clusters.clearLayers();
    markers.clear();
    let total = 0;
    const pts = [], near = [], cats = new Set();
    for (const g of groups.values()) {
      g.evs.sort((a, b) => (a.start || "").localeCompare(b.start || ""));
      total += g.evs.length;
      // Nom et catégorie du lieu : la salle connue en priorité, sinon l'orthographe la plus fréquente.
      const tally = (f) => { const t = {}; for (const e of g.evs) { const v = f(e); if (v) t[v] = (t[v] || 0) + 1; } return Object.keys(t).sort((a, b) => t[b] - t[a])[0]; };
      g.key = tally((e) => venueById[e.venueId] && e.venueId) || tally((e) => e.venueId || e.venue);
      g.venue = venueById[g.key]?.name || tally((e) => e.venue) || "Lieu à confirmer";
      g.cat = tally((e) => pinCat(e.category));
      cats.add(g.cat);
      const ll = [g.lat, g.lng];
      pts.push(ll);
      if (km(CENTER, ll) <= NEAR_KM) near.push(ll);
      const m = L.marker(ll, { icon: pinIcon(g), title: g.venue, n: g.evs.length, riseOnHover: true });
      m.bindPopup(() => mapPopup(g), { maxWidth: 320, minWidth: 260, autoPanPadding: [20, 20] });
      markers.set(g.k, { m, g });
    }
    const layers = [...markers.values()].map((x) => x.m);
    clusters.addLayers ? clusters.addLayers(layers) : layers.forEach((m) => clusters.addLayer(m));

    $("#count").textContent = groups.size
      ? `${total} événement${total > 1 ? "s" : ""} dans ${groups.size} lieu${groups.size > 1 ? "x" : ""}` +
        (missing ? ` (${missing} sans adresse précise, visible${missing > 1 ? "s" : ""} seulement dans l'agenda)` : "")
      : "Aucun événement à placer sur la carte avec ces filtres";
    legend.getContainer().innerHTML = Object.keys(CATS).filter((c) => cats.has(c))
      .map((c) => `<span style="--c:var(--c-${c})"><i></i>${CATS[c].label}</span>`).join("");
    legend.getContainer().hidden = !cats.size;

    map.invalidateSize();
    allBounds = pts.length ? L.latLngBounds(pts) : null;
    const frame = near.length ? near : pts;
    if (frame.length) map.fitBounds(frame, { padding: [30, 30], maxZoom: 15 });
    renderMapList();
  }

  // Les lieux visibles dans le cadre de la carte, du plus chargé au moins chargé.
  function renderMapList() {
    if (!map || state.view !== "map") return;
    const box = map.getBounds();
    const shown = [...markers.values()].map((x) => x.g).filter((g) => box.contains([g.lat, g.lng]))
      .sort((a, b) => b.evs.length - a.evs.length);
    const dates = shown.reduce((t, g) => t + g.evs.length, 0);
    $("#mapHead").textContent = !markers.size ? ""
      : shown.length ? `${shown.length} lieu${shown.length > 1 ? "x" : ""} dans cette zone, ${dates} date${dates > 1 ? "s" : ""}`
      : "Aucun lieu dans cette zone : dézoome ou déplace la carte.";
    const MAX = 40;
    $("#mapList").innerHTML = shown.slice(0, MAX).map((g) => `<li><button type="button" class="map-item" data-pin="${esc(g.k)}" style="--c:var(--c-${g.cat})">
        <span class="n">${g.evs.length}</span>
        <span class="txt"><b>${esc(g.venue)}</b>${g.city ? `<span class="sub">${esc(g.city)}</span>` : ""}
          <span class="next">${esc(g.evs[0].title)}, ${esc(when(g.evs[0]))}</span></span>
      </button></li>`).join("") +
      (shown.length > MAX ? `<li class="map-more">Et ${shown.length - MAX} autres lieux : zoome pour les voir.</li>` : "");
  }

  function render() {
    prepareQuery();
    renderCats(); renderDates(); renderVenueSelect();
    $("#q").value = state.q;
    $("#onlyNew").checked = state.onlyNew;
    document.querySelectorAll(".tab").forEach((t) => { const on = t.dataset.view === state.view; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
    $("#agenda").hidden = state.view !== "agenda";
    $("#cats").hidden = $(".filters-row").hidden = state.view === "venues";
    $("#venues").hidden = state.view !== "venues";
    $("#map").hidden = state.view !== "map";
    state.view === "agenda" ? renderAgenda() : state.view === "venues" ? renderVenues() : renderMap();
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
    // Chrome valide la date dès le premier chiffre de l'année (0002-…) : on attend l'année complète.
    if (ev.target.id === "pick" && ev.target.value && ev.target.value < "1000") return;
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
