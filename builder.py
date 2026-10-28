"""
builder.py
==========

Moteur de génération de sites web pour **SiteBuilder Pro — Jinja2 Edition**.

Le module expose :

* l'environnement Jinja2 construit sur le dossier ``templates/``,
* :data:`TEMPLATES_CONFIG` : la configuration de chaque gabarit métier
  (couleur, police, produits, mots-clés de détection, images, arguments de vente),
* :func:`detect_template_type` : détection automatique du type de commerce,
* :func:`get_products_for_template` : catalogue produits associé à un gabarit,
* :func:`enrich_business_data` : complétion des données du commerce,
* :func:`render_business_site` : rendu d'une version (vitrine ou e-commerce),
* :func:`create_both_versions` : rendu simultané des deux versions vendables,
* le **thème Bootswatch** (voir :mod:`themes`) est tiré au hasard pour chaque site
  et embarqué dans le fichier HTML généré,
* :func:`save_html_to_file` : écriture d'un fichier HTML,
* :func:`create_zip_of_sites` : archive ZIP en mémoire prête à télécharger.

Exemple d'utilisation :

    >>> from builder import create_both_versions
    >>> biz = {"name": "Tajine Express", "address": "Maarif, Casablanca", "types": ["restaurant"]}
    >>> static_html, ecommerce_html = create_both_versions(biz, "restaurant")
    >>> len(static_html) > 1000 and len(ecommerce_html) > 1000
    True
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import zipfile
from datetime import datetime
from io import BytesIO

from jinja2 import Environment, FileSystemLoader, select_autoescape

import themes as theme_library
from version import __version__ as GENERATOR_VERSION

LOGGER = logging.getLogger(__name__)

#: Dossier contenant les gabarits Jinja2 (``base.html``, ``partials/``, ``types/``).
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

#: Dossier de sortie par défaut pour :func:`save_html_to_file`.
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# --------------------------------------------------------------------------- #
# Environnement Jinja2
# --------------------------------------------------------------------------- #
env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

def _shade(hex_color: str, percent: float) -> str:
    """Éclaircit (``percent > 0``) ou assombrit (``percent < 0``) une couleur hexadécimale."""
    value = str(hex_color or "#34495E").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        red, green, blue = 52, 73, 94
    factor = 1 + percent / 100
    if percent > 0:
        red, green, blue = (round(ch + (255 - ch) * percent / 100) for ch in (red, green, blue))
    else:
        red, green, blue = (max(0, min(255, round(ch * factor))) for ch in (red, green, blue))
    return f"#{red:02x}{green:02x}{blue:02x}"


# Quelques filtres pratiques pour les gabarits.
env.filters["tel"] = lambda value: re.sub(r"[^\d+]", "", str(value or ""))
env.filters["wa"] = lambda value: re.sub(r"[^\d]", "", str(value or ""))
env.filters["darken"] = lambda color, percent=20: _shade(color, -abs(percent))
env.filters["lighten"] = lambda color, percent=90: _shade(color, abs(percent))


# --------------------------------------------------------------------------- #
# Images (URL directes Unsplash : source.unsplash.com est hors service)
# --------------------------------------------------------------------------- #
def _img(photo_id: str, width: int = 600) -> str:
    """Construit une URL d'image Unsplash directe et optimisée."""
    return (
        f"https://images.unsplash.com/{photo_id}"
        f"?w={width}&q=80&auto=format&fit=crop"
    )


# --------------------------------------------------------------------------- #
# Configuration des gabarits métier
# --------------------------------------------------------------------------- #
#: Couleurs, polices, produits et mots-clés de chaque gabarit.
#: ``keywords`` sert à la détection automatique du bon gabarit pour un commerce.
TEMPLATES_CONFIG: dict[str, dict] = {
    "restaurant": {
        "name": "Restaurant",
        "emoji": "🍽️",
        "label": "Restaurant / Snack / Grill",
        "color": "#E74C3C",
        "font": "Poppins",
        "file": "types/restaurant.html",
        "ecommerce_allowed": True,
        "keywords": [            # « food » est trop générique (une épicerie le porte aussi) et
            # détournait les commerces vers le gabarit restaurant.
            "restaurant", "meal", "meal_delivery", "meal_takeaway", "pizza",
            "tacos", "burger", "grill", "snack", "sandwicherie", "cuisine", "traiteur",
            "grillade", "poisson", "kebab", "resto",
        ],
        "tagline": "Une cuisine généreuse, préparée chaque jour avec des produits frais.",
        "about": (
            "Depuis notre ouverture, nous cuisinons des plats authentiques, "
            "servis dans une ambiance chaleureuse. Nos produits sont choisis "
            "chaque matin sur le marché et préparés à la commande."
        ),
        "hero_image": _img("photo-1517248135467-4c7edcad34c4", 1600),
        "gallery": [
            _img("photo-1513104890138-7c749659a591"),
            _img("photo-1541518763669-27fef04b14ea"),
            _img("photo-1585937421612-70a008356fbe"),
        ],
        "features": [
            {"icon": "🌿", "title": "Produits frais", "text": "Livrés chaque matin par nos producteurs locaux."},
            {"icon": "⚡", "title": "Service rapide", "text": "Votre commande prête en moins de 15 minutes."},
            {"icon": "🛵", "title": "Livraison", "text": "Livraison à domicile dans tout le quartier."},
        ],
        "products": [
            {"name": "Tajine Poulet", "price": 89, "desc": "Poulet, olives, citron", "image": _img("photo-1541518763669-27fef04b14ea", 400)},
            {"name": "Couscous Royal", "price": 120, "desc": "Vendredi spécial", "image": _img("photo-1585937421612-70a008356fbe", 400)},
            {"name": "Pizza Margherita", "price": 65, "desc": "Mozzarella, tomate", "image": _img("photo-1513104890138-7c749659a591", 400)},
            {"name": "Pastilla", "price": 95, "desc": "Poulet, amandes", "image": _img("photo-1565299624946-b28f40a0ae38", 400)},
            {"name": "Salade Marocaine", "price": 45, "desc": "Tomates, concombres", "image": _img("photo-1540189549336-e6e99c3679fe", 400)},
            {"name": "Jus d'Orange", "price": 25, "desc": "Pressé", "image": _img("photo-1621506289937-a8e4df240d0b", 400)},
        ],
    },
    "cafe": {
        "name": "Café",
        "emoji": "☕",
        "label": "Café / Salon de thé / Pâtisserie café",
        "color": "#6F4E37",
        "font": "Playfair Display",
        "file": "types/cafe.html",
        "ecommerce_allowed": True,
        # « the » nu attrapait « The Burger House » : on cible « salon de thé »,
        # « tea house » et les noms anglais en « tea ».
        "keywords": [
            "cafe", "coffee", "coffee_shop", "salon de the", "tea house", "tea",
            "patisserie cafe",
        ],
        "tagline": "Le meilleur endroit du quartier pour un café torréfié à la main.",
        "about": (
            "Un lieu cosy où l'on prend le temps. Nos grains sont torréfiés "
            "artisanalement, nos pâtisseries sont faites maison et notre thé à "
            "la menthe est servi à la marocaine."
        ),
        "hero_image": _img("photo-1509042239860-f550ce710b93", 1600),
        "gallery": [
            _img("photo-1554118811-1e0d58224f24"),
            _img("photo-1495474472287-4d71bcdd2085"),
            _img("photo-1461023058943-07fcbe16d735"),
        ],
        "features": [
            {"icon": "☕", "title": "Torréfaction maison", "text": "Grains sélectionnés et torréfiés chaque semaine."},
            {"icon": "🍰", "title": "Pâtisseries maison", "text": "Préparées sur place, sans conservateurs."},
            {"icon": "📶", "title": "Wi-Fi & travail", "text": "Coin calme, prises et Wi-Fi gratuit."},
        ],
        "products": [
            {"name": "Espresso", "price": 15, "desc": "Grains 100% arabica", "image": _img("photo-1510707577719-ae7c14805e3a", 400)},
            {"name": "Cappuccino", "price": 22, "desc": "Mousse de lait onctueuse", "image": _img("photo-1572442388796-11668a67e53d", 400)},
            {"name": "Café Latte", "price": 25, "desc": "Latte art maison", "image": _img("photo-1461023058943-07fcbe16d735", 400)},
            {"name": "Thé à la menthe", "price": 18, "desc": "Servi à la marocaine", "image": _img("photo-1544787219-7f47ccb76574", 400)},
            {"name": "Jus d'Avocat", "price": 25, "desc": "Avocat, lait, amandes", "image": _img("photo-1610970881699-44a5587cabec", 400)},
            {"name": "Pâtisserie du jour", "price": 20, "desc": "Faite maison", "image": _img("photo-1555507036-ab1f4038808a", 400)},
        ],
    },
    "salon": {
        "name": "Salon de beauté",
        "emoji": "💅",
        "label": "Salon / Coiffure / Spa / Esthétique",
        "color": "#9B59B6",
        "font": "Montserrat",
        "file": "types/salon.html",
        "ecommerce_allowed": True,
        "keywords": [
            "beauty_salon", "hair_care", "spa", "salon", "coiffure", "barbier",
            "beaute", "esthetique", "onglerie", "hammam", "massage",
        ],
        "tagline": "Sublimez votre style avec nos coiffeurs et esthéticiennes passionnés.",
        "about": (
            "Notre salon réunit une équipe passionnée et des produits "
            "professionnels pour prendre soin de vous. Sur rendez-vous ou en "
            "passant, nous vous accueillons dans un espace calme et climatisé."
        ),
        "hero_image": _img("photo-1560066984-138dadb4c035", 1600),
        "gallery": [
            _img("photo-1560066984-138dadb4c035"),
            _img("photo-1522337360788-8b13dee7a37e"),
            _img("photo-1503951914875-452162b0f3f1"),
        ],
        "features": [
            {"icon": "✂️", "title": "Coiffeurs experts", "text": "Une équipe formée aux tendances actuelles."},
            {"icon": "🧴", "title": "Produits pro", "text": "Marques professionnelles uniquement."},
            {"icon": "📅", "title": "Réservation facile", "text": "Réservez en un message WhatsApp."},
        ],
        "products": [
            {"name": "Coupe Homme", "price": 99, "duration": "30 min", "desc": "Coupe + finitions", "image": _img("photo-1503951914875-452162b0f3f1", 400)},
            {"name": "Coupe + Barbe", "price": 149, "duration": "45 min", "desc": "Taille de barbe à la tondeuse", "image": _img("photo-1622286342621-4bd786c2447c", 400)},
            {"name": "Brushing", "price": 120, "duration": "40 min", "desc": "Lavage + brushing", "image": _img("photo-1522337360788-8b13dee7a37e", 400)},
            {"name": "Coloration", "price": 350, "duration": "90 min", "desc": "Couleur + soin", "image": _img("photo-1560066984-138dadb4c035", 400)},
            {"name": "Manucure", "price": 150, "duration": "45 min", "desc": "Vernis semi-permanent inclus", "image": _img("photo-1604654894610-df63bc536371", 400)},
            {"name": "Soin du visage", "price": 250, "duration": "60 min", "desc": "Nettoyage + hydratation", "image": _img("photo-1570172619644-dfd03ed5d881", 400)},
        ],
    },
    "shop": {
        "name": "Boutique",
        "emoji": "🛍️",
        "label": "Boutique / Prêt-à-porter / Magasin",
        "color": "#2E86C1",
        "font": "Inter",
        "file": "types/shop.html",
        "ecommerce_allowed": True,
        "keywords": [            "clothing_store", "clothing", "boutique", "magasin", "shop", "store", "textile",
            "mode", "shoes", "shoe_store", "jewelry_store", "supermarket",
            "grocery_or_supermarket", "convenience_store", "electronics_store",
        ],
        "tagline": "Nouvelle collection disponible en boutique — essayez avant d'acheter.",
        "about": (
            "Des pièces sélectionnées avec soin, des matières de qualité et des "
            "prix justes. Notre équipe vous conseille pour trouver le style qui "
            "vous ressemble, en boutique ou via WhatsApp."
        ),
        "hero_image": _img("photo-1441986300917-64674bd600d8", 1600),
        "gallery": [
            _img("photo-1445205170230-053b83016050"),
            _img("photo-1523381210434-271e8be1f52b"),
            _img("photo-1490481651871-ab68de25d43d"),
        ],
        "features": [
            {"icon": "🚚", "title": "Livraison rapide", "text": "Livraison partout dans la ville."},
            {"icon": "💳", "title": "Paiement à la livraison", "text": "Payez en espèces à la réception."},
            {"icon": "🔄", "title": "Échange 7 jours", "text": "Taille non adaptée ? On échange."},
        ],
        "products": [
            {"name": "Chemise Oxford", "price": 249, "old_price": 320, "tag": "Promo", "category": "Homme", "desc": "Coton 100%", "image": _img("photo-1596755094514-f87e34085b2c", 400)},
            {"name": "Robe Été Fleurie", "price": 399, "old_price": 520, "tag": "Promo", "category": "Femme", "desc": "Fluide et légère", "image": _img("photo-1595777457583-95e059d581b8", 400)},
            {"name": "Pantalon Chino", "price": 279, "category": "Homme", "tag": "Nouveau", "desc": "Coupe slim", "image": _img("photo-1473966968600-fa801b869a1a", 400)},
            {"name": "Blouson en Jean", "price": 459, "category": "Femme", "tag": "Nouveau", "desc": "Denim robuste", "image": _img("photo-1544022613-e87ca75a784a", 400)},
            {"name": "Sac à main Cuir", "price": 549, "old_price": 690, "tag": "Promo", "category": "Accessoires", "desc": "Cuir véritable", "image": _img("photo-1584917865442-de89df76afd3", 400)},
            {"name": "Montre Classique", "price": 399, "category": "Accessoires", "tag": "Nouveau", "desc": "Bracelet acier", "image": _img("photo-1524805444758-089113d48a6d", 400)},
            {"name": "Sneakers Blanches", "price": 449, "old_price": 599, "tag": "Promo", "category": "Accessoires", "desc": "Semelle confort", "image": _img("photo-1549298916-b41d501d3772", 400)},
            {"name": "Ceinture Cuir", "price": 149, "category": "Homme", "tag": "Nouveau", "desc": "Boucle acier", "image": _img("photo-1624222247344-550fb60583dc", 400)},
        ],
    },
    "pharmacy": {
        "name": "Pharmacie",
        "emoji": "💊",
        "label": "Pharmacie / Parapharmacie",
        "color": "#27AE60",
        "font": "Roboto",
        "file": "types/pharmacy.html",
        "ecommerce_allowed": True,
        # « health » / « medical » sont trop génériques : une salle de sport
        # (types « gym, health ») était détectée comme pharmacie.
        "keywords": [
            "pharmacy", "drugstore", "pharmacie", "parapharmacie", "para pharmacie",
        ],
        "tagline": "Votre pharmacie de proximité : conseil, ordonnance et livraison.",
        "about": (
            "Une équipe de pharmaciens diplômés à votre écoute pour le conseil, "
            "la délivrance d'ordonnance et le suivi de vos traitements. "
            "Livraison à domicile dans tout le quartier."
        ),
        "hero_image": _img("photo-1587854692152-cbe660dbde88", 1600),
        "gallery": [
            _img("photo-1587854692152-cbe660dbde88"),
            _img("photo-1631549916768-4119b2e5f926"),
            _img("photo-1585435557343-3b092031a831"),
        ],
        "features": [
            {"icon": "📋", "title": "Ordonnance", "text": "Dépôt et retrait de votre ordonnance."},
            {"icon": "🛵", "title": "Livraison", "text": "À domicile, 7j/7 jusqu'à 22h."},
            {"icon": "👩‍⚕️", "title": "Conseil", "text": "Un pharmacien répond à vos questions."},
        ],
        "products": [
            {"name": "Paracétamol 500mg", "price": 25, "stock": "En stock", "desc": "Boîte de 20 comprimés", "image": _img("photo-1584308666744-24d5c474f2ae", 400)},
            {"name": "Vitamine C 1000mg", "price": 45, "stock": "En stock", "desc": "Comprimés effervescents", "image": _img("photo-1607619056574-7b8d3ee536b2", 400)},
            {"name": "Sirop pour la toux", "price": 60, "stock": "En stock", "desc": "Adulte et enfant +12 ans", "image": _img("photo-1631549916768-4119b2e5f926", 400)},
            {"name": "Pansements assortis", "price": 30, "stock": "En stock", "desc": "Boîte de 40 pièces", "image": _img("photo-1603398938378-e54eab446dde", 400)},
            {"name": "Thermomètre digital", "price": 89, "stock": "Sur commande", "desc": "Mesure en 10 secondes", "image": _img("photo-1584362917165-526a968579e8", 400)},
            {"name": "Crème solaire SPF 50", "price": 120, "stock": "Sur commande", "desc": "Protection visage et corps", "image": _img("photo-1556228720-195a672e8a03", 400)},
        ],
    },
    "bakery": {
        "name": "Boulangerie",
        "emoji": "🥖",
        "label": "Boulangerie / Pâtisserie",
        "color": "#E67E22",
        "font": "Lora",
        "file": "types/bakery.html",
        "ecommerce_allowed": True,
        "keywords": [
            "bakery", "boulangerie", "patisserie", "pastry", "bread", "viennoiserie",
            "gateau", "confiserie",
        ],
        "tagline": "Le pain et les viennoiseries sortent du four chaque matin.",
        "about": (
            "Farine de qualité, levain naturel et savoir-faire familial : nous "
            "pétrissons et cuisons sur place. Commandez vos gâteaux d'événement "
            "au moins 48h à l'avance."
        ),
        "hero_image": _img("photo-1509440159596-0249088772ff", 1600),
        "gallery": [
            _img("photo-1509440159596-0249088772ff"),
            _img("photo-1555507036-ab1f4038808a"),
            _img("photo-1486427944299-d1955d23e34d"),
        ],
        "features": [
            {"icon": "🌾", "title": "Levain naturel", "text": "Une fermentation lente et digeste."},
            {"icon": "👨‍🍳", "title": "Fait maison", "text": "Tout est préparé sur place."},
            {"icon": "🎂", "title": "Sur commande", "text": "Gâteaux d'anniversaire et plateaux."},
        ],
        "products": [
            {"name": "Baguette tradition", "price": 3, "badge": "Fait maison", "desc": "Cuite au four à sole", "image": _img("photo-1509440159596-0249088772ff", 400)},
            {"name": "Pain complet", "price": 5, "badge": "Fait maison", "desc": "Farine complète bio", "image": _img("photo-1608198093002-ad4e005484ec", 400)},
            {"name": "Croissant au beurre", "price": 8, "badge": "Fait maison", "desc": "Beurre fin", "image": _img("photo-1555507036-ab1f4038808a", 400)},
            {"name": "Pain au chocolat", "price": 9, "badge": "Fait maison", "desc": "Chocolat noir", "image": _img("photo-1486427944299-d1955d23e34d", 400)},
            {"name": "Msemen", "price": 4, "badge": "Fait maison", "desc": "Feuilleté à la marocaine", "image": _img("photo-1568051243851-f9b136146e97", 400)},
            {"name": "Gâteau d'anniversaire", "price": 180, "badge": "Sur commande", "desc": "Sur mesure, 48h à l'avance", "image": _img("photo-1578985545062-69928b1d9587", 400)},
        ],
    },
    "gym": {
        "name": "Salle de sport",
        "emoji": "💪",
        "label": "Salle de sport / Fitness / Coaching",
        "color": "#2C3E50",
        "font": "Oswald",
        "file": "types/gym.html",
        "ecommerce_allowed": True,
        "keywords": [
            "gym", "fitness", "salle de sport", "sport", "musculation", "coach",
            "crossfit", "yoga",
        ],
        "tagline": "Entraîne-toi avec du matériel pro et des coachs diplômés.",
        "about": (
            "Plus de 80 machines, un espace cardio, une zone poids libres et des "
            "cours collectifs tous les jours. Nos coachs construisent avec vous "
            "un programme adapté à votre objectif."
        ),
        "hero_image": _img("photo-1534438327276-14e5300c3a48", 1600),
        "gallery": [
            _img("photo-1534438327276-14e5300c3a48"),
            _img("photo-1517836357463-d25dfeac3438"),
            _img("photo-1540497077202-7c8a3999166f"),
        ],
        "features": [
            {"icon": "🏋️", "title": "Matériel pro", "text": "80 machines et zone poids libres."},
            {"icon": "🥗", "title": "Coaching & nutrition", "text": "Programme et suivi personnalisés."},
            {"icon": "🚿", "title": "Vestiaires", "text": "Douches, casiers et sauna."},
        ],
        "products": [
            {
                "name": "Abonnement Mensuel", "price": 300, "period": "/ mois", "badge": "Sans engagement",
                "desc": "Accès libre à toutes les salles, hors cours collectifs.",
                "features": ["Accès illimité 6h - 23h", "Vestiaires et douches", "Sans frais d'inscription"],
                "image": _img("photo-1517836357463-d25dfeac3438", 400),
            },
            {
                "name": "Abonnement Trimestriel", "price": 800, "period": "/ 3 mois", "badge": "Économisez 100 DH",
                "old_price": 900,
                "desc": "Trois mois d'accès libre plus deux séances de coaching.",
                "features": ["Tout le mensuel inclus", "2 séances de coaching offertes", "Économisez 100 DH"],
                "image": _img("photo-1534438327276-14e5300c3a48", 400),
            },
            {
                "name": "Abonnement Annuel", "price": 2400, "period": "/ an", "badge": "Meilleure offre",
                "old_price": 3600,
                "desc": "L'offre complète : accès libre, cours collectifs et suivi.",
                "features": ["Tout le trimestriel inclus", "Cours collectifs illimités", "Suivi nutritionnel trimestriel", "Économisez 1200 DH"],
                "image": _img("photo-1540497077202-7c8a3999166f", 400),
            },
        ],
    },
    "default": {
        "name": "Commerce",
        "emoji": "🏪",
        "label": "Autre commerce / Service de proximité",
        "color": "#34495E",
        "font": "Inter",
        "file": "types/default.html",
        "ecommerce_allowed": True,
        "keywords": [],
        "tagline": "Un service de proximité, une équipe à votre écoute.",
        "about": (
            "Nous accompagnons nos clients du quartier au quotidien avec des "
            "prestations fiables et des prix transparents. Contactez-nous pour "
            "un devis ou un rendez-vous."
        ),
        "hero_image": _img("photo-1497366754035-f200968a6e72", 1600),
        "gallery": [
            _img("photo-1486406146926-c627a92ad1ab"),
            _img("photo-1521737604893-d14cc237f11d"),
            _img("photo-1497215728101-856f4ea42174"),
        ],
        "features": [
            {"icon": "🤝", "title": "Service de confiance", "text": "Des clients fidèles depuis des années."},
            {"icon": "⏱️", "title": "Rapidité", "text": "Nous répondons dans la journée."},
            {"icon": "💰", "title": "Prix justes", "text": "Des tarifs clairs, sans surprise."},
        ],
        "products": [
            {"name": "Prestation Standard", "price": 199, "desc": "Prise en charge complète", "image": _img("photo-1521737604893-d14cc237f11d", 400)},
            {"name": "Prestation Premium", "price": 349, "desc": "Avec suivi personnalisé", "image": _img("photo-1497366754035-f200968a6e72", 400)},
            {"name": "Service express", "price": 129, "desc": "Intervention rapide", "image": _img("photo-1497215728101-856f4ea42174", 400)},
            {"name": "Diagnostic", "price": 99, "desc": "Analyse et conseil", "image": _img("photo-1486406146926-c627a92ad1ab", 400)},
            {"name": "Contrat mensuel", "price": 299, "desc": "Accompagnement récurrent", "image": _img("photo-1552664730-d307ca884978", 400)},
            {"name": "Formation", "price": 499, "desc": "Session sur mesure", "image": _img("photo-1552664730-d307ca884978", 400)},
        ],
    },
}

#: Ordre de résolution de :func:`detect_template_type` (du plus précis au plus général).
DETECTION_ORDER = ["pharmacy", "bakery", "cafe", "salon", "gym", "restaurant", "shop"]


# --------------------------------------------------------------------------- #
# Utilitaires internes
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    """Minuscule + suppression des accents, pour comparer des libellés."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().replace("_", " ").strip()


def slugify(value: str, fallback: str = "site") -> str:
    """Transforme un nom de commerce en identifiant de fichier sûr."""
    text = _normalize(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or fallback


def list_template_types() -> list[str]:
    """Retourne la liste des gabarits disponibles (clés de :data:`TEMPLATES_CONFIG`)."""
    return list(TEMPLATES_CONFIG.keys())


def get_template_config(template_name: str) -> dict:
    """Retourne la configuration d'un gabarit, avec repli sur ``default``."""
    if template_name not in TEMPLATES_CONFIG:
        LOGGER.warning("Gabarit inconnu '%s' : repli sur 'default'.", template_name)
        template_name = "default"
    return TEMPLATES_CONFIG[template_name]


# --------------------------------------------------------------------------- #
# Détection du type de commerce
# --------------------------------------------------------------------------- #
def detect_template_type(google_place_types: list[str] | None, business_name: str = "") -> str:
    """
    Détecte le gabarit le plus adapté à un commerce.

    :param google_place_types: liste des types renvoyés par Google Places
        (ex. ``["restaurant", "food", "point_of_interest"]``).
    :param business_name: nom du commerce, utilisé pour repérer des mots-clés
        français absents des types Google (ex. « Pharmacie Al Amal »).
    :return: la clé du gabarit (``restaurant``, ``cafe``, ``salon``, ``shop``,
        ``pharmacy``, ``bakery``, ``gym`` ou ``default``).
    """
    if isinstance(google_place_types, str):
        google_place_types = [google_place_types]

    types = [str(t) for t in (google_place_types or [])]
    combined = f" {_normalize(' '.join(types))} {_normalize(business_name)} "
    # Google liste le type principal en premier : il passe avant les types
    # secondaires (un café peut porter « bakery » sans être une boulangerie).
    primary = f" {_normalize(types[0])} " if types else ""

    for haystack in (primary, combined):
        if not haystack.strip():
            continue
        for key in DETECTION_ORDER:
            config = TEMPLATES_CONFIG[key]
            for keyword in config["keywords"]:
                if re.search(rf"\b{re.escape(_normalize(keyword))}\b", haystack):
                    LOGGER.debug("Type détecté '%s' via le mot-clé '%s'.", key, keyword)
                    return key

    LOGGER.debug("Aucun type reconnu pour '%s' : gabarit 'default'.", business_name)
    return "default"


def get_products_for_template(template_name: str) -> list[dict]:
    """Retourne la liste de produits / prestations associée à un gabarit."""
    return list(get_template_config(template_name)["products"])


def get_gallery_for_template(template_name: str) -> list[str]:
    """Retourne les trois visuels de galerie associés à un gabarit."""
    return list(get_template_config(template_name).get("gallery", []))


# --------------------------------------------------------------------------- #
# Enrichissement des données du commerce
# --------------------------------------------------------------------------- #
def _default_hours() -> dict[str, str]:
    """Horaires par défaut (utilisés si le commerce n'en fournit pas)."""
    return {
        "Lundi": "09:00 - 20:00",
        "Mardi": "09:00 - 20:00",
        "Mercredi": "09:00 - 20:00",
        "Jeudi": "09:00 - 20:00",
        "Vendredi": "09:00 - 20:00",
        "Samedi": "09:00 - 21:00",
        "Dimanche": "Fermé",
    }


def _moroccan_international(number: str) -> str:
    """Convertit un numéro marocain local (``06 12 34 56 78``) en format international."""
    digits = re.sub(r"[^\d]", "", str(number or ""))
    if not digits:
        return ""
    if digits.startswith("212"):
        return digits
    if digits.startswith("0"):
        return "212" + digits[1:]
    return digits


def enrich_business_data(business: dict) -> dict:
    """
    Complète un dictionnaire commerce avec toutes les valeurs attendues par les gabarits.

    Ajoute notamment ``phone``, ``whatsapp``, ``description``, ``hours``,
    ``maps_embed_url``, ``maps_link``, ``wa_link``, ``phone_tel`` et ``city``.
    Aucune clé existante n'est écrasée par une valeur vide.

    :param business: dictionnaire brut (issu de :mod:`finder` ou saisi à la main).
    :return: un nouveau dictionnaire enrichi (l'original n'est pas modifié).
    """
    data = dict(business or {})

    name = (data.get("name") or "Commerce").strip()
    address = (data.get("address") or data.get("formatted_address") or "").strip()
    city = (data.get("city") or "Casablanca").strip()
    street = (data.get("street") or "").strip()
    if not address:
        address = ", ".join(part for part in [street, city] if part) or "Maroc"

    template_type = data.get("template_type") or detect_template_type(
        data.get("types"), name
    )
    config = TEMPLATES_CONFIG.get(template_type, TEMPLATES_CONFIG["default"])

    # Téléphone / WhatsApp -------------------------------------------------- #
    phone = (data.get("phone") or data.get("formatted_phone_number") or "").strip()
    has_phone = bool(re.sub(r"[^\d]", "", phone))
    if not phone:
        phone = "+212 5 22 00 00 00"
    phone_tel = re.sub(r"[^\d+]", "", phone) or "+212522000000"

    whatsapp = re.sub(r"[^\d]", "", str(data.get("whatsapp") or "")) or _moroccan_international(phone)
    if len(whatsapp) < 9:
        whatsapp = "212522000000"

    # Description ----------------------------------------------------------- #
    description = (data.get("description") or "").strip()
    if not description:
        description = (
            f"Bienvenue chez {name}, votre {config['name'].lower()} de confiance "
            f"à {address}. {config['tagline']}"
        )

    # Horaires -------------------------------------------------------------- #
    hours = data.get("hours") or data.get("opening_hours_table") or _default_hours()
    if isinstance(hours, (list, tuple)):
        hours = {day: value for day, value in zip(_default_hours().keys(), hours)} or _default_hours()
    if not isinstance(hours, dict) or not hours:
        hours = _default_hours()

    # Géolocalisation ------------------------------------------------------- #
    lat = data.get("lat")
    lng = data.get("lng")
    if lat in (None, "") or lng in (None, ""):
        lat, lng = 33.5731, -7.5898  # centre de Casablanca
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        lat, lng = 33.5731, -7.5898

    # Liens utiles ---------------------------------------------------------- #
    maps_query = f"{name} {address}".strip().replace(" ", "+")
    maps_link = data.get("maps_link") or f"https://www.google.com/maps/search/?api=1&query={maps_query}"
    maps_embed_url = (
        data.get("maps_embed_url")
        or f"https://maps.google.com/maps?q={maps_query}&z=15&output=embed"
    )
    wa_link = f"https://wa.me/{whatsapp}"

    # Réseaux sociaux (recherche par nom : le commerçant n'a pas encore de site) #
    facebook = data.get("facebook") or f"https://www.facebook.com/search/top?q={name.replace(' ', '%20')}"
    instagram = data.get("instagram") or f"https://www.instagram.com/explore/tags/{slugify(name, 'commerce')}"

    rating = data.get("rating") or 0
    try:
        rating = float(rating)
    except (TypeError, ValueError):
        rating = 0.0

    reviews = data.get("reviews") or data.get("user_ratings_total") or 0
    try:
        reviews = int(reviews)
    except (TypeError, ValueError):
        reviews = 0

    data.update(
        {
            "name": name,
            "address": address,
            "city": city,
            "street": street,
            "phone": phone,
            "phone_tel": phone_tel,
            "has_phone": has_phone,
            "whatsapp": whatsapp,
            "description": description,
            "hours": hours,
            "lat": lat,
            "lng": lng,
            "rating": rating,
            "reviews": reviews,
            "template_type": template_type,
            "maps_link": maps_link,
            "maps_embed_url": maps_embed_url,
            "wa_link": wa_link,
            "facebook": facebook,
            "instagram": instagram,
            "year": datetime.now().year,
        }
    )
    return data


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
def _error_html(business: dict, error: Exception) -> str:
    """Page d'erreur autonome (le rendu ne doit jamais lever d'exception)."""
    name = (business or {}).get("name", "Commerce")
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Erreur de génération — {name}</title></head>
<body style="font-family:system-ui,sans-serif;padding:40px;max-width:720px;margin:auto">
  <h1 style="color:#c0392b">Génération impossible</h1>
  <p>Le site de <strong>{name}</strong> n'a pas pu être généré.</p>
  <pre style="background:#f4f4f4;padding:16px;border-radius:8px;overflow:auto">{type(error).__name__}: {error}</pre>
</body></html>"""


def render_business_site(
    business: dict,
    template_name: str,
    is_ecommerce: bool = False,
    theme: object | str | None = None,
) -> str:
    """
    Génère le code HTML complet d'un site pour un commerce.

    :param business: données du commerce (sera enrichi automatiquement).
    :param template_name: clé du gabarit (voir :data:`TEMPLATES_CONFIG`).
    :param is_ecommerce: ``True`` pour la version e-commerce (panier + commande WhatsApp).
    :param theme: thème Bootswatch à utiliser. ``None`` (ou ``"aléatoire"``) tire un
        thème reproductible à partir du commerce, ``"aucun"`` désactive les thèmes
        (couleurs du métier), et un nom de thème (``"darkly"``) l'impose.
        Un objet :class:`themes.Theme` est également accepté.
    :return: la chaîne HTML complète ; une page d'erreur si le rendu échoue.
    """
    config = get_template_config(template_name)
    if is_ecommerce and not config["ecommerce_allowed"]:
        LOGGER.info("Gabarit '%s' sans e-commerce : rendu vitrine uniquement.", template_name)
        is_ecommerce = False

    try:
        enriched = enrich_business_data(business)
        resolved_theme = theme_library.resolve_theme(enriched, theme)
        products = get_products_for_template(template_name)
        template = env.get_template(config["file"])
        html = template.render(
            business=enriched,
            products=products,
            gallery_images=get_gallery_for_template(template_name),
            features=config["features"],
            is_ecommerce=is_ecommerce,
            color=config["color"],
            font=config["font"],
            template_type=template_name,
            template_config=config,
            currency="DH",
            theme=resolved_theme.to_context() if resolved_theme else None,
            theme_css=resolved_theme.css() if resolved_theme else "",
            generator_version=GENERATOR_VERSION,
        )
        LOGGER.debug(
            "Site généré (%s, e-commerce=%s, thème=%s) pour '%s' : %d caractères.",
            template_name, is_ecommerce, resolved_theme.slug if resolved_theme else "aucun",
            enriched["name"], len(html),
        )
        return html
    except Exception as exc:  # pragma: no cover - filet de sécurité
        LOGGER.exception("Échec du rendu pour '%s'.", business)
        return _error_html(business, exc)


def create_both_versions(
    business: dict,
    template_name: str,
    theme: object | str | None = None,
) -> tuple[str, str | None]:
    """
    Génère les deux versions vendables d'un commerce.

    Le thème Bootswatch est résolu **une seule fois** : la version vitrine et la
    version e-commerce du même commerce partagent donc toujours le même thème.

    :param business: données du commerce.
    :param template_name: clé du gabarit à utiliser.
    :param theme: thème à appliquer (nom, ``"aucun"`` ou ``None`` pour un tirage auto).
    :return: ``(html_vitrine, html_ecommerce)``. Le second vaut ``None`` si le
        gabarit n'autorise pas l'e-commerce.
    """
    resolved_theme = theme_library.resolve_theme(business, theme)
    # ``None`` signifierait « tirage automatique » pour render_business_site :
    # on transmet donc explicitement « aucun » quand il n'y a pas de thème.
    token = resolved_theme if resolved_theme else "aucun"
    static_html = render_business_site(business, template_name, is_ecommerce=False, theme=token)
    ecommerce_html: str | None = None
    if get_template_config(template_name)["ecommerce_allowed"]:
        ecommerce_html = render_business_site(
            business, template_name, is_ecommerce=True, theme=token
        )
    return static_html, ecommerce_html


def get_site_theme(business: dict, theme: object | str | None = None):
    """
    Retourne le thème Bootswatch qui sera utilisé pour un commerce.

    :param business: données du commerce (nom et adresse servent de graine).
    :param theme: nom de thème, ``"aucun"``, ou ``None`` pour un tirage aléatoire.
    :return: l'objet :class:`themes.Theme` retenu, ou ``None`` si aucun thème local.
    """
    return theme_library.resolve_theme(business, theme)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def save_html_to_file(html: str, filename: str) -> str:
    """
    Écrit un site HTML sur le disque.

    :param html: contenu HTML.
    :param filename: nom de fichier ou chemin complet. Un nom seul est écrit
        dans le dossier ``output/``.
    :return: le chemin absolu du fichier écrit.
    """
    path = filename
    if not os.path.isabs(path) and os.path.dirname(path) == "":
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    LOGGER.info("Fichier écrit : %s", path)
    return os.path.abspath(path)


def create_zip_of_sites(
    static_html: str,
    ecommerce_html: str | None,
    business_name: str,
) -> bytes:
    """
    Construit une archive ZIP en mémoire contenant les deux versions du site.

    :param static_html: HTML de la version vitrine.
    :param ecommerce_html: HTML de la version e-commerce (peut être ``None``).
    :param business_name: nom du commerce, utilisé pour nommer les fichiers.
    :return: les octets de l'archive ZIP.
    """
    slug = slugify(business_name, "commerce")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{slug}-site-vitrine.html", static_html or "")
        if ecommerce_html:
            archive.writestr(f"{slug}-site-ecommerce.html", ecommerce_html)
        archive.writestr(
            "LISEZ-MOI.txt",
            (
                f"SiteBuilder Pro {GENERATOR_VERSION} — {business_name}\n"
                f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
                "1. Version vitrine  : infos, horaires, galerie, carte, contact.\n"
                "2. Version e-commerce : les mêmes sections + catalogue, panier\n"
                "   et commande envoyée sur WhatsApp.\n\n"
                "Mise en ligne : glissez le fichier .html sur Netlify Drop, Vercel,\n"
                "ou n'importe quel hébergement statique. Aucune dépendance.\n"
            ),
        )
    buffer.seek(0)
    return buffer.read()


if __name__ == "__main__":  # pragma: no cover - test manuel
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    demo = {
        "name": "Tajine Express",
        "address": "Rue Ibnou Katib, Maarif, Casablanca",
        "types": ["restaurant", "food"],
        "rating": 4.6,
        "reviews": 213,
    }
    kind = detect_template_type(demo["types"], demo["name"])
    vitrine, ecommerce = create_both_versions(demo, kind)
    theme = get_site_theme(demo)
    print(f"Gabarit : {kind}")
    print(f"Thème   : {theme.label if theme else 'aucun'} (tirage automatique)")
    print(f"Vitrine   : {len(vitrine):,} caractères")
    print(f"E-commerce: {len(ecommerce or ''):,} caractères")
