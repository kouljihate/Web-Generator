"""
checker.py
==========

Analyse des sites web des commerces trouvés par :mod:`finder`.

C'est le cœur de la logique commerciale : un commerce **sans site web** (ou avec
un site mort, en erreur, parqué ou réduit à une page Facebook) est un **lead**
à démarcher.

Fonctions principales :

* :func:`check_website_status` — analyse un commerce (1 requête réseau maximum),
* :func:`check_websites_batch` — analyse une liste en parallèle,
* :func:`get_leads` — ne garde que les commerces sans site web,
* :func:`score_lead` / :func:`lead_grade` — priorisation de la prospection,
* :func:`summarize_leads` — statistiques pour le tableau de bord.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import requests

LOGGER = logging.getLogger(__name__)

#: Domaines qui ne constituent pas un vrai site web (page sociale uniquement).
SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "tiktok.com",
    "snapchat.com", "wa.me", "linktr.ee", "linktree.com", "business.site",
    "sites.google.com", "wixsite.com", "blogspot.com",
)

#: Marqueurs d'un domaine parqué, en construction ou abandonné.
PARKED_MARKERS = (
    "domain for sale", "this domain is for sale", "buy this domain",
    "ce domaine est a vendre", "nom de domaine a vendre",
    "site en construction", "site under construction", "coming soon",
    "page en construction", "default web page", "index of /",
    "apache2 ubuntu default page", "welcome to nginx",
)

#: Types de commerces pour lesquels une version e-commerce se vend bien.
ECOMMERCE_FRIENDLY = ("restaurant", "cafe", "bakery", "pharmacy", "shop", "salon", "gym", "clothing", "store")

REQUEST_TIMEOUT = 7
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 SiteBuilderPro/1.0"
)


def _clean_website(value: str) -> str:
    """Normalise une URL de site web (ajoute ``https://`` si nécessaire)."""
    url = str(value or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url


def is_social_only(url: str) -> bool:
    """Indique si l'URL pointe vers une page sociale (Facebook, Instagram...) plutôt qu'un site."""
    lowered = str(url or "").lower()
    return any(domain in lowered for domain in SOCIAL_DOMAINS)


def _looks_parked(html: str) -> bool:
    """Détecte les pages « domaine à vendre », « site en construction », serveurs par défaut."""
    sample = (html or "")[:6000].lower()
    return any(marker in sample for marker in PARKED_MARKERS)


def check_website_status(business: dict, timeout: int = REQUEST_TIMEOUT) -> dict:
    """
    Vérifie si un commerce possède un site web réellement exploitable.

    Règles appliquées :

    * pas de champ ``website`` → pas de site (lead immédiat) ;
    * URL sociale (Facebook / Instagram / Linktree...) → pas de vrai site (lead) ;
    * site qui répond en erreur HTTP, domaine injoignable, page parquée ou
      « en construction » → pas de site exploitable (lead).

    :param business: dictionnaire commerce issu de :mod:`finder`.
    :param timeout: délai maximal de la requête HTTP en secondes.
    :return: dictionnaire ``{has_website, website, url_ok, status_code, reason, kind}``.
    """
    website = _clean_website(business.get("website") or business.get("site") or "")

    if not website:
        return {
            "has_website": False, "website": "", "url_ok": False, "status_code": None,
            "reason": "Aucun site web sur la fiche", "kind": "none",
        }

    if is_social_only(website):
        return {
            "has_website": False, "website": website, "url_ok": False, "status_code": None,
            "reason": "Page sociale uniquement (pas de vrai site)", "kind": "social",
        }

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr,en"}
    sessions = (requests,)

    status_code: int | None = None
    last_error = ""
    for client in sessions:
        try:
            response = client.get(website, headers=headers, timeout=timeout, allow_redirects=True)
            status_code = response.status_code
            if status_code < 400:
                if _looks_parked(response.text):
                    return {
                        "has_website": False, "website": website, "url_ok": False,
                        "status_code": status_code,
                        "reason": "Site en construction ou domaine parqué", "kind": "parked",
                    }
                return {
                    "has_website": True, "website": website, "url_ok": True,
                    "status_code": status_code,
                    "reason": f"Site en ligne (HTTP {status_code})", "kind": "alive",
                }
        except requests.RequestException as exc:
            last_error = exc.__class__.__name__
            LOGGER.info("Site injoignable (%s) pour '%s' : %s", website, business.get("name"), exc)

    if status_code is not None:
        return {
            "has_website": False, "website": website, "url_ok": False, "status_code": status_code,
            "reason": f"Site en erreur (HTTP {status_code}) — à refaire", "kind": "error",
        }

    return {
        "has_website": False, "website": website, "url_ok": False, "status_code": None,
        "reason": f"Domaine injoignable ({last_error or 'DNS'}) — site abandonné ?",
        "kind": "unreachable",
    }


def score_lead(business: dict) -> int:
    """
    Calcule un score de priorité (0-100) pour un lead.

    Un commerce sans site, noté au-dessus de 4,5 avec plus de 100 avis, joignable
    par téléphone et de type « vendeur » obtient le meilleur score : c'est lui
    qu'il faut démarcher en premier.

    :param business: commerce enrichi par :func:`check_websites_batch`.
    :return: score entier entre 0 et 100.
    """
    score = 0

    if not business.get("has_website"):
        score += 35
    if business.get("website_status", {}).get("kind") in ("error", "unreachable", "parked"):
        score += 5  # il avait un site : le besoin est déjà prouvé

    try:
        rating = float(business.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0.0
    if rating >= 4.5:
        score += 20
    elif rating >= 4.0:
        score += 14
    elif rating >= 3.5:
        score += 8
    else:
        score += 4  # note inconnue ou faible : à vérifier sur place

    try:
        reviews = int(business.get("reviews") or 0)
    except (TypeError, ValueError):
        reviews = 0
    if reviews >= 100:
        score += 15
    elif reviews >= 50:
        score += 10
    elif reviews >= 20:
        score += 7
    elif reviews >= 5:
        score += 3

    phone_digits = "".join(ch for ch in str(business.get("phone") or "") if ch.isdigit())
    if phone_digits:
        score += 15
        if phone_digits.lstrip("212").startswith(("6", "7")) or phone_digits.startswith(("06", "07")):
            score += 5  # mobile → WhatsApp possible, argument de vente fort

    types = " ".join(str(t).lower() for t in business.get("types", []))
    if any(keyword in types for keyword in ECOMMERCE_FRIENDLY):
        score += 10

    return max(0, min(100, score))


def lead_grade(score: int) -> str:
    """Transforme un score en note lisible : ``A`` (chaud), ``B``, ``C`` ou ``D``."""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def check_websites_batch(
    businesses: list[dict],
    max_workers: int = 8,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Analyse les sites web d'une liste de commerces en parallèle.

    :param businesses: liste de commerces.
    :param max_workers: nombre de requêtes simultanées.
    :param progress_callback: fonction ``(faits, total)`` appelée après chaque
        commerce analysé (utilisée par la barre de progression Streamlit).
    :return: nouvelle liste de commerces enrichis des clés ``has_website``,
        ``website_status``, ``website_reason``, ``is_lead``, ``lead_score``
        et ``lead_grade``.
    """
    total = len(businesses)
    if not total:
        return []

    enriched: list[dict | None] = [None] * total

    def worker(index: int, business: dict) -> tuple[int, dict]:
        status = check_website_status(business)
        item = dict(business)
        item["has_website"] = status["has_website"]
        item["website"] = status["website"] or business.get("website", "")
        item["website_status"] = status
        item["website_reason"] = status["reason"]
        item["is_lead"] = not status["has_website"]
        item["lead_score"] = score_lead(item)
        item["lead_grade"] = lead_grade(item["lead_score"])
        return index, item

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 16))) as pool:
        futures = [pool.submit(worker, index, business) for index, business in enumerate(businesses)]
        done = 0
        for future in as_completed(futures):
            index, item = future.result()
            enriched[index] = item
            done += 1
            if progress_callback:
                progress_callback(done, total)

    result = [item for item in enriched if item is not None]
    leads = sum(1 for item in result if item["is_lead"])
    LOGGER.info("%d commerces analysés : %d leads sans site web.", len(result), leads)
    return result


def get_leads(businesses: list[dict], only_leads: bool = True) -> list[dict]:
    """
    Filtre la liste des commerces pour ne garder que les leads.

    :param businesses: commerces enrichis (ou bruts : la vérification sera faite).
    :param only_leads: ``True`` pour ne garder que les commerces sans site web,
        ``False`` pour les commerces ayant déjà un site.
    :return: liste filtrée, triée par score de lead décroissant.
    """
    if not businesses:
        return []

    prepared: list[dict] = []
    for business in businesses:
        if "is_lead" in business:
            prepared.append(business)
            continue
        status = check_website_status(business)
        item = dict(business)
        item["has_website"] = status["has_website"]
        item["website_status"] = status
        item["website_reason"] = status["reason"]
        item["is_lead"] = not status["has_website"]
        item["lead_score"] = score_lead(item)
        item["lead_grade"] = lead_grade(item["lead_score"])
        prepared.append(item)

    selected = [item for item in prepared if bool(item.get("is_lead")) is bool(only_leads)]
    return sorted(selected, key=lambda item: item.get("lead_score", 0), reverse=True)


def summarize_leads(businesses: list[dict]) -> dict:
    """
    Calcule les statistiques affichées dans le tableau de bord.

    :param businesses: commerces enrichis par :func:`check_websites_batch`.
    :return: dictionnaire ``{total, with_website, leads, hot_leads, avg_rating,
        top_zone_report}``.
    """
    total = len(businesses or [])
    with_website = sum(1 for item in (businesses or []) if item.get("has_website"))
    leads = total - with_website
    hot = sum(1 for item in (businesses or []) if item.get("lead_grade") in ("A", "B"))
    rated = [float(item.get("rating") or 0) for item in (businesses or []) if item.get("rating")]
    avg_rating = round(sum(rated) / len(rated), 2) if rated else 0.0

    return {
        "total": total,
        "with_website": with_website,
        "leads": leads,
        "hot_leads": hot,
        "avg_rating": avg_rating,
        "opportunity_rate": round(100 * leads / total, 1) if total else 0.0,
    }


if __name__ == "__main__":  # pragma: no cover - test manuel
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    from finder import get_businesses_demo

    results = check_websites_batch(get_businesses_demo())
    stats = summarize_leads(results)
    print(f"{stats['total']} commerces · {stats['leads']} leads · {stats['with_website']} avec site")
    for item in get_leads(results):
        print(f"  [{item['lead_grade']}] {item['lead_score']:3d} · {item['name']} — {item['website_reason']}")
