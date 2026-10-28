# Journal des versions — SiteBuilder Pro

Toutes les versions notables de **SiteBuilder Pro — Jinja2 Edition**.
Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
[versionnage sémantique](https://semver.org/lang/fr/).

La version courante vit dans le fichier [`VERSION`](VERSION) ; elle est exposée par
[`version.py`](version.py) et affichée dans la barre latérale de l'application, dans les
archives ZIP exportées et dans le `<meta name="generator">` de chaque site généré.

---

## [Non publié]

### À venir

- Catalogue produits réel par commerce (lecture d'un CSV du commerçant).
- Téléchargement local des polices Google pour un rendu 100 % hors ligne.

---

## [1.1.0] — 2026-10-28

### Ajouté

- **26 thèmes Bootswatch téléchargés localement** dans `../assets/themes/` (un dossier par
  thème, `bootstrap.min.css` + `manifest.json`). Aucun appel à un CDN de thèmes.
- **`themes.py`** : téléchargement (`--download`, `--force`, `--destination`), analyse des
  variables CSS du thème (`--bs-primary`, `--bs-body-bg`, rayon, police, mode sombre),
  vérification (`--check`), recalcul du manifeste (`--reanalyze`) et tirage aléatoire stable
  par commerce (`pick_theme`, `resolve_theme`).
- **Thème aléatoire par site** : chaque commerce reçoit un thème tiré au sort, mais
  reproductible (graine = nom + adresse + `place_id`). La vitrine et l'e-commerce d'un même
  commerce partagent le même thème. Sélecteur dans la barre latérale : aléatoire, thème
  précis, ou `Aucun` (couleur et police du métier).
- **Jetons de lisibilité** : `--primary-text`, `--primary-soft-text`, `--primary-tint`,
  `--on-primary`, `--ok-text`, vérifiés à 4,5:1 (WCAG AA) sur toutes les surfaces utilisées
  par les gabarits — surface, bandeau alterné, fond doux, teinte colorée, survol de bouton.
- **`version.py` + fichier `VERSION`** : source unique de la version, exposée dans
  l'interface, les exports et les fichiers HTML générés.
- **`CHANGELOG.md`**, `.gitignore` et documentation du versionnage dans le README.

### Modifié

- `builder.render_business_site()` accepte un thème (`Theme`, nom de thème ou `"aucun"`) et
  embarque le CSS du thème directement dans le fichier HTML.
- Détection du gabarit affinée : `food` ne détourne plus une épicerie vers *restaurant*,
  `the` seul ne capture plus « The Burger House », `health`/`medical` ne classent plus une
  salle de sport en pharmacie ; les épiceries et supérettes rejoignent *shop*.
- `themes.resolve_theme()` reconnaît le libellé d'interface « ❌ Aucun (couleur du métier) »
  et plus seulement la valeur `"aucun"`.

### Corrigé

- Texte blanc sur bouton principal illisible sur les thèmes clairs (Minty, Lux, Yeti…) :
  `--on-primary` est désormais calculé par comparaison de contraste et non par seuil de
  luminance.
- Prix, liens et surtitres lisibles sur les thèmes sombres (Darkly, Cyborg, Vapor…).
- Voile des visuels de héros renforcé pour que les titres blancs restent lisibles sur photo.

---

## [1.0.0] — 2026-10-27

### Ajouté

- Application **Streamlit** de prospection : ville, quartier, type de commerce, filtres de
  qualité (note, nombre d'avis).
- **`finder.py`** : mode démonstration (15 commerces de Casablanca), Google Places
  (Text Search + Place Details, pagination douce) et OpenStreetMap (Nominatim + Overpass).
- **`checker.py`** : détection des sites web (présence, joignabilité, redirections) et score
  de priorité **A/B/C** pour trier les leads.
- **`builder.py`** : moteur Jinja2, détection automatique du gabarit, enrichissement des
  données du commerce, rendu vitrine + e-commerce, export ZIP.
- **8 gabarits métier** (`restaurant`, `cafe`, `salon`, `shop`, `pharmacy`, `bakery`, `gym`,
  `default`) étendant `base.html`, avec `partials/` (en-tête, pied de page, panier, carte,
  galerie, horaires).
- **Version vitrine** (1 fichier HTML) et **version e-commerce** (panier + commande
  WhatsApp) pour chaque lead, prévisualisables et téléchargeables depuis l'application.
- Export **CSV** des leads et archive ZIP de tous les sites générés.

---

[Non publié]: https://github.com/kouljihate/Web-Generator/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/kouljihate/Web-Generator/releases/tag/v1.1.0
[1.0.0]: https://github.com/kouljihate/Web-Generator/releases/tag/v1.0.0
