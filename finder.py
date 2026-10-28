"""
finder.py
=========

Recherche de commerces locaux pour « SiteBuilder Pro — Jinja2 Edition ».

Trois sources disponibles :

* :func:`get_businesses_demo` — jeu de données marocain hors ligne (aucune clé API),
* :func:`get_businesses_google` — Google Places (Text Search + Place Details),
* :func:`get_businesses_osm` — OpenStreetMap (Nominatim + Overpass), gratuit, sans clé.

:func:`get_businesses` est le point d'entrée unique utilisé par l'application.

Chaque commerce est renvoyé sous forme de dictionnaire normalisé :

    {
        "name": "Restaurant Le Riad",
        "address": "45 Rue Ibnou Katib, Maârif, Casablanca",
        "city": "Casablanca",
        "street": "Maârif",
        "types": ["restaurant", "food"],
        "place_id": "demo-1",
        "rating": 4.5,
        "reviews": 268,
        "phone": "+212 522 25 33 44",
        "website": "",            # vide => commerce sans site web
        "hours": {"Lundi": "12:00 - 23:00", ...},
        "lat": 33.5883,
        "lng": -7.6321,
        "source": "demo"
    }
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

LOGGER = logging.getLogger(__name__)

#: En-tête imposé par la politique d'usage de Nominatim / Overpass.
OSM_HEADERS = {
    "User-Agent": "SiteBuilderPro/1.0 (outil de prospection locale; contact: local)",
    "Accept-Language": "fr,en",
}

GOOGLE_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,international_phone_number,"
    "website,opening_hours,geometry,rating,user_ratings_total,types,place_id"
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: Miroirs Overpass essayés dans l'ordre, avec un délai adapté : l'instance
#: publique principale met souvent 30 à 60 secondes à répondre (file d'attente)
#: et tombe parfois en « 502 Bad Gateway » ; le miroir prend alors le relais.
OVERPASS_ENDPOINTS = (
    ("https://overpass-api.de/api/interpreter", 75),
    ("https://overpass.kumi.systems/api/interpreter", 60),
)

#: Types Google associés à chaque catégorie proposée dans l'interface.
BUSINESS_TYPE_CHOICES: dict[str, str] = {
    "": "Tous les commerces",
    "restaurant": "Restaurant / Snack",
    "cafe": "Café / Salon de thé",
    "salon": "Salon de coiffure / Beauté",
    "boutique": "Boutique / Prêt-à-porter",
    "pharmacie": "Pharmacie / Parapharmacie",
    "boulangerie": "Boulangerie / Pâtisserie",
    "salle de sport": "Salle de sport / Fitness",
}

_GOOGLE_TYPE_KEYWORDS = {
    "restaurant": "restaurant",
    "cafe": "cafe",
    "salon": "beauty salon",
    "boutique": "boutique vetements",
    "pharmacie": "pharmacie",
    "boulangerie": "boulangerie patisserie",
    "salle de sport": "salle de sport",
}

_OSM_FILTERS = {
    "restaurant": ('["amenity"~"restaurant|fast_food|food_court"]',),
    "cafe": ('["amenity"~"cafe|ice_cream"]',),
    "salon": ('["shop"~"hairdresser|beauty"]', '["amenity"="spa"]'),
    "boutique": ('["shop"~"clothes|shoes|jewelry|bag|fashion"]',),
    "pharmacie": ('["amenity"="pharmacy"]', '["healthcare"="pharmacy"]'),
    "boulangerie": ('["shop"~"bakery|pastry|confectionery"]',),
    "salle de sport": ('["leisure"~"fitness_centre|sports_centre"]',),
    "": (
        '["amenity"~"restaurant|fast_food|cafe|pharmacy|spa"]',
        '["shop"~"clothes|shoes|jewelry|bakery|pastry|hairdresser|beauty|convenience"]',
        '["leisure"~"fitness_centre|sports_centre"]',
    ),
}


# --------------------------------------------------------------------------- #
# Jeu de démonstration
# --------------------------------------------------------------------------- #
def get_businesses_demo(
    city: str = "Casablanca",
    street: str = "Maârif",
    business_type: str = "",
) -> list[dict]:
    """
    Retourne 15 commerces marocains réalistes, sans appel réseau.

    Le quartier demandé est appliqué aux adresses, ce qui permet de tester
    l'application sans clé API. 14 commerces n'ont aucun site exploitable (les
    leads) et 1 possède un site en ligne : le filtrage de
    :func:`checker.get_leads` reste donc visible dans l'interface.

    :param city: ville affichée dans les adresses et les sites générés.
    :param street: quartier / zone utilisé pour construire les adresses.
    :param business_type: filtre optionnel sur le type (``restaurant``, ``salon``...).
    :return: liste de dictionnaires commerces normalisés.
    """
    hours_shop = {
        "Lundi": "09:00 - 20:00", "Mardi": "09:00 - 20:00", "Mercredi": "09:00 - 20:00",
        "Jeudi": "09:00 - 20:00", "Vendredi": "09:00 - 20:00",
        "Samedi": "09:00 - 21:00", "Dimanche": "Fermé",
    }
    hours_food = {
        "Lundi": "12:00 - 23:30", "Mardi": "12:00 - 23:30", "Mercredi": "12:00 - 23:30",
        "Jeudi": "12:00 - 23:30", "Vendredi": "12:00 - 00:30",
        "Samedi": "12:00 - 00:30", "Dimanche": "12:00 - 23:00",
    }
    hours_cafe = {
        "Lundi": "07:00 - 22:00", "Mardi": "07:00 - 22:00", "Mercredi": "07:00 - 22:00",
        "Jeudi": "07:00 - 22:00", "Vendredi": "07:00 - 23:00",
        "Samedi": "08:00 - 23:00", "Dimanche": "08:00 - 22:00",
    }

    raw: list[dict] = [
        {
            "name": "Restaurant Le Riad",
            "types": ["restaurant", "food", "point_of_interest"],
            "rating": 4.5, "reviews": 268,
            "phone": "+212 522 25 33 44", "website": "",
            "address": f"45 Rue Ibnou Katib, {street}, {city}",
            "lat": 33.5883, "lng": -7.6321, "hours": hours_food,
        },
        {
            "name": "Café Andalous",
            "types": ["cafe", "food", "point_of_interest"],
            "rating": 4.3, "reviews": 141,
            "phone": "+212 522 27 18 90", "website": "",
            "address": f"12 Rue Jean Jaurès, {street}, {city}",
            "lat": 33.5899, "lng": -7.6288, "hours": hours_cafe,
        },
        {
            "name": "Salon Nour Beauté",
            "types": ["beauty_salon", "hair_care", "point_of_interest"],
            "rating": 4.7, "reviews": 96,
            "phone": "+212 661 44 22 10", "website": "",
            "address": f"88 Rue Mustapha El Maani, {street}, {city}",
            "lat": 33.5912, "lng": -7.6344, "hours": hours_shop,
        },
        {
            "name": "Boulangerie Al Firdaous",
            "types": ["bakery", "store", "food"],
            "rating": 4.4, "reviews": 187,
            "phone": "+212 522 23 71 05", "website": "",
            "address": f"24 Rue Socrate, {street}, {city}",
            "lat": 33.5866, "lng": -7.6352, "hours": {
                "Lundi": "05:30 - 21:00", "Mardi": "05:30 - 21:00", "Mercredi": "05:30 - 21:00",
                "Jeudi": "05:30 - 21:00", "Vendredi": "05:30 - 21:00",
                "Samedi": "05:30 - 21:30", "Dimanche": "06:00 - 13:00",
            },
        },
        {
            "name": "Pharmacie Al Amal",
            "types": ["pharmacy", "health", "store"],
            "rating": 4.6, "reviews": 74,
            "phone": "+212 522 25 09 61", "website": "",
            "address": f"6 Rue Ahmed Charci, {street}, {city}",
            "lat": 33.5871, "lng": -7.6309, "hours": {
                "Lundi": "08:30 - 22:00", "Mardi": "08:30 - 22:00", "Mercredi": "08:30 - 22:00",
                "Jeudi": "08:30 - 22:00", "Vendredi": "08:30 - 22:00",
                "Samedi": "08:30 - 22:00", "Dimanche": "09:00 - 20:00",
            },
        },
        {
            "name": "Boutique Zine Prêt-à-porter",
            "types": ["clothing_store", "store", "point_of_interest"],
            "rating": 4.2, "reviews": 58,
            "phone": "+212 664 77 31 88", "website": "",
            "address": f"51 Rue Oued Fès, {street}, {city}",
            "lat": 33.5918, "lng": -7.6267, "hours": hours_shop,
        },
        {
            "name": "Tacos House Maârif",
            "types": ["restaurant", "meal_takeaway", "fast_food"],
            "rating": 4.1, "reviews": 312,
            "phone": "+212 662 15 40 92", "website": "",
            "address": f"33 Rue Bapaume, {street}, {city}",
            "lat": 33.5891, "lng": -7.6245, "hours": hours_food,
        },
        {
            "name": "Salon de thé Riad Zitoune",
            "types": ["cafe", "tea_house", "food"],
            "rating": 4.8, "reviews": 205,
            "phone": "+212 522 26 84 17", "website": "",
            "address": f"19 Rue Tanger, {street}, {city}",
            "lat": 33.5855, "lng": -7.6291, "hours": hours_cafe,
        },
        {
            "name": "Fitness Club Atlas",
            "types": ["gym", "health", "point_of_interest"],
            "rating": 4.4, "reviews": 129,
            "phone": "+212 522 48 12 30", "website": "",
            "address": f"72 Boulevard Anfa, {street}, {city}",
            "lat": 33.5927, "lng": -7.6385, "hours": {
                "Lundi": "06:00 - 23:00", "Mardi": "06:00 - 23:00", "Mercredi": "06:00 - 23:00",
                "Jeudi": "06:00 - 23:00", "Vendredi": "06:00 - 23:00",
                "Samedi": "07:00 - 22:00", "Dimanche": "08:00 - 20:00",
            },
        },
        {
            "name": "Pâtisserie Manar",
            "types": ["bakery", "pastry", "store"],
            "rating": 4.5, "reviews": 163,
            "phone": "+212 522 22 47 63", "website": "",
            "address": f"40 Rue Mohamed El Baqal, {street}, {city}",
            "lat": 33.5849, "lng": -7.6328, "hours": hours_shop,
        },
        {
            "name": "Barber King Coiffure",
            "types": ["hair_care", "beauty_salon", "point_of_interest"],
            "rating": 4.3, "reviews": 88,
            "phone": "+212 665 90 12 44", "website": "",
            "address": f"15 Rue Ali Ibn Abi Talib, {street}, {city}",
            "lat": 33.5902, "lng": -7.6221, "hours": {
                "Lundi": "10:00 - 21:00", "Mardi": "10:00 - 21:00", "Mercredi": "10:00 - 21:00",
                "Jeudi": "10:00 - 21:00", "Vendredi": "10:00 - 21:00",
                "Samedi": "10:00 - 22:00", "Dimanche": "Fermé",
            },
        },
        {
            "name": "Épicerie Fine Argan",
            "types": ["convenience_store", "store", "food"],
            "rating": 4.0, "reviews": 37,
            "phone": "+212 522 25 77 19", "website": "",
            "address": f"9 Rue Ibn Mounir, {street}, {city}",
            "lat": 33.5863, "lng": -7.6265, "hours": hours_shop,
        },
        {
            "name": "Restaurant Poisson d'Anfa",
            "types": ["restaurant", "seafood", "food"],
            "rating": 4.6, "reviews": 421,
            "phone": "+212 522 36 55 08", "website": "",
            "address": f"111 Boulevard d'Anfa, {street}, {city}",
            "lat": 33.5936, "lng": -7.6412, "hours": hours_food,
        },
        # Déjà en ligne : ce commerce ne doit PAS ressortir comme lead.
        # (Domaine réel et actif, utilisé pour que le filtrage soit démontrable.)
        {
            "name": "Rick's Café Casablanca",
            "types": ["restaurant", "food", "point_of_interest"],
            "rating": 4.4, "reviews": 2860,
            "phone": "+212 522 27 42 07", "website": "https://www.rickscafe.ma",
            "address": f"248 Boulevard Sour Jdid, {street}, {city}",
            "lat": 33.6019, "lng": -7.6187, "hours": hours_food,
        },
        # Domaine abandonné : le commerce redevient un lead, priorité haute.
        # (Utilisez ce cas pour montrer au client qu'un site mort coûte des clients.)
        {
            "name": "Hôtel Maârif Palace",
            "types": ["lodging", "point_of_interest"],
            "rating": 4.2, "reviews": 640,
            "phone": "+212 522 27 00 00", "website": "https://www.maarif-palace.ma",
            "address": f"12 Boulevard Al Massira, {street}, {city}",
            "lat": 33.5948, "lng": -7.6302, "hours": hours_shop,
        },
    ]

    wanted = (business_type or "").strip().lower()
    businesses: list[dict] = []
    for index, item in enumerate(raw, start=1):
        entry = dict(item)
        entry.setdefault("city", city)
        entry.setdefault("street", street)
        entry["place_id"] = f"demo-{index}"
        entry["source"] = "demo"
        entry["reviews"] = entry.get("reviews", 0)
        businesses.append(entry)

    if wanted:
        filtered = [
            entry for entry in businesses
            if any(wanted.split()[0] in str(t).lower() for t in entry.get("types", []))
            or wanted in entry["name"].lower()
        ]
        businesses = filtered or businesses

    LOGGER.info("%d commerces de démonstration générés (%s / %s).", len(businesses), street, city)
    return businesses


# --------------------------------------------------------------------------- #
# Google Places
# --------------------------------------------------------------------------- #
def get_business_details(api_key: str, place_id: str, session: requests.Session | None = None) -> dict:
    """
    Récupère les détails d'un lieu via l'API Google Place Details.

    :param api_key: clé API Google Places.
    :param place_id: identifiant Google du lieu.
    :param session: session ``requests`` réutilisable (optionnel).
    :return: dictionnaire normalisé (``{}`` en cas d'échec).
    """
    if not api_key or not place_id:
        return {}
    client = session or requests
    try:
        response = client.get(
            GOOGLE_DETAILS_URL,
            params={"place_id": place_id, "fields": GOOGLE_DETAIL_FIELDS, "key": api_key},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        LOGGER.warning("Erreur Place Details (%s) : %s", place_id, exc)
        return {}

    status = payload.get("status")
    if status != "OK":
        LOGGER.warning("Place Details '%s' pour %s : %s", status, place_id, payload.get("error_message", ""))
        return {}

    result = payload.get("result", {})
    location = result.get("geometry", {}).get("location", {})
    return {
        "name": result.get("name", ""),
        "address": result.get("formatted_address", ""),
        "phone": result.get("international_phone_number") or result.get("formatted_phone_number") or "",
        "website": result.get("website", ""),
        "rating": result.get("rating", 0),
        "reviews": result.get("user_ratings_total", 0),
        "types": result.get("types", []),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "hours": _google_hours_to_dict(result),
    }


def _google_hours_to_dict(result: dict) -> dict:
    """Convertit ``opening_hours.weekday_text`` en dictionnaire français."""
    weekday_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    texts = result.get("opening_hours", {}).get("weekday_text") or []
    hours: dict[str, str] = {}
    for name, text in zip(weekday_names, texts):
        value = text.split(":", 1)[-1].strip() if ":" in text else text.strip()
        hours[name] = value or "Fermé"
    return hours


def get_businesses_google(
    api_key: str,
    city: str,
    street: str,
    business_type: str = "",
) -> list[dict]:
    """
    Recherche des commerces via Google Places (Text Search puis Place Details).

    La requête envoyée est ``"{type} in {quartier}, {ville}"``. Chaque résultat
    est complété (téléphone, site web, horaires, coordonnées) par un appel
    Place Details.

    :param api_key: clé API Google Places activée.
    :param city: ville recherchée (ex. ``Casablanca``).
    :param street: quartier ou rue (ex. ``Maârif``).
    :param business_type: catégorie optionnelle (voir :data:`BUSINESS_TYPE_CHOICES`).
    :return: liste de commerces normalisés ; liste vide en cas d'erreur.
    """
    if not api_key:
        LOGGER.error("Clé API Google Places manquante.")
        return []

    keyword = _GOOGLE_TYPE_KEYWORDS.get(business_type.strip().lower(), business_type.strip())
    query = f"{keyword} in {street}, {city}, Maroc" if keyword else f"commerce in {street}, {city}, Maroc"
    LOGGER.info("Recherche Google Places : %s", query)

    session = requests.Session()
    try:
        response = session.get(
            GOOGLE_TEXT_SEARCH_URL,
            params={"query": query, "region": "ma", "language": "fr", "key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        LOGGER.error("Erreur Text Search : %s", exc)
        return []

    status = payload.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        LOGGER.error(
            "Text Search refusé (%s) : %s", status, payload.get("error_message", "vérifiez la clé API")
        )
        return []
    if status == "ZERO_RESULTS":
        LOGGER.info("Aucun résultat pour %s.", query)
        return []

    businesses: list[dict] = []
    for place in payload.get("results", []):
        place_id = place.get("place_id", "")
        details = get_business_details(api_key, place_id, session=session)
        location = place.get("geometry", {}).get("location", {})
        business = {
            "name": details.get("name") or place.get("name", ""),
            "address": details.get("address") or place.get("formatted_address", ""),
            "city": city,
            "street": street,
            "types": details.get("types") or place.get("types", []),
            "place_id": place_id,
            "rating": details.get("rating") or place.get("rating", 0),
            "reviews": details.get("reviews") or place.get("user_ratings_total", 0),
            "phone": details.get("phone", ""),
            "website": details.get("website", ""),
            "hours": details.get("hours") or {},
            "lat": details.get("lat") or location.get("lat"),
            "lng": details.get("lng") or location.get("lng"),
            "source": "google",
        }
        businesses.append(business)
        time.sleep(0.05)  # respecte le débit de l'API

    LOGGER.info("%d commerces récupérés depuis Google Places.", len(businesses))
    return businesses


# --------------------------------------------------------------------------- #
# OpenStreetMap (Nominatim + Overpass)
# --------------------------------------------------------------------------- #
def _osm_types(tags: dict) -> list[str]:
    """Traduit les tags OSM en liste de types proche du format Google."""
    types: list[str] = []
    for key in ("amenity", "shop", "leisure", "healthcare", "craft", "office", "club"):
        value = tags.get(key)
        if value:
            types.append(value)
    if tags.get("beauty") == "yes" and "beauty" not in types:
        types.append("beauty")
    if any(t in ("hairdresser", "beauty") for t in types):
        types.append("beauty_salon")
    if "restaurant" in types or "fast_food" in types:
        types.append("restaurant")
    if "fitness_centre" in types:
        types.append("gym")
    return types


def get_businesses_osm(city: str, street: str, business_type: str = "") -> list[dict]:
    """
    Recherche des commerces sur OpenStreetMap — gratuit et sans clé API.

    Deux étapes : Nominatim géolocalise le quartier, puis Overpass renvoie les
    commerces situés dans la zone.

    :param city: ville recherchée.
    :param street: quartier ou rue recherché.
    :param business_type: catégorie optionnelle (voir :data:`BUSINESS_TYPE_CHOICES`).
    :return: liste de commerces normalisés ; liste vide en cas d'erreur ou si la
        zone n'est pas trouvée.
    """
    query = f"{street}, {city}, Maroc"
    LOGGER.info("Géocodage OSM : %s", query)
    try:
        geo = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers=OSM_HEADERS,
            timeout=15,
        )
        geo.raise_for_status()
        places = geo.json()
    except requests.RequestException as exc:
        LOGGER.error("Nominatim indisponible : %s", exc)
        return []

    if not places:
        LOGGER.warning("Zone introuvable sur OpenStreetMap : %s", query)
        return []

    south, north, west, east = places[0]["boundingbox"]
    bbox = f"{south},{west},{north},{east}"
    filters = _OSM_FILTERS.get(business_type.strip().lower(), _OSM_FILTERS[""])
    parts = "\n".join(f'  node{flt}({bbox});' for flt in filters)
    overpass_query = f"[out:json][timeout:25];\n(\n{parts}\n);\nout center tags 80;"

    payload: dict | None = None
    for endpoint, timeout in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(
                endpoint,
                data={"data": overpass_query},
                headers=OSM_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            LOGGER.info("Réponse Overpass reçue depuis %s.", endpoint)
            break
        except (requests.RequestException, ValueError) as exc:
            LOGGER.warning("Miroir Overpass indisponible (%s) : %s", endpoint, exc)

    if payload is None:
        LOGGER.error("Aucun miroir Overpass n'a répondu : réessayez dans quelques minutes.")
        return []

    businesses: list[dict] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("name:fr")
        if not name:
            continue  # un commerce sans nom n'est pas exploitable commercialement
        address_parts = [
            tags.get("addr:street", ""),
            tags.get("addr:housenumber", ""),
        ]
        address = " ".join(part for part in reversed(address_parts) if part).strip()
        address = f"{address}, {street}, {city}" if address else f"{street}, {city}"
        center = element.get("center", {})
        businesses.append(
            {
                "name": name,
                "address": address,
                "city": city,
                "street": street,
                "types": _osm_types(tags),
                "place_id": f"osm-{element.get('id')}",
                "rating": 0,
                "reviews": 0,
                "phone": tags.get("phone") or tags.get("contact:phone", ""),
                "website": tags.get("website") or tags.get("contact:website", ""),
                "hours": {"Lundi": tags.get("opening_hours", "09:00 - 20:00")},
                "lat": element.get("lat") or center.get("lat"),
                "lng": element.get("lon") or center.get("lon"),
                "source": "osm",
            }
        )

    LOGGER.info("%d commerces récupérés depuis OpenStreetMap.", len(businesses))
    return businesses


# --------------------------------------------------------------------------- #
# Point d'entrée unique
# --------------------------------------------------------------------------- #
def get_businesses(
    source: str = "demo",
    city: str = "Casablanca",
    street: str = "Maârif",
    business_type: str = "",
    api_key: str = "",
) -> tuple[list[dict], str]:
    """
    Récupère les commerces depuis la source choisie.

    :param source: ``"demo"``, ``"google"`` ou ``"osm"``.
    :param city: ville recherchée.
    :param street: quartier ou rue.
    :param business_type: catégorie optionnelle.
    :param api_key: clé API Google Places (obligatoire pour ``source="google"``).
    :return: ``(commerces, message)`` — le message est destiné à l'interface
        (avertissement ou erreur), chaîne vide quand tout va bien.
    """
    source = (source or "demo").lower()

    if source == "google":
        if not api_key:
            return [], "Clé API Google Places manquante : passez en mode démonstration ou OpenStreetMap."
        businesses = get_businesses_google(api_key, city, street, business_type)
        if not businesses:
            return [], (
                "Aucun commerce trouvé avec Google Places. Vérifiez que la clé est valide, "
                "que l'API « Places API » est activée, ou essayez OpenStreetMap."
            )
        return businesses, ""

    if source == "osm":
        businesses = get_businesses_osm(city, street, business_type)
        if not businesses:
            return [], (
                "Aucun commerce trouvé sur OpenStreetMap pour cette zone (le service public "
                "peut aussi être saturé — réessayez dans un instant). Essayez un quartier "
                "plus large, ou passez en mode démonstration."
            )
        return businesses, ""

    return get_businesses_demo(city, street, business_type), ""
