# Lyon Events

Un site qui regroupe les matchs (OL, LOU Rugby, LDLC ASVEL), les concerts et les spectacles à Lyon et autour (Décines, Villeurbanne, Caluire), avec pour chaque événement : la date, l'heure, le lieu, un lien d'itinéraire, l'ajout à l'agenda et un bouton qui mène directement à la page de vente officielle.

Le site se met à jour tout seul chaque matin grâce à GitHub Actions et il est hébergé gratuitement sur GitHub Pages.

## D'où viennent les événements

| Source | Ce qu'elle apporte | Clé nécessaire |
|---|---|---|
| [Ticketmaster Discovery API](https://developer.ticketmaster.com) | Concerts et spectacles vendus sur Ticketmaster dans un rayon de 25 km (LDLC Arena, Halle Tony Garnier, Transbordeur, Radiant…) avec le lien d'achat | `TICKETMASTER_API_KEY` (gratuite) |
| [fixturedownload.com](https://fixturedownload.com) | Calendrier complet des matchs de l'OL à domicile en Ligue 1 | aucune |
| [OpenAgenda, copie publique](https://public.opendatasoft.com/explore/dataset/evenements-publics-openagenda/) | Agendas culturels publics à 25 km (concerts, expos, cinéma, jeune public, festivals…), sans les forums emploi et réunions | aucune |
| [Songkick](https://www.songkick.com/metro-areas/28889-france-lyon) | Concerts à Lyon, y compris les petites salles absentes de Ticketmaster (8 pages lues par jour, robots.txt respecté) | aucune |
| [football-data.org](https://www.football-data.org) | Matchs à domicile de l'OL, coupes d'Europe comprises | `FOOTBALL_DATA_API_KEY` (gratuite, facultative) |
| [TheSportsDB](https://www.thesportsdb.com) | Prochain match à domicile du LOU Rugby, de l'ASVEL et de l'OL | aucune |
| Pages agenda des salles | Les données structurées (schema.org) que certaines salles publient elles-mêmes, en respectant leur robots.txt | aucune |
| [OpenAgenda](https://openagenda.com) | Agendas culturels publics, si tu ajoutes leurs identifiants dans `config/sources.json` | `OPENAGENDA_API_KEY` (facultative) |
| Instagram ([API Graph officielle](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery)) | Posts publics des comptes de `instagramAccounts` (config) : chaque annonce datée est rapprochée des événements déjà trouvés (titre, lieu, heure, à un jour près). Si elle correspond, la carte affiche « Annoncé sur Instagram » ; sinon l'événement est ajouté. Les posts lus sont gardés dans `data/instagram.json`. | `IG_ACCESS_TOKEN` et `IG_USER_ID` |
| `data/manual.json` | Les événements que tu veux ajouter à la main | aucune |

Sources écartées (vérifié en novembre 2026) : Fnac Spectacles, OnlyLyon, Tribune de Lyon, AllEvents, Lyon Première et Le Bon Plan interdisent les robots dans leur robots.txt ; Petit Bulletin, Bandsintown, Infoconcert et Shotgun les bloquent ; Eventbrite contient surtout des cours et ateliers. Facebook et TikTok ne sont pas lus : leurs conditions d'utilisation interdisent la collecte automatique et leurs contenus demandent une connexion. Instagram n'est lu que par son API officielle (voir plus haut), jamais en aspirant les pages. Fnac Spectacles et See Tickets n'ont pas d'API publique, donc le script ne va pas lire leurs pages automatiquement. Leurs liens apparaissent quand une salle les publie elle-même, et ils restent accessibles en bas de page.

Une source en panne n'empêche pas les autres de fonctionner, et si tout échoue un jour, le site garde les données de la veille.

## Mise en route (une seule fois)

1. Pousse ce dossier dans un dépôt GitHub (branche `main`).
2. Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**, ajoute `TICKETMASTER_API_KEY` (et `FOOTBALL_DATA_API_KEY` si tu en as une).
3. **Settings → Pages → Source : GitHub Actions**.
4. **Actions → Mise à jour quotidienne des événements → Run workflow** pour la première mise à jour.

Le site est ensuite à l'adresse `https://<ton-pseudo>.github.io/<nom-du-depot>/`.

## Personnaliser

- Ajouter une salle ou une équipe : `config/sources.json`.
- Ajouter un événement à la main : `data/manual.json`, par exemple :
  ```json
  { "title": "Festival X", "start": "2027-06-12T18:00", "category": "concert",
    "venueId": "theatre-antique-fourviere", "ticketUrl": "https://..." }
  ```
- Changer l'heure de mise à jour : la ligne `cron` dans `.github/workflows/update.yml`.

## Lancer en local

```bash
TICKETMASTER_API_KEY=xxx python3 scripts/fetch_events.py
cd site && python3 -m http.server 8000   # puis ouvrir http://localhost:8000
```

Aucune dépendance à installer : Python 3.9+ suffit.
