# SiteBuilder Pro — Jinja2 Edition

Un outil de prospection et de production de sites pour freelances au Maroc.

**Le principe :** vous entrez une ville, un quartier et un type de commerce. L'application
liste les commerces de la zone, vérifie lesquels n'ont **pas** de site web, puis génère
pour chacun **deux sites prêts à vendre** :

| Version | Contenu | Fichier |
| --- | --- | --- |
| **A — Vitrine** | infos, horaires, galerie, carte Google, contact, bouton d'appel | `1 fichier .html` |
| **B — E-commerce** | la vitrine + catalogue, panier et commande envoyée sur WhatsApp | `1 fichier .html` |

Aucun serveur, aucune base de données, aucun paiement en ligne : le commerçant reçoit
ses commandes directement sur son WhatsApp.

---

## 1. Installation

```bash
cd Web-Generator
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Lancement

```bash
streamlit run app.py
```

L'application s'ouvre sur `http://localhost:8501`.

## 3. Utilisation

1. **Barre latérale — source des données**
   * `🟢 Démonstration` : 15 commerces de Casablanca, aucune clé API (idéal pour tester).
   * `🔵 Google Places API` : collez votre clé API, prospectez n'importe quelle ville.
   * `🟠 OpenStreetMap` : gratuit et sans clé (Nominatim + Overpass), fiches moins complètes.
2. **Zone** : ville + quartier/rue (`Maârif`, `Gauthier`, `Anfa`, `Bourgogne`, `Oasis`...).
3. **Type de commerce** : restaurant, café, salon, boutique, pharmacie, boulangerie, salle de sport.
4. Cliquez sur **🔍 Rechercher les commerces**.
5. L'application vérifie chaque site web, puis affiche **uniquement les leads** avec un score
   de priorité (**A** = à démarcher en premier).
6. Onglet **🛠️ Générateur** : choisissez un lead, prévisualisez les deux versions dans
   l'application, téléchargez-les, ou enregistrez-les dans `output/`.
7. Bouton **⚡ Générer tous les sites** : prépare une archive ZIP avec un dossier par commerce
   (les deux versions + un fichier de rappel), plus l'export **CSV** des leads pour votre suivi.

### Obtenir une clé Google Places

1. [Google Cloud Console](https://console.cloud.google.com/) → nouveau projet.
2. Activez **Places API** → *Identifiants* → *Créer une clé API*.
3. C'est tout : l'application utilise Text Search puis Place Details, avec pagination douce
   (0,05 s entre deux appels).

Sans clé, tout le reste fonctionne : le mode démonstration et OpenStreetMap couvrent la prospection.

---

## 4. Structure du projet

```
Web-Generator/
├── app.py                    # Interface Streamlit (recherche, leads, générateur, export)
├── builder.py                # Moteur Jinja2 : config des gabarits, rendu, ZIP
├── finder.py                 # Recherche des commerces : démo / Google Places / OpenStreetMap
├── checker.py                # Détection des sites web + scoring des leads
├── requirements.txt
├── README.md
├── output/                   # Sites enregistrés depuis l'application (créé à la volée)
└── templates/
    ├── base.html             # Gabarit maître (design system, blocs, polices, CSS)
    ├── partials/
    │   ├── _header.html      # En-tête collant : logo, navigation, bouton d'appel
    │   ├── _footer.html      # Pied de page sombre : à propos, contact, horaires
    │   ├── _cart.html        # Panier flottant + tiroir + commande WhatsApp
    │   ├── _map.html         # Carte Google Maps intégrée + coordonnées
    │   ├── _gallery.html     # Galerie de 3 visuels
    │   └── _hours.html       # Tableau des horaires
    └── types/
        ├── restaurant.html   # rouge #E74C3C · Poppins · hero plein écran
        ├── cafe.html         # brun #6F4E37 · Playfair Display · hero en arche
        ├── salon.html        # violet #9B59B6 · Montserrat · hero dégradé + équipe
        ├── shop.html         # bleu #2E86C1 · Inter · grille 4 colonnes + filtres
        ├── pharmacy.html     # vert #27AE60 · Roboto · tableau produits + urgence
        ├── bakery.html       # orange #E67E22 · Lora · produits du four
        ├── gym.html          # ardoise #2C3E50 · Oswald · comparaison d'abonnements
        └── default.html      # #34495E · Inter · gabarit générique
```

---

## 5. Comment ça marche (technique)

### Détection du type de commerce
`builder.detect_template_type()` croise les `types` Google (`restaurant`, `beauty_salon`,
`pharmacy`...) avec le nom du commerce (accents normalisés), puis retourne la clé du gabarit.
L'ordre de résolution va du plus précis au plus général (une pharmacie n'est jamais prise
pour une boutique).

### Vérification des sites web — `checker.check_website_status()`
Un commerce est un **lead** si :

* sa fiche n'a aucun site web → *Aucun site web sur la fiche* ;
* son « site » est une page Facebook / Instagram / Linktree → *Page sociale uniquement* ;
* son site répond en erreur (`HTTP 404/500`) → *Site en erreur — à refaire* ;
* son domaine ne résout plus ou expire → *Domaine injoignable — site abandonné ?* ;
* la page est parquée ou « en construction » → *Site en construction ou domaine parqué*.

Les 20 à 40 fiches sont analysées en parallèle (`ThreadPoolExecutor`, 8 requêtes simultanées).

### Score de priorité
| Critère | Points |
| --- | --- |
| Sans site web | +35 |
| Il avait un site (mort, parqué, en erreur) | +5 |
| Note ≥ 4,5 / 4,0 / 3,5 | +20 / +14 / +8 |
| Avis ≥ 100 / 50 / 20 / 5 | +15 / +10 / +7 / +3 |
| Téléphone renseigné (et mobile → WhatsApp possible) | +15 (+5) |
| Type « vendeur » (restaurant, boutique, pharmacie...) | +10 |

`A` ≥ 80, `B` ≥ 60, `C` ≥ 40, sinon `D`.

### Rendu Jinja2
`builder.create_both_versions(business, template_name)` rend deux fois le même gabarit :
une fois avec `is_ecommerce=False`, une fois avec `True`. Dans les gabarits :

```jinja
{% if is_ecommerce %}
  <button class="btn btn--primary add-to-cart" data-name="{{ product.name }}" data-price="{{ product.price }}">Ajouter</button>
{% endif %}
```

Le panier de `partials/_cart.html` est en JavaScript pur : `let cart = []`, `addToCart()`,
`updateCartUI()`, `checkoutWhatsApp()`. Le panier est conservé dans `localStorage`, et le
message final (lignes d'articles + total) est envoyé sur `https://wa.me/<numéro>`.

L'auto-échappement est activé : échappez les données dynamiques les unes après les autres
n'est pas nécessaire, et les noms contenant une apostrophe (« Jus d'Orange ») sont transmis
au panier via des attributs `data-*` plutôt que par un script inline.

---

## 6. Personnalisation

**Ajouter un type de commerce** : ajoutez une entrée dans `TEMPLATES_CONFIG` (`builder.py`) —
couleur, police, mots-clés de détection, images, 6 produits — puis un fichier dans
`templates/types/` qui étend `base.html`. La détection le prendra en compte automatiquement.

**Changer les produits** : les catalogues vivent dans `TEMPLATES_CONFIG[...]["products"]`.
Chaque produit accepte `name`, `price`, `desc`, `image` et, selon le gabarit, `category`,
`old_price`, `tag`, `duration`, `stock`, `badge`, `features`.

**Changer les couleurs / polices** : modifiez `color` et `font` dans `TEMPLATES_CONFIG` **et**
le `{% set color %}` / `{% set font %}` en tête du fichier de type (les deux doivent rester
identiques : le `set` du gabarit est prioritaire au rendu).

**Brancher un vrai catalogue par commerce** : remplacez l'appel `get_products_for_template()`
dans `render_business_site()` par votre propre source (CSV du commerçant, base de données...).

---

## 7. Vendre les sites générés

* **Livraison du fichier** : un seul `.html` autonome — le commerçant peut l'ouvrir par
  double-clic. Pour le mettre en ligne : Netlify Drop, Vercel, GitHub Pages, ou l'hébergement
  de la boutique. Aucune dépendance à installer.
* **Nom de domaine** : `nom-du-commerce.ma` (registrar marocain) puis pointer les DNS.
* **Ordre de vente conseillé** : vitrine d'abord (500 – 1 500 DH), e-commerce en upsell
  (2 000 – 4 000 DH + maintenance mensuelle). Montrez les deux versions sur votre téléphone,
  avec le vrai nom, la vraie adresse et la vraie carte du commerce : l'effet est immédiat.
* **Traçabilité** : utilisez l'export CSV comme pipeline (appelé / pas intéressé / signé).

---

## 8. Notes et limites

* `source.unsplash.com` ayant été retiré par Unsplash, les visuels utilisent des URL
  `images.unsplash.com` directes ; l'ancienne syntaxe n'est conservée que comme repli dans
  `partials/_gallery.html`. Remplacez ces URL par les photos réelles du commerçant avant livraison.
* Les sites générés ne contiennent pas de formulaire de contact (pas de serveur) :
  le canal de conversion est le téléphone et WhatsApp.
* OpenStreetMap ne fournit pas toujours la note, le téléphone ou les horaires : les valeurs
  manquantes sont remplacées par des valeurs génériques dans `builder.enrich_business_data()`.
* Respectez les conditions d'utilisation de Google Places et la politique d'usage de Nominatim
  (une requête à la fois, en-tête `User-Agent` identifiable).
#   W e b - G e n e r a t o r  
 