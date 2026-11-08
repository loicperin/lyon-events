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
        "title": html.unescape(title).strip(),
        "category": category,
        "genre": genre,
        "competition": competition,
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M") if has_time else None,
        "venueId": vid,
        "venue": v.get("name") or venue_name or "Lieu à confirmer",
        "city": v.get("city") or city,
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


def vendor_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    for key, label in [("ticketmaster", "Ticketmaster"), ("fnacspectacles", "Fnac Spectacles"),
                       ("francebillet", "France Billet"), ("seetickets", "See Tickets"),
                       ("digitick", "See Tickets"), ("shotgun", "Shotgun"), ("dice.fm", "DICE"),
                       ("weezevent", "Weezevent"), ("billetweb", "Billetweb"),
                       ("helloasso", "HelloAsso"), ("ol.fr", "Billetterie OL"),
                       ("lourugby", "Billetterie LOU"), ("eventbrite", "Eventbrite"),
                       ("ticketac", "Ticketac"), ("festik", "Festik")]:
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
                vid = match_venue(loc.get("name", ""), addr.get("addressLocality", "")) or page.get("venueId")
                price = off.get("price") or off.get("lowPrice")
                try:
                    price = float(str(price).replace(",", ".")) if price not in (None, "") else None
                except ValueError:
                    price = None
                ev = make_event(
                    title=e.get("name"), start=parse_dt(sd), end=parse_dt(e.get("endDate")),
                    source=urllib.parse.urlparse(url).netloc.replace("www.", ""), category=cat,
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
    ("football-data.org", fetch_football_data),
    ("TheSportsDB", fetch_sportsdb),
    ("OpenAgenda", fetch_openagenda),
    ("Sites des salles (JSON-LD)", fetch_jsonld),
    ("Ajouts manuels", fetch_manual),
]
PRIORITY = {"Ticketmaster": 0, "football-data.org": 1, "Ajout manuel": 2, "OpenAgenda": 4, "TheSportsDB": 5}


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
    today = NOW.date().isoformat()
    for e in events:
        e["firstSeen"] = previous.get(e["id"], {}).get("firstSeen", today if previous else "")
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
