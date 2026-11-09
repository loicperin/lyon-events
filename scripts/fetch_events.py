#!/usr/bin/env python3
"""Récupère les événements à Lyon depuis plusieurs sources et écrit site/events.json.

Sources (chacune est optionnelle, une source en échec n'arrête pas les autres) :
  - Ticketmaster Discovery API   (clé : TICKETMASTER_API_KEY)  concerts, spectacles, sport
  - football-data.org            (clé : FOOTBALL_DATA_API_KEY) matchs à domicile de l'OL
  - TheSportsDB (clé gratuite)   prochain match à domicile OL / LOU / ASVEL
  - OpenAgenda                   (clé : OPENAGENDA_API_KEY)    agendas listés dans la config
  - Données structurées schema.org (JSON-LD) publiées par les salles, en respectant robots.txt
  - data/manual.json             événements ajoutés à la main

Uniquement la bibliothèque standard Python : aucune dépendance à installer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
OUT = ROOT / "site" / "events.json"
MANUAL = ROOT / "data" / "manual.json"
PARIS = ZoneInfo("Europe/Paris")
UA = "LyonEventsBot/1.0 (+agrégateur personnel d'événements; respecte robots.txt)"
NOW = dt.datetime.now(PARIS)
HORIZON = NOW + dt.timedelta(days=CONFIG.get("horizonDays", 365))

VENUES = {v["id"]: v for v in CONFIG["venues"]}
report: dict[str, dict] = {}


# --------------------------------------------------------------------------- utils
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
         "Accept-Language": "fr-FR,fr;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def get_json(url: str, headers: dict | None = None):
    return json.loads(http_get(url, headers).decode("utf-8"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def too_far(lat, lng) -> bool:
    """Vrai si des coordonnées sont connues et hors du rayon autour de Lyon."""
    try:
        c = CONFIG["center"]
        return distance_km(float(lat), float(lng), c["lat"], c["lng"]) > c["radiusKm"]
    except (TypeError, ValueError):
        return False


def match_venue(name: str, city: str = "") -> str | None:
    n = norm(name)
    if not n:
        return None
    best, best_len = None, 0
    for v in CONFIG["venues"]:
        for a in [v["name"], *v.get("aliases", [])]:
            an = norm(a)
            if an and (an == n or f" {an} " in f" {n} " or (len(n) > 5 and n in an)) and len(an) > best_len:
                best, best_len = v["id"], len(an)
    return best


def geohash(lat: float, lng: float, precision: int = 7) -> str:
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_r, lng_r = [-90.0, 90.0], [-180.0, 180.0]
    bits, bit, ch, even, out = [16, 8, 4, 2, 1], 0, 0, True, ""
    while len(out) < precision:
        rng, val = (lng_r, lng) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val > mid:
            ch |= bits[bit]
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out += base32[ch]
            bit, ch = 0, 0
    return out


def parse_dt(value: str | None, assume_tz=PARIS) -> dt.datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(v)
    except ValueError:
        try:
            d = dt.datetime.strptime(v[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=assume_tz)
    return d.astimezone(PARIS)


def make_event(*, title, start, source, category="autre", venue_name="", venue_id=None,
               city="", address="", lat=None, lng=None, ticket_url="", vendor="",
               image="", price_min=None, price_max=None, currency="EUR", genre="",
               status="", has_time=True, competition="", end=None, description=""):
    if not title or not start:
        return None
    if start < NOW - dt.timedelta(hours=6) or start > HORIZON:
        return None
    vid = venue_id or match_venue(venue_name, city)
    v = VENUES.get(vid or "", {})
    ev = {
        "title": pretty(html.unescape(title).strip(), True),
        "category": category,
        "genre": genre,
        "competition": competition,
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M") if has_time else None,
        "venueId": vid,
        "venue": v.get("name") or pretty(venue_name) or "Lieu à confirmer",
        "city": v.get("city") or pretty(city),
        "address": v.get("address") or address,
        "lat": v.get("lat", lat),
        "lng": v.get("lng", lng),
        "ticketUrl": ticket_url or v.get("ticketing") or v.get("website") or "",
        "vendor": vendor,
        "image": image,
        "priceMin": price_min,
        "priceMax": price_max,
        "currency": currency,
        "status": status,
        "description": (description or "")[:400],
        "source": source,
    }
    ev["id"] = hashlib.sha1(f"{norm(ev['title'])}|{ev['date']}|{vid or norm(venue_name)}".encode()).hexdigest()[:12]
    return ev


KEEP_UPPER = {"DJ", "MC", "OL", "LOU", "ASVEL", "LDLC", "II", "III", "IV", "VI", "TV", "UK", "USA", "ABBA",
              "AC/DC", "NTM", "IAM", "PNL", "SCH", "JUL", "RnB", "R&B", "XXL", "VIP", "BD", "ONL", "LGBT", "MJC", "EP"}
SMALL = {"de", "du", "des", "la", "le", "les", "et", "en", "a", "à", "au", "aux", "sur", "pour", "par", "avec",
         "un", "une", "of", "the", "and", "in", "on", "w", "x", "vs", "feat"}


def pretty(s: str, dedupe_parts: bool = False) -> str:
    """Remet en forme les textes tout en MAJUSCULES venant des billetteries."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if dedupe_parts:  # « X - X - Y » devient « X - Y »
        parts = [p.strip() for p in re.split(r"\s+-\s+", s)]
        out = []
        for p in parts:
            if not out or norm(p) != norm(out[-1]):
                out.append(p)
        s = " - ".join(out)
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4 or any(c.islower() for c in letters):
        return s

    def word(w: str, first: bool) -> str:
        core = w.strip("()[]«»\"!?.,:;")
        if core.upper() in KEEP_UPPER or (len(core) <= 3 and re.fullmatch(r"[A-Z]\.?(?:[A-Z]\.?)+", core) and "." in core):
            return w
        lw = w.lower()
        if not first and core.lower() in SMALL:
            return lw
        m = re.match(r"^([ld]['’])(.+)$", lw)
        if m:  # l'amphitheatre -> L'Amphitheatre
            pre = m.group(1) if not first else m.group(1).capitalize()
            return pre + m.group(2)[:1].upper() + m.group(2)[1:]
        return re.sub(r"(^|[-/(\"«])(\w)", lambda x: x.group(1) + x.group(2).upper(), lw)

    words = s.split(" ")
    return " ".join(word(w, i == 0 or words[i - 1] in ("-", ":", "–")) for i, w in enumerate(words))


def vendor_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    for key, label in [("ticketmaster", "Ticketmaster"), ("fnacspectacles", "Fnac Spectacles"),
                       ("francebillet", "France Billet"), ("seetickets", "See Tickets"),
                       ("digitick", "See Tickets"), ("shotgun", "Shotgun"), ("dice.fm", "DICE"),
                       ("weezevent", "Weezevent"), ("billetweb", "Billetweb"),
                       ("helloasso", "HelloAsso"), ("ol.fr", "Billetterie OL"),
                       ("lourugby", "Billetterie LOU"), ("eventbrite", "Eventbrite"),
                       ("ticketac", "Ticketac"), ("festik", "Festik"), ("songkick", "Songkick"),
                       ("openagenda", "OpenAgenda")]:
        if key in host:
            return label
    return host.replace("www.", "") if host else ""


# ------------------------------------------------------------------ Ticketmaster
TM_SEGMENTS = {"Music": "concert", "Arts & Theatre": "spectacle", "Sports": "sport",
               "Film": "autre", "Miscellaneous": "autre"}


def tm_category(cls: dict) -> tuple[str, str]:
    seg = (cls.get("segment") or {}).get("name", "")
    genre = (cls.get("genre") or {}).get("name", "")
    sub = (cls.get("subGenre") or {}).get("name", "")
    cat = TM_SEGMENTS.get(seg, "autre")
    g = norm(genre + " " + sub)
    if cat == "sport":
        if "soccer" in g or "football" in g:
            cat = "football"
        elif "rugby" in g:
            cat = "rugby"
        elif "basket" in g:
            cat = "basket"
        elif "hockey" in g:
            cat = "hockey"
    if cat == "spectacle" and ("comedy" in g or "humour" in g):
        genre = "Humour"
    if genre in ("Undefined", "Other"):
        genre = ""
    return cat, genre


def fetch_ticketmaster():
    key = os.environ.get("TICKETMASTER_API_KEY")
    if not key:
        raise RuntimeError("TICKETMASTER_API_KEY absente")
    c = CONFIG["center"]
    gh = geohash(c["lat"], c["lng"], 7)
    events = []
    # Découpage par mois : l'API limite la pagination profonde (size*page < 1000).
    start = NOW.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    while start < HORIZON:
        end = min(start + dt.timedelta(days=31), HORIZON.astimezone(dt.timezone.utc))
        page = 0
        while True:
            q = {
                "apikey": key, "geoPoint": gh, "radius": c["radiusKm"], "unit": "km",
                "countryCode": "FR", "locale": "*", "size": 200, "page": page, "sort": "date,asc",
                "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            data = get_json("https://app.ticketmaster.com/discovery/v2/events.json?" + urllib.parse.urlencode(q))
            for e in (data.get("_embedded") or {}).get("events", []):
                d = e.get("dates", {}).get("start", {})
                st = parse_dt(d.get("dateTime"), dt.timezone.utc) if d.get("dateTime") else \
                    parse_dt(d.get("localDate") + ("T" + d["localTime"] if d.get("localTime") else ""))
                ven = ((e.get("_embedded") or {}).get("venues") or [{}])[0]
                cat, genre = tm_category((e.get("classifications") or [{}])[0])
                imgs = sorted(e.get("images") or [], key=lambda i: (i.get("ratio") != "16_9", -(i.get("width") or 0)))
                img = next((i["url"] for i in imgs if (i.get("width") or 0) <= 1100), imgs[0]["url"] if imgs else "")
                pr = (e.get("priceRanges") or [{}])[0]
                loc = ven.get("location") or {}
                ev = make_event(
                    title=e.get("name"), start=st, source="Ticketmaster", category=cat, genre=genre,
                    venue_name=ven.get("name", ""), city=(ven.get("city") or {}).get("name", ""),
                    address=(ven.get("address") or {}).get("line1", ""),
                    lat=float(loc["latitude"]) if loc.get("latitude") else None,
                    lng=float(loc["longitude"]) if loc.get("longitude") else None,
                    ticket_url=e.get("url", ""), vendor="Ticketmaster", image=img,
                    price_min=pr.get("min"), price_max=pr.get("max"), currency=pr.get("currency", "EUR"),
                    status={"cancelled": "Annulé", "postponed": "Reporté", "rescheduled": "Reprogrammé",
                            "offsale": "Plus en vente"}.get(e.get("dates", {}).get("status", {}).get("code", ""), ""),
                    has_time=not d.get("timeTBA") and not d.get("noSpecificTime") and bool(d.get("localTime") or d.get("dateTime")),
                )
                if ev:
                    events.append(ev)
            pg = data.get("page", {})
            page += 1
            time.sleep(0.25)  # limite : 5 requêtes / seconde
            if page >= pg.get("totalPages", 0) or page * 200 >= 1000:
                break
        start = end
    return events


# -------------------------------------------------------------- football-data.org
def fetch_football_data():
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise RuntimeError("FOOTBALL_DATA_API_KEY absente")
    events = []
    for t in CONFIG["teams"]:
        if not t.get("footballDataId"):
            continue
        url = f"https://api.football-data.org/v4/teams/{t['footballDataId']}/matches?status=SCHEDULED,TIMED,POSTPONED"
        data = get_json(url, {"X-Auth-Token": key})
        for m in data.get("matches", []):
            if (m.get("homeTeam") or {}).get("id") != t["footballDataId"]:
                continue  # uniquement les matchs à domicile (donc à Lyon)
            st = parse_dt(m.get("utcDate"), dt.timezone.utc)
            home = m["homeTeam"].get("shortName") or m["homeTeam"].get("name")
            away = (m.get("awayTeam") or {}).get("shortName") or (m.get("awayTeam") or {}).get("name") or "à déterminer"
            ev = make_event(
                title=f"{home} – {away}", start=st, source="football-data.org", category=t["sport"],
                competition=(m.get("competition") or {}).get("name", ""), venue_id=t["venueId"],
                ticket_url=t["ticketUrl"], vendor=vendor_from_url(t["ticketUrl"]),
                image=(m.get("awayTeam") or {}).get("crest", ""),
                status="Reporté" if m.get("status") == "POSTPONED" else "",
            )
            if ev:
                events.append(ev)
    return events


# --------------------------------------------------------------------- TheSportsDB
def fetch_sportsdb():
    base = "https://www.thesportsdb.com/api/v1/json/" + os.environ.get("THESPORTSDB_KEY", "123")
    events = []
    for t in CONFIG["teams"]:
        if not t.get("sportsDbSearch"):
            continue
        teams = get_json(f"{base}/searchteams.php?t=" + urllib.parse.quote(t["sportsDbSearch"])).get("teams") or []
        teams = [x for x in teams if x.get("strSport") == t["sportsDbSport"] and x.get("strCountry") == "France"]
        if not teams:
            log(f"  TheSportsDB : équipe introuvable pour {t['name']}")
            continue
        tid = teams[0]["idTeam"]
        time.sleep(1)
        for m in get_json(f"{base}/eventsnext.php?id={tid}").get("events") or []:
            if m.get("idHomeTeam") != tid:
                continue
            ts = m.get("strTimestamp") or (m.get("dateEvent", "") + "T" + (m.get("strTime") or "00:00:00"))
            st = parse_dt(ts, dt.timezone.utc)
            title = f"{m.get('strHomeTeam')} – {m.get('strAwayTeam')}" if m.get("strAwayTeam") else m.get("strEvent")
            ev = make_event(
                title=title, start=st, source="TheSportsDB", category=t["sport"],
                competition=m.get("strLeague", ""), venue_id=t["venueId"],
                ticket_url=t["ticketUrl"], vendor=vendor_from_url(t["ticketUrl"]),
                image=m.get("strThumb") or "", has_time=bool(m.get("strTime")) and m.get("strTime") != "00:00:00",
            )
            if ev:
                events.append(ev)
        time.sleep(1)
    return events


# ---------------------------------------------------------------------- OpenAgenda
def fetch_openagenda():
    key = os.environ.get("OPENAGENDA_API_KEY")
    agendas = CONFIG.get("openAgendaAgendas") or []
    if not key or not agendas:
        raise RuntimeError("OPENAGENDA_API_KEY ou liste d'agendas absente")
    events = []
    for a in agendas:
        uid = a["uid"] if isinstance(a, dict) else a
        after = None
        for _ in range(20):
            q = [("key", key), ("size", "300"), ("relative[]", "current"), ("relative[]", "upcoming"),
                 ("detailed", "1"), ("monolingual", "fr"), ("adminLevel2[]", "Rhône")]
            for x in after or []:
                q.append(("after[]", str(x)))
            data = get_json(f"https://api.openagenda.com/v2/agendas/{uid}/events?" + urllib.parse.urlencode(q))
            for e in data.get("events", []):
                loc = e.get("location") or {}
                reg = [r.get("value") for r in e.get("registration") or [] if r.get("type") == "link"]
                img = e.get("image") or {}
                img_url = (img.get("base", "") + img.get("filename", "")) if img else ""
                kws = " ".join(e.get("keywords") or []) if isinstance(e.get("keywords"), list) else ""
                k = norm(kws + " " + (e.get("title") or ""))
                cat = "concert" if "concert" in k or "musique" in k else "spectacle" if any(w in k for w in ("theatre", "spectacle", "danse", "humour")) else "autre"
                for tm in (e.get("timings") or [])[:30]:
                    ev = make_event(
                        title=e.get("title"), start=parse_dt(tm.get("begin")), end=parse_dt(tm.get("end")),
                        source="OpenAgenda", category=cat, venue_name=loc.get("name", ""),
                        city=loc.get("city", ""), address=loc.get("address", ""),
                        lat=loc.get("latitude"), lng=loc.get("longitude"),
                        ticket_url=(reg[0] if reg else e.get("canonicalUrl") or ""),
                        vendor=vendor_from_url(reg[0]) if reg else "OpenAgenda", image=img_url,
                        description=e.get("description") or "",
                    )
                    if ev:
                        events.append(ev)
            after = data.get("after")
            if not after:
                break
            time.sleep(0.5)
    return events


# ------------------------------------------------------- JSON-LD (schema.org Event)
EVENT_TYPES = {"Event", "MusicEvent", "SportsEvent", "TheaterEvent", "ComedyEvent", "DanceEvent",
               "Festival", "SocialEvent", "ScreeningEvent", "EducationEvent"}
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def allowed_by_robots(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(http_get(base + "/robots.txt", timeout=15).decode("utf-8", "ignore").splitlines())
        except urllib.error.HTTPError as e:
            rp.parse([] if e.code in (404, 410) else ["User-agent: *", "Disallow: /"])
        except Exception:
            rp.parse(["User-agent: *", "Disallow: /"])
        _robots[base] = rp
    return _robots[base].can_fetch(UA, url)


def walk_jsonld(node):
    if isinstance(node, list):
        for n in node:
            yield from walk_jsonld(n)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = set(t if isinstance(t, list) else [t])
        if types & EVENT_TYPES:
            yield node
        for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if k in node:
                yield from walk_jsonld(node[k])


def first(x):
    return x[0] if isinstance(x, list) and x else x


def fetch_jsonld():
    events = []
    for page in CONFIG.get("jsonLdPages", []):
        url = page["url"]
        try:
            if not allowed_by_robots(url):
                log(f"  robots.txt interdit {url}, page ignorée")
                continue
            body = http_get(url, {"Accept": "text/html"}).decode("utf-8", "ignore")
        except Exception as e:
            log(f"  {url} : {e}")
            continue
        blocks = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', body, re.S | re.I)
        n = 0
        for b in blocks:
            try:
                data = json.loads(b.strip())
            except json.JSONDecodeError:
                continue
            for e in walk_jsonld(data):
                loc = first(e.get("location")) or {}
                loc = loc if isinstance(loc, dict) else {"name": str(loc)}
                addr = loc.get("address") or {}
                addr = addr if isinstance(addr, dict) else {"streetAddress": str(addr)}
                off = first(e.get("offers")) or {}
                off = off if isinstance(off, dict) else {}
                t_url = off.get("url") or e.get("url") or url
                t = e.get("@type")
                t = t[0] if isinstance(t, list) else t
                cat = {"MusicEvent": "concert", "TheaterEvent": "spectacle", "ComedyEvent": "spectacle",
                       "DanceEvent": "spectacle", "SportsEvent": "sport", "Festival": "concert"}.get(t, "concert")
                sd = e.get("startDate") or ""
                img = first(e.get("image"))
                img = img.get("url") if isinstance(img, dict) else img
                geo = loc.get("geo") if isinstance(loc.get("geo"), dict) else {}
                if too_far(geo.get("latitude"), geo.get("longitude")):
                    continue  # agendas « région lyonnaise » qui incluent Valence, Grenoble…
                vid = match_venue(loc.get("name", ""), addr.get("addressLocality", "")) or page.get("venueId")
                name = e.get("name") or ""
                if loc.get("name") and name.lower().endswith(" @ " + loc["name"].lower()):
                    name = name[: -len(loc["name"]) - 3]  # Songkick : « Artiste @ Salle »
                price = off.get("price") or off.get("lowPrice")
                try:
                    price = float(str(price).replace(",", ".")) if price not in (None, "") else None
                except ValueError:
                    price = None
                ev = make_event(
                    title=name, start=parse_dt(sd), end=parse_dt(e.get("endDate")),
                    source=page.get("source") or urllib.parse.urlparse(url).netloc.replace("www.", ""),
                    category=page.get("category") or cat,
                    lat=geo.get("latitude"), lng=geo.get("longitude"),
                    venue_name=loc.get("name", ""), venue_id=vid,
                    city=addr.get("addressLocality", ""), address=addr.get("streetAddress", ""),
                    ticket_url=urllib.parse.urljoin(url, t_url), vendor=vendor_from_url(urllib.parse.urljoin(url, t_url)),
                    image=urllib.parse.urljoin(url, img) if isinstance(img, str) and img else "",
                    price_min=price, currency=off.get("priceCurrency") or "EUR",
                    has_time="T" in sd, description=re.sub("<[^>]+>", " ", e.get("description") or ""),
                    status="Annulé" if "Cancelled" in str(e.get("eventStatus", "")) else
                           "Reporté" if "Postponed" in str(e.get("eventStatus", "")) else "",
                )
                if ev:
                    events.append(ev)
                    n += 1
        log(f"  {url} : {n} événements")
        time.sleep(2)
    return events


# ------------------------------------------------- Calendriers de championnat (fixturedownload)
def fetch_fixtures():
    """Saison complète des matchs à domicile (flux JSON publics de fixturedownload.com, sans clé)."""
    events = []
    year = NOW.year if NOW.month >= 7 else NOW.year - 1
    for t in CONFIG["teams"]:
        feed, home = t.get("fixtureFeed"), t.get("fixtureName")
        if not feed or not home:
            continue
        for y in (year, year + 1):
            try:
                matches = get_json(f"https://fixturedownload.com/feed/json/{feed}-{y}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue  # saison pas encore publiée
                raise
            for m in matches:
                if m.get("HomeTeam") != home:
                    continue
                away = m.get("AwayTeam") or "à déterminer"
                st = parse_dt(m.get("DateUtc"), dt.timezone.utc)
                ev = make_event(
                    title=f"{t.get('shortName', home)} – {away}", start=st,
                    has_time=bool(st) and (st.hour, st.minute) != (0, 0),  # minuit = horaire pas encore fixé
                    source="Calendrier officiel", category=t["sport"], competition=t.get("competition", ""),
                    venue_id=t["venueId"], ticket_url=t["ticketUrl"], vendor=vendor_from_url(t["ticketUrl"]),
                )
                if ev:
                    events.append(ev)
            time.sleep(1)
    return events


# ------------------------------------------- OpenAgenda, copie publique (OpenDataSoft, sans clé)
ODS_URL = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records"
# Événements publics qui ne sont pas des sorties : on les écarte.
OA_SKIP = re.compile(r"\b(emploi|recrut\w*|job ?dating|conseil municipal|permanence|reunion publique|"
                     r"semaine de l industrie|portes? ouvertes?|formation|webinaire|collecte de sang|don du sang|"
                     r"enquete publique|concertation|france travail|salon de l emploi|celibataires?|speed dating)\b")
OA_CATS = [  # (catégorie, genre affiché, mots-clés)
    ("concert", "", r"\b(concert|musique|musical|live|jazz|rock|rap|electro|dj|chorale|orchestre|recital|opera)\b"),
    ("spectacle", "Humour", r"\b(humour|humoriste|stand ?up|one (wo)?man show|comique)\b"),
    ("spectacle", "Cirque", r"\b(cirque|acrobat\w*|jongl\w*)\b"),
    ("spectacle", "Danse", r"\b(danse|ballet|choregraph\w*)\b"),
    ("autre", "Exposition", r"\b(exposition|expo|vernissage|musee|galerie)\b"),
    ("spectacle", "Jeune public", r"\b(jeune public|marionnettes?|contes?|conteuse?)\b"),
    ("spectacle", "Théâtre", r"\b(theatre|spectacle|piece|impro\w*)\b"),
    ("sport", "", r"\b(sport\w*|match|course a pied|trail|marathon|tournoi|running|velo)\b"),
    ("autre", "Cinéma", r"\b(cinema|projection|film|documentaire|court metrage)\b"),
    ("autre", "Festival", r"\b(festival|fete|carnaval)\b"),
    ("autre", "Visite", r"\b(visite|balade|patrimoine)\b"),
    ("autre", "Conférence", r"\b(conference|rencontre|debat|lecture|dedicace)\b"),
    ("autre", "Atelier", r"\b(atelier|stage|initiation)\b"),
]


def oa_category(text: str) -> tuple[str, str]:
    for cat, genre, rx in OA_CATS:
        if re.search(rx, text):
            return cat, genre
    return "autre", ""


def fetch_openagenda_public():
    c = CONFIG["center"]
    where = (f"within_distance(location_coordinates, geom'POINT({c['lng']} {c['lat']})', {c['radiusKm']}km)"
             " AND lastdate_end >= now()")
    events, offset, per = [], 0, 100
    while offset < 5000:
        q = {"where": where, "order_by": "firstdate_begin", "limit": per, "offset": offset,
             "select": "uid,title_fr,description_fr,keywords_fr,image,canonicalurl,registration,timings,"
                       "location_name,location_address,location_city,location_coordinates,status,originagenda_title"}
        data = get_json(ODS_URL + "?" + urllib.parse.urlencode(q))
        rows = data.get("results") or []
        for r in rows:
            title = r.get("title_fr") or ""
            kws = r.get("keywords_fr") or ""
            kws = " ".join(kws) if isinstance(kws, list) else str(kws)
            text = norm(" ".join([title, kws, r.get("description_fr") or "", r.get("originagenda_title") or ""]))
            if OA_SKIP.search(text):
                continue
            status = r.get("status") or {}
            if isinstance(status, str):
                try:
                    status = json.loads(status)
                except ValueError:
                    status = {}
            # Statuts OpenAgenda : 1 programmé, 2 reprogrammé, 3 en ligne, 4 reporté, 5 complet, 6 annulé.
            sid = status.get("id") if isinstance(status, dict) else None
            cat, genre = oa_category(text)
            reg = r.get("registration") or []
            if isinstance(reg, str):
                try:
                    reg = json.loads(reg)
                except ValueError:
                    reg = []
            links = [x.get("value") for x in reg if isinstance(x, dict) and x.get("type") == "link"]
            url = links[0] if links else r.get("canonicalurl") or ""
            timings = r.get("timings") or []
            if isinstance(timings, str):
                try:
                    timings = json.loads(timings)
                except ValueError:
                    timings = []
            geo = r.get("location_coordinates") or {}
            # Les expositions ont une date par jour d'ouverture : on ne garde que les 3 prochaines.
            upcoming = [t for t in timings if (parse_dt(t.get("begin")) or NOW) >= NOW - dt.timedelta(hours=6)][:3]
            for t in upcoming:
                ev = make_event(
                    title=title, start=parse_dt(t.get("begin")), end=parse_dt(t.get("end")),
                    source="OpenAgenda", category=cat, genre=genre,
                    venue_name=r.get("location_name") or "", city=r.get("location_city") or "",
                    address=r.get("location_address") or "", lat=geo.get("lat"), lng=geo.get("lon"),
                    ticket_url=url, vendor=vendor_from_url(url), image=r.get("image") or "",
                    description=r.get("description_fr") or "",
                    status={2: "Reprogrammé", 4: "Reporté", 5: "Complet", 6: "Annulé"}.get(sid, ""),
                )
                if ev:
                    events.append(ev)
        if len(rows) < per:
            break
        offset += per
        time.sleep(0.5)
    return events


# ------------------------------------------------------------------- Instagram
# Lecture des posts publics de comptes qui annoncent des événements (config « instagramAccounts »),
# via l'API officielle Instagram Graph « Business Discovery » : il faut un compte Instagram
# professionnel relié à une app Meta, et deux secrets IG_ACCESS_TOKEN / IG_USER_ID.
# Les posts déjà lus sont gardés dans data/instagram.json : un post de la semaine dernière qui
# annonce un concert dans un mois reste affiché même s'il ne fait plus partie des derniers posts.
IG_CACHE = ROOT / "data" / "instagram.json"
GRAPH = "https://graph.facebook.com/v21.0"
MONTHS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5,
          "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "sep": 9, "octobre": 10,
          "oct": 10, "novembre": 11, "nov": 11, "decembre": 12, "dec": 12}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
RX_DATE_TXT = re.compile(r"\b(\d{1,2})(?:er)?\s+(" + _MONTH_RX + r")\.?(?:\s+(20\d\d))?\b")
RX_DATE_NUM = re.compile(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](20\d\d|\d\d))?\b")
RX_TIME = re.compile(r"\b([01]?\d|2[0-3])\s?h\s?([0-5]\d)?\b")
RX_PIN = re.compile(r"(?:📍|📌|🏠|lieu\s*:)\s*([^\n#]+)", re.I)


def _date_from(day: int, month: int, year: int | None, posted: dt.datetime) -> dt.date | None:
    """Sans année, on prend la première date à venir après la publication du post."""
    try:
        if year:
            return dt.date(year if year > 100 else 2000 + year, month, day)
        d = dt.date(posted.year, month, day)
        return d if d >= posted.date() - dt.timedelta(days=1) else dt.date(posted.year + 1, month, day)
    except ValueError:
        return None


def parse_caption(caption: str, posted: dt.datetime) -> list[dict]:
    """Découpe une légende en annonces : chaque bloc qui contient une date devient un événement.

    Un post « Les sorties du week-end » qui liste cinq concerts donne donc cinq événements.
    """
    text = caption or ""
    blocks = [b for b in re.split(r"\n\s*\n|\n(?=\s*(?:[-•▪️➡️👉🔸🔹⭐✨🎤🎶🎭🎨🎬⚽🏉🏀]|\d+[.)]\s))", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [text]
    found = []
    header = ""  # bloc sans date qui précède (« 🔥 ORELSAN débarque à Lyon ! ») : sert de titre au bloc daté suivant
    for b in blocks:
        n = norm(b)
        dates = [(int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)) if m.group(3) else None) for m in RX_DATE_TXT.finditer(n)]
        if not dates:
            dates = [(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None)
                     for m in RX_DATE_NUM.finditer(b) if 1 <= int(m.group(2)) <= 12]
        title_lines = [_clean_line(l) for l in b.splitlines() if not _is_info_line(l)]
        title_lines = [l for l in title_lines if len(l) > 2]
        if not dates:
            header = title_lines[0] if title_lines else header
            continue
        day = _date_from(*dates[0], posted)
        if not day:
            continue
        tm = RX_TIME.search(n)
        pin = RX_PIN.search(b)
        title = title_lines[0] if title_lines else header
        venue = pin.group(1).strip(" -–—:.,") if pin else ""
        if not venue:  # lieu connu cité dans le texte : « … au Transbordeur »
            for v in CONFIG["venues"]:
                if any(f" {norm(a)} " in f" {n} " for a in [v["name"], *v.get("aliases", [])]):
                    venue = v["name"]
                    break
        if not venue:  # « au Musée des Confluences », « à la Sucrière », « chez Mama Shelter »
            m = RX_AT.search(b)
            venue = m.group(1).strip() if m else ""
        if title and venue and norm(title).endswith(norm(venue)):  # « Expo X au Musée Y » -> « Expo X »
            title = re.sub(r"\s+(?:au|à la|à l['’]|aux|chez)\s+" + re.escape(venue) + r"\s*$", "", title, flags=re.I) or title
        found.append({"title": title[:120], "date": day.isoformat(),
                      "time": f"{int(tm.group(1)):02d}:{tm.group(2) or '00'}" if tm else None,
                      "venue": venue[:80], "text": (header + "\n" + b.strip())[:400]})
        header = ""
    return found


_CAP = r"[A-ZÉÈÀÂÎ][\w'’-]*"
RX_AT = re.compile(r"\b(?:au|à la|à l['’]|aux|chez)[ \t]+(" + _CAP + r"(?:[ \t]+(?:(?:de|des|du|la|le)[ \t]+|[ld]['’])?" + _CAP + r")*)")


def _is_info_line(line: str) -> bool:
    """Ligne de date, d'heure ou de lieu : pas un titre."""
    n = norm(line)
    return bool(RX_PIN.search(line) or RX_DATE_TXT.search(n) or RX_DATE_NUM.search(line)
                or re.fullmatch(r"\W*(?:\d{1,2}\s?h\s?\d{0,2}|a partir de .*)\W*", n or "x"))


def _clean_line(line: str) -> str:
    """Retire emojis, hashtags et mentions d'une ligne de légende."""
    return re.sub(r"\s+", " ", re.sub(r"[#@]\w[\w.]*|[^\w\s'’&:!?,.()«»\"/-]", "", line)).strip(" -–—:•|")


def fetch_instagram_posts() -> list[dict]:
    token, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    accounts = CONFIG.get("instagramAccounts") or []
    if not accounts:
        raise RuntimeError("aucun compte dans instagramAccounts")
    if not token or not uid:
        raise RuntimeError("IG_ACCESS_TOKEN ou IG_USER_ID absente")
    posts = []
    for acc in accounts:
        fields = (f"business_discovery.username({acc}){{username,media.limit(50)"
                  "{id,caption,timestamp,permalink,media_type,media_url,thumbnail_url}}")
        data = get_json(f"{GRAPH}/{uid}?" + urllib.parse.urlencode({"fields": fields, "access_token": token}))
        for m in ((data.get("business_discovery") or {}).get("media") or {}).get("data", []):
            m["account"] = acc
            posts.append(m)
        time.sleep(1)
    return posts


def instagram_events() -> list[dict]:
    """Met à jour le cache avec les posts du jour et renvoie toutes les annonces encore à venir."""
    cache = json.loads(IG_CACHE.read_text(encoding="utf-8")) if IG_CACHE.exists() else {"posts": {}}
    for p in fetch_instagram_posts():
        posted = parse_dt(p.get("timestamp"), dt.timezone.utc) or NOW
        cache["posts"][p["id"]] = {
            "account": p["account"], "permalink": p.get("permalink", ""), "posted": posted.isoformat(),
            "image": p.get("thumbnail_url") if p.get("media_type") == "VIDEO" else p.get("media_url", ""),
            "announces": parse_caption(p.get("caption", ""), posted),
        }
    # On oublie les posts dont toutes les annonces sont passées.
    today = NOW.date().isoformat()
    cache["posts"] = {k: v for k, v in cache["posts"].items() if any(a["date"] >= today for a in v["announces"])}
    IG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    IG_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    out = []
    for p in cache["posts"].values():
        for a in p["announces"]:
            out.append({**a, "account": p["account"], "permalink": p["permalink"], "image": p.get("image", "")})
    return out


TITLE_STOP = {"de", "du", "des", "la", "le", "les", "et", "a", "au", "aux", "en", "un", "une", "the", "concert",
              "spectacle", "lyon", "live", "tour", "tournee", "soiree", "presente", "avec", "feat", "x", "vs"}


def _tokens(s: str) -> set[str]:
    return {w for w in norm(s).split() if len(w) > 1 and w not in TITLE_STOP}


def correlate(announce: dict, events_by_date: dict[str, list[dict]]) -> tuple[dict | None, float]:
    """Cherche l'événement déjà présent qui correspond à une annonce Instagram.

    Score : mots du titre en commun (le plus important), même lieu, même heure.
    On regarde le jour annoncé et la veille / le lendemain (date mal recopiée, fin de soirée après minuit).
    """
    a_tok = _tokens(announce["title"]) | _tokens(announce.get("text", "")[:200])
    a_vid = match_venue(announce.get("venue", ""))
    d = dt.date.fromisoformat(announce["date"])
    best, best_score = None, 0.0
    for delta in (0, -1, 1):
        for e in events_by_date.get((d + dt.timedelta(days=delta)).isoformat(), []):
            e_tok = _tokens(e["title"])
            if not e_tok:
                continue
            common = len(e_tok & a_tok) / len(e_tok)  # part du titre existant retrouvée dans l'annonce
            same_venue = bool(a_vid and a_vid == e.get("venueId")) or \
                bool(announce.get("venue") and _tokens(announce["venue"]) & _tokens(e["venue"]))
            score = common + (0.35 if same_venue else 0) + (0.1 if announce.get("time") and announce["time"] == e.get("time") else 0)
            score -= 0.15 * abs(delta)
            if score > best_score:
                best, best_score = e, score
    return (best, best_score) if best_score >= 0.6 else (None, best_score)


def merge_instagram(events: list[dict]) -> int:
    """Rattache chaque annonce Instagram à l'événement existant correspondant, sinon l'ajoute.

    Renvoie le nombre d'événements créés. Lève une exception si la source n'est pas disponible.
    """
    by_date: dict[str, list[dict]] = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e)
    linked = created = 0
    for a in instagram_events():
        match, _ = correlate(a, by_date)
        seen = {"account": a["account"], "url": a["permalink"]}
        if match:
            if seen not in match.setdefault("seenOn", []):
                match["seenOn"].append(seen)
            linked += 1
            continue
        start = parse_dt(a["date"] + ("T" + a["time"] if a.get("time") else ""))
        cat, genre = oa_category(norm(a["title"] + " " + a.get("text", "")))
        ev = make_event(title=a["title"] or "Événement", start=start, source="Instagram", category=cat, genre=genre,
                        venue_name=a.get("venue", ""), ticket_url=a["permalink"], vendor=f"Instagram @{a['account']}",
                        image=a.get("image", ""), has_time=bool(a.get("time")), description=a.get("text", ""))
        if ev:
            ev["seenOn"] = [seen]
            events.append(ev)
            by_date.setdefault(ev["date"], []).append(ev)  # deux posts sur le même événement = un seul
            created += 1
    log(f"  Instagram : {linked} annonces rattachées à un événement existant, {created} nouveaux événements")
    return created


# ------------------------------------------------------------------- Manuel
def fetch_manual():
    if not MANUAL.exists():
        return []
    events = []
    for m in json.loads(MANUAL.read_text(encoding="utf-8")).get("events", []):
        ev = make_event(
            title=m.get("title"), start=parse_dt(m.get("start")), source="Ajout manuel",
            category=m.get("category", "autre"), venue_id=m.get("venueId"), venue_name=m.get("venue", ""),
            city=m.get("city", ""), ticket_url=m.get("ticketUrl", ""),
            vendor=m.get("vendor") or vendor_from_url(m.get("ticketUrl", "")), image=m.get("image", ""),
            competition=m.get("competition", ""), genre=m.get("genre", ""), has_time="T" in m.get("start", ""),
        )
        if ev:
            events.append(ev)
    return events


# ------------------------------------------------------------------- main
SOURCES = [
    ("Ticketmaster", fetch_ticketmaster),
    ("Calendrier Ligue 1", fetch_fixtures),
    ("football-data.org", fetch_football_data),
    ("TheSportsDB", fetch_sportsdb),
    ("OpenAgenda (public)", fetch_openagenda_public),
    ("OpenAgenda (clé)", fetch_openagenda),
    ("Songkick et sites des salles", fetch_jsonld),
    ("Ajouts manuels", fetch_manual),
]
PRIORITY = {"Ticketmaster": 0, "football-data.org": 1, "Calendrier officiel": 1, "Ajout manuel": 2,
            "Songkick": 3, "OpenAgenda": 4, "TheSportsDB": 5}


def dedupe(events):
    """Fusionne les doublons (même titre approximatif, même jour, même lieu)."""
    out: dict[str, dict] = {}
    for e in sorted(events, key=lambda e: PRIORITY.get(e["source"], 3)):
        words = norm(e["title"]).split()
        key = f"{e['date']}|{e['venueId'] or norm(e['venue'])}|{' '.join(words[:3])}"
        if e["category"] in ("football", "rugby", "basket"):
            key = f"{e['date']}|{e['category']}|{e['venueId']}"
        if key in out:
            keep = out[key]
            for f in ("image", "priceMin", "priceMax", "genre", "competition", "description"):
                if not keep.get(f) and e.get(f):
                    keep[f] = e[f]
            if not keep.get("time") and e.get("time"):
                keep["time"], keep["start"] = e["time"], e["start"]
            if e["ticketUrl"] and e["ticketUrl"] != keep["ticketUrl"] and (e["vendor"] or e["source"]) != keep["vendor"]:
                keep.setdefault("altTickets", [])
                if all(a["url"] != e["ticketUrl"] for a in keep["altTickets"]):
                    keep["altTickets"].append({"url": e["ticketUrl"], "vendor": e["vendor"] or e["source"]})
        else:
            out[key] = e
    return list(out.values())


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = {e["id"]: e for e in json.loads(OUT.read_text(encoding="utf-8")).get("events", [])}
        except Exception:
            pass

    all_events = []
    for name, fn in SOURCES:
        log(f"→ {name}")
        try:
            evs = fn()
            report[name] = {"ok": True, "count": len(evs)}
            all_events.extend(evs)
            log(f"  {len(evs)} événements")
        except Exception as e:  # une source en panne ne bloque pas les autres
            report[name] = {"ok": False, "count": 0, "error": str(e)[:200]}
            log(f"  ignorée : {e}")

    events = dedupe(all_events)

    # Instagram en dernier : chaque annonce est comparée à tout ce que les autres sources ont trouvé.
    log("→ Instagram")
    try:
        before = len(events)
        merge_instagram(events)
        report["Instagram"] = {"ok": True, "count": sum(1 for e in events if e.get("seenOn")),
                               "new": len(events) - before}
    except Exception as e:
        report["Instagram"] = {"ok": False, "count": 0, "error": str(e)[:200]}
        log(f"  ignorée : {e}")

    today = NOW.date().isoformat()
    for e in events:
        e["firstSeen"] = previous.get(e["id"], {}).get("firstSeen", today)
    # Premier gros import : rien n'est « nouveau », sinon tout le site serait marqué Nouveau.
    fresh = [e for e in events if e["firstSeen"] == today and e["id"] not in previous]
    if len(previous) < 50 or len(fresh) > 0.5 * len(events):
        for e in fresh:
            e["firstSeen"] = ""
    events.sort(key=lambda e: (e["start"], e["title"]))

    # Si toutes les sources échouent, on garde les données de la veille plutôt qu'un site vide.
    if not events and previous:
        log("Aucune donnée récupérée : on conserve le fichier précédent.")
        return 1

    payload = {
        "generatedAt": NOW.isoformat(timespec="seconds"),
        "sources": report,
        "venues": CONFIG["venues"],
        "events": events,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"✓ {len(events)} événements écrits dans {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
