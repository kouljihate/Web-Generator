"""
themes.py
=========

Bibliothèque locale des thèmes **Bootswatch** pour « SiteBuilder Pro — Jinja2 Edition ».

Ce module :

* **télécharge tous les thèmes Bootswatch** (Bootstrap 5) dans le dossier
  ``assets/themes/<thème>/bootstrap.min.css`` — par défaut ``../assets/themes``
  par rapport au projet, c'est-à-dire ``assets/themes`` au niveau du dossier parent,
* analyse chaque fichier CSS pour en extraire les **jetons de design**
  (couleur principale, surfaces, police, rayon des bordures...) dans un
  ``manifest.json``,
* fournit les fonctions de sélection utilisées par :mod:`builder` :
  :func:`pick_theme`, :func:`get_theme`, :func:`resolve_theme`.

Utilisation en ligne de commande ::

    python themes.py --download      # télécharge tous les thèmes + manifeste
    python themes.py --list          # liste les thèmes disponibles localement
    python themes.py --check         # vérifie que tous les fichiers sont présents

Les thèmes sont embarqués dans les sites générés (CSS complet en ligne) : chaque
site reste un fichier ``.html`` autonome, sans dépendance à ``assets/themes``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from version import __version__

LOGGER = logging.getLogger(__name__)

#: Version de Bootswatch utilisée (alignée sur Bootstrap 5.3).
BOOTSWATCH_VERSION = "5.3.8"

#: Sources de téléchargement, essayées dans l'ordre.
CDN_URLS = (
    "https://cdn.jsdelivr.net/npm/bootswatch@{version}/dist/{slug}/bootstrap.min.css",
    "https://bootswatch.com/5/{slug}/bootstrap.min.css",
)

#: API officielle : utilisée pour récupérer la liste à jour des thèmes et leurs libellés.
BOOTSWATCH_API = "https://bootswatch.com/api/5.json"

#: Les 26 thèmes Bootswatch 5.3.8 (repli hors ligne si l'API est injoignable).
FALLBACK_THEMES = [
    "brite", "cerulean", "cosmo", "cyborg", "darkly", "flatly", "journal", "litera",
    "lumen", "lux", "materia", "minty", "morph", "pulse", "quartz", "sandstone",
    "simplex", "sketchy", "slate", "solar", "spacelab", "superhero", "united",
    "vapor", "yeti", "zephyr",
]

MARKER = "bootstrap.min.css"
MANIFEST_NAME = "manifest.json"

#: Dossiers candidats, dans l'ordre : ``<projet>/assets/themes`` puis
#: ``<projet>/../assets/themes`` (l'emplacement demandé : ``..\\assets\\themes``).
THEME_DIR_CANDIDATES = (
    Path("assets") / "themes",
    Path("..") / "assets" / "themes",
)

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_ROOT_SELECTOR_RE = re.compile(r":root")
_DARK_VARIANT = "data-bs-theme=dark"
_IMPORT_RE = re.compile(r"@import\s+url\(([^)]+)\)")


# --------------------------------------------------------------------------- #
# Couleurs : petites utilitaires indépendantes du reste du projet
# --------------------------------------------------------------------------- #
def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """Convertit ``#abc`` / ``#aabbcc`` en tuple RGB (``None`` si non convertible)."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """Convertit un tuple RGB (flottants acceptés) en ``#rrggbb``."""
    return "#" + "".join(f"{max(0, min(255, round(channel))):02x}" for channel in rgb)


def _mix(color_a: str, color_b: str, weight: float) -> str:
    """
    Mélange deux couleurs. ``weight`` = part de ``color_b`` (0 → ``color_a``, 1 → ``color_b``).
    """
    rgb_a, rgb_b = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    if not rgb_a or not rgb_b:
        return color_a or color_b
    return _rgb_to_hex(tuple(a + (b - a) * weight for a, b in zip(rgb_a, rgb_b)))


def _luminance(color: str) -> float:
    """Luminance relative (0 = noir, 1 = blanc) d'une couleur hexadécimale."""
    rgb = _hex_to_rgb(color)
    if not rgb:
        return 1.0

    def channel(value: int) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(c) for c in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def readable_text(background: str, dark: str = "#14181d", light: str = "#ffffff") -> str:
    """
    Retourne le texte le plus lisible (clair ou sombre) sur une couleur de fond.

    On compare les deux contrastes réels : un seuil de luminance donnait du blanc
    sur les couleurs moyennes (le turquoise de *Minty*, 2,1:1) au lieu du noir.
    """
    if not _hex_to_rgb(background):
        return light
    return dark if contrast_ratio(dark, background) >= contrast_ratio(light, background) else light


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Ratio de contraste WCAG entre deux couleurs (1 = invisible, 21 = noir/blanc)."""
    lum_a, lum_b = _luminance(color_a), _luminance(color_b)
    high, low = max(lum_a, lum_b), min(lum_a, lum_b)
    return (high + 0.05) / (low + 0.05)


def _flatten(color: str, background: str) -> str:
    """
    Rend une couleur opaque en la composant sur un fond.

    Bootstrap exprime ses gris secondaires en ``rgba(136, 136, 136, 0.75)`` : posée
    telle quelle sur la surface, la couleur est plus pâle que prévu et le contraste
    réel n'est plus comparable aux seuils WCAG. On la compose donc d'abord.
    """
    text = str(color or "").strip()
    match = re.match(r"rgba?\(([^)]*)\)", text)
    if not match:
        return text
    parts = [part.strip() for part in match.group(1).replace("/", " ").split(",")]
    if len(parts) < 3:
        return text
    try:
        rgb = tuple(float(part) for part in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
    except ValueError:
        return text
    base = _hex_to_rgb(background) or (255, 255, 255)
    return _rgb_to_hex(tuple(b + (c - b) * alpha for b, c in zip(base, rgb)))


def ensure_readable(color: str, background: str, target: float = 4.5) -> str:
    """
    Garantit qu'une couleur reste lisible en texte sur son fond.

    Si elle échoue au seuil WCAG, on prend le noir ou le blanc (selon le fond) —
    les thèmes Bootswatch clairs comme *Minty* posent du blanc sur une couleur
    principale pâle (2,1:1), illisible pour un bouton ou une étiquette de prix.
    """
    if not _hex_to_rgb(color) or not _hex_to_rgb(background):
        return color
    if contrast_ratio(color, background) >= target:
        return color
    alternative = readable_text(background)
    if contrast_ratio(alternative, background) < target:
        # Ni le noir doux ni le blanc ne suffisent (couleurs principales moyennes de
        # *Quartz* ou *Cosmo*) : on descend jusqu'au noir/blanc purs, qui passent.
        extreme = max(("#000000", "#ffffff"), key=lambda candidate: contrast_ratio(candidate, background))
        if contrast_ratio(extreme, background) > contrast_ratio(alternative, background):
            alternative = extreme
    return alternative if contrast_ratio(alternative, background) > contrast_ratio(color, background) else color


def readable_accent(color: str, background: str, target: float = 4.5) -> str:
    """
    Éclaircit ou assombrit une couleur jusqu'à ce qu'elle soit lisible sur un fond.

    Utilisé pour les **textes accentués** : sur un thème sombre, la couleur principale
    de Bootswatch (ex. le bleu nuit de Darkly) est faite pour un bouton, pas pour du
    texte — elle doit être rehaussée pour rester lisible.
    """
    if not _hex_to_rgb(color) or not _hex_to_rgb(background):
        return color
    if contrast_ratio(color, background) >= target:
        return color
    towards = "#ffffff" if _luminance(background) < 0.5 else "#000000"
    candidate = color
    for step in range(1, 21):
        candidate = _mix(color, towards, step / 20)
        if contrast_ratio(candidate, background) >= target:
            break
    return candidate


def _push_away(background: str, text: str, target: float = 4.5, limit: float = 0.40) -> str:
    """
    Écarte un fond de la couleur de texte qui sera posée dessus.

    Un bandeau alterné à peine plus clair que la surface suffit à faire tomber un
    texte gris sous le seuil WCAG (4,37:1 chez *Minty*, 3,95:1 chez *Quartz*).
    On assombrit donc (texte clair) ou on éclaircit (texte sombre) le fond par
    petits pas, jusqu'à retrouver la lisibilité — l'écart visuel reste minime.

    :param background: couleur de fond à ajuster.
    :param text: couleur de texte qui sera posée dessus.
    :param target: ratio de contraste minimal visé.
    :param limit: amplitude maximale de l'ajustement (0–1).
    :return: le fond, inchangé s'il est déjà lisible.
    """
    if not _hex_to_rgb(background) or not _hex_to_rgb(text):
        return background
    if contrast_ratio(text, background) >= target:
        return background
    # On éloigne le fond du texte dans la direction qui augmente le contraste :
    # un fond plus sombre que le texte s'assombrit, un fond plus clair s'éclaircit.
    towards = "#000000" if _luminance(background) < _luminance(text) else "#ffffff"
    candidate = background
    step = 0.02
    while step <= limit + 1e-9:
        candidate = _mix(background, towards, step)
        if contrast_ratio(text, candidate) >= target:
            return candidate
        step += 0.02
    return candidate


def _readable_on(color: str, backgrounds, target: float = 4.5) -> str:
    """
    Ajuste une couleur de texte pour qu'elle reste lisible sur **tous** ses fonds.

    Un site pose son texte sur plusieurs surfaces (surface principale, bandeau
    alterné, fond doux, teinte colorée). On corrige la couleur jusqu'à ce que le
    fond le plus défavorable atteigne le seuil WCAG.

    :param color: couleur de texte issue du thème.
    :param backgrounds: fonds sur lesquels ce texte est réellement posé.
    :param target: ratio de contraste minimal visé.
    :return: la couleur d'origine, ou une variante éclaircie/assombrie.
    """
    usable = [bg for bg in backgrounds if _hex_to_rgb(bg)]
    if not usable or not _hex_to_rgb(color):
        return color
    candidate = color
    for _ in range(4):
        worst = min(usable, key=lambda background: contrast_ratio(candidate, background))
        if contrast_ratio(candidate, worst) >= target:
            return candidate
        nudged = readable_accent(candidate, worst, target)
        if contrast_ratio(nudged, worst) <= contrast_ratio(candidate, worst):
            nudged = readable_text(worst)
            if contrast_ratio(nudged, worst) < target:
                nudged = max(("#000000", "#ffffff"), key=lambda value: contrast_ratio(value, worst))
        candidate = nudged
    return candidate


def _rgba(color: str, alpha: float) -> str:
    """Retourne ``rgba(r, g, b, a)`` depuis une couleur hexadécimale."""
    rgb = _hex_to_rgb(color)
    if not rgb:
        return color
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


# --------------------------------------------------------------------------- #
# Résolution des chemins
# --------------------------------------------------------------------------- #
def project_root() -> Path:
    """Dossier du projet (celui qui contient ``builder.py``)."""
    return Path(__file__).resolve().parent


def themes_dir(create: bool = False) -> Path:
    """
    Retourne le dossier des thèmes.

    Le premier dossier existant parmi :data:`THEME_DIR_CANDIDATES` est retenu
    (``<projet>/assets/themes`` puis ``<projet>/../assets/themes``) ; sinon
    ``<projet>/../assets/themes`` — l'emplacement demandé — est utilisé.

    :param create: crée le dossier au besoin.
    """
    root = project_root()
    for relative in THEME_DIR_CANDIDATES:
        candidate = (root / relative).resolve()
        if (candidate / MANIFEST_NAME).exists() or any(candidate.glob(f"*/{MARKER}")):
            return candidate
    target = (root / THEME_DIR_CANDIDATES[-1]).resolve()
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def theme_css_path(slug: str) -> Path:
    """Chemin du fichier CSS d'un thème (``assets/themes/<slug>/bootstrap.min.css``)."""
    return themes_dir() / slug / MARKER


# --------------------------------------------------------------------------- #
# Analyse du CSS d'un thème
# --------------------------------------------------------------------------- #
def _iter_rules(css: str):
    """Parcourt les règles CSS ``sélecteur { déclarations }``."""
    for match in _RULE_RE.finditer(css):
        yield match.group(1).strip(), match.group(2)


def _declarations(body: str) -> dict[str, str]:
    """Extrait les variables CSS (``--x: valeur``) d'un bloc de déclarations."""
    found: dict[str, str] = {}
    for chunk in body.split(";"):
        if ":" not in chunk:
            continue
        key, value = chunk.split(":", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("--") and value:
            found[key] = value
    return found


def _resolve(tokens: dict[str, str], name: str, depth: int = 5) -> str | None:
    """Résout un jeton, y compris les indirections ``var(--autre)``."""
    value = tokens.get(name)
    if not value:
        return None
    for _ in range(depth):
        match = re.fullmatch(r"var\((--[\w-]+)(?:,\s*([^)]+))?\)", value.strip())
        if not match:
            break
        resolved = tokens.get(match.group(1)) or (match.group(2) or "").strip()
        if not resolved:
            return None
        value = resolved
    return value.strip()


def _font_from_import(css: str) -> str | None:
    """Récupère la première famille Google Fonts importée par le thème."""
    for match in _IMPORT_RE.finditer(css):
        url = match.group(1)
        family = re.search(r"family=([^&:|]+)", url)
        if family:
            return family.group(1).replace("+", " ").strip()
        families = re.search(r"family=([^&]+)", url)
        if families:
            return families.group(1).split(":")[0].replace("+", " ").strip()
    return None


#: Polices système / non web : jamais utilisables comme police de marque dans un site livré.
#: (Certains thèmes Bootswatch ont été compilés sur une machine Linux et déclarent
#: « Liberation Sans », que le navigateur du client ne possède pas.)
NON_WEB_FONTS = {
    "liberation sans", "liberation serif", "liberation mono", "dejavu sans", "dejavu serif",
    "ubuntu", "cantarell", "nimbus sans", "nimbus roman", "freesans", "freeserif", "arimo",
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "-apple-system",
    "blinkmacsystemfont", "sans-serif", "serif", "monospace", "cursive", "fantasy",
    "segoe ui", "roboto", "helvetica neue", "noto sans", "arial", "helvetica", "verdana",
    "tahoma", "trebuchet ms", "times new roman", "georgia", "calibri", "candara", "geneva",
    "apple color emoji", "segoe ui emoji", "segoe ui symbol", "noto color emoji",
}


def _first_family(stack: str | None) -> str | None:
    """Retourne la première famille **web** utilisable d'une pile de polices CSS."""
    if not stack:
        return None
    for part in stack.split(","):
        candidate = part.strip().strip('"').strip("'")
        if not candidate or candidate.startswith("var("):
            continue
        if candidate.lower() in NON_WEB_FONTS:
            continue
        return candidate
    return None


def _radius_px(value: str | None, default: float = 6.0) -> float:
    """Convertit un rayon CSS (``0.375rem``, ``25px``...) en pixels."""
    if not value:
        return default
    match = re.match(r"([\d.]+)\s*(px|rem|em)?", value.strip())
    if not match:
        return default
    number = float(match.group(1))
    unit = match.group(2) or "px"
    if unit in ("rem", "em"):
        number *= 16
    return number


@dataclass
class Theme:
    """Un thème Bootswatch analysé, prêt à être injecté dans un site."""

    slug: str
    label: str
    primary: str = "#34495E"
    primary_dark: str = "#2C3E50"
    primary_light: str = "#eef1f4"
    primary_tint: str = "#e8f0f7"
    primary_text: str = "#2C3E50"
    primary_soft_text: str = "#2C3E50"
    on_primary: str = "#ffffff"
    surface: str = "#ffffff"
    surface_alt: str = "#f7f8fa"
    surface_glass: str = "rgba(255, 255, 255, 0.94)"
    soft: str = "#f7f8fa"
    ink: str = "#232a31"
    muted: str = "#6b7280"
    ok_text: str = "#156B3A"
    line: str = "#e6e8eb"
    radius_px: float = 18.0
    radius_sm_px: float = 10.0
    font_family: str = ""
    google_font: str = ""
    is_dark: bool = False
    size_bytes: int = 0
    sha256: str = ""
    source_url: str = ""
    file: str = ""
    _css: str = field(default="", repr=False)

    # -- contexte Jinja ---------------------------------------------------- #
    def to_context(self) -> dict:
        """Dictionnaire transmis aux gabarits Jinja2."""
        return {
            "slug": self.slug,
            "label": self.label,
            "primary": self.primary,
            "primary_dark": self.primary_dark,
            "on_primary": self.on_primary,
            "surface": self.surface,
            "surface_alt": self.surface_alt,
            "surface_glass": self.surface_glass,
            "primary_light": self.primary_light,
            "primary_tint": self.primary_tint,
            "primary_text": self.primary_text,
            "primary_soft_text": self.primary_soft_text,
            "soft": self.soft,
            "ink": self.ink,
            "muted": self.muted,
            "ok_text": self.ok_text,
            "line": self.line,
            "radius_px": round(self.radius_px),
            "radius_sm_px": round(self.radius_sm_px),
            "font": self.font_family,
            "google_font": self.google_font,
            "is_dark": self.is_dark,
            "version": BOOTSWATCH_VERSION,
        }

    def to_manifest_entry(self) -> dict:
        """Version sérialisable du thème (sans le CSS)."""
        entry = asdict(self)
        entry.pop("_css", None)
        return entry

    # -- CSS --------------------------------------------------------------- #
    def css(self) -> str:
        """
        CSS complet du thème, prêt à être embarqué dans un ``<style>``.

        Le ``@charset`` d'en-tête est retiré (il n'est valide que dans un fichier
        CSS autonome et invaliderait l'``@import`` de la police Google).
        """
        if not self._css:
            path = theme_css_path(self.slug)
            if path.exists():
                self._css = path.read_text(encoding="utf-8")
        return re.sub(r'^\s*@charset\s+"[^"]+"\s*;', "", self._css, count=1).strip()


def analyze_theme(slug: str, css: str, path: Path | None = None, size_bytes: int = 0) -> Theme:
    """
    Analyse le CSS d'un thème Bootswatch et en extrait les jetons de design.

    :param slug: identifiant du thème (``darkly``, ``minty``...).
    :param css: contenu du fichier ``bootstrap.min.css``.
    :param path: chemin du fichier (pour le manifeste).
    :param size_bytes: taille du fichier.
    :return: un objet :class:`Theme` prêt à l'emploi.
    """
    default_tokens: dict[str, str] = {}
    for selector, body in _iter_rules(css):
        if not _ROOT_SELECTOR_RE.search(selector) or _DARK_VARIANT in selector:
            continue
        default_tokens.update(_declarations(body))

    def token(name: str) -> str | None:
        return _resolve(default_tokens, name)

    primary = (token("--bs-primary") or "#34495E").strip()
    if primary.startswith("rgb") or not _hex_to_rgb(primary):
        rgb = re.search(r"rgba?\(([\d,\s]+)\)", primary)
        primary = _rgb_to_hex(tuple(float(v) for v in rgb.group(1).split(",")[:3])) if rgb else "#34495E"

    surface = (token("--bs-body-bg") or "#ffffff").strip()
    if not _hex_to_rgb(surface):
        surface = "#ffffff"
    ink = (token("--bs-body-color") or "#232a31").strip()
    if not _hex_to_rgb(ink):
        ink = readable_text(surface)

    is_dark = _luminance(surface) < 0.45
    radius = _radius_px(token("--bs-border-radius"), 6.0)
    ink = _flatten(ink, surface)

    if is_dark:
        # Sur un thème sombre, on dérive les surfaces du fond plutôt que de faire
        # confiance aux jetons secondaires (souvent restés clairs chez Bootswatch).
        surface_alt = _mix(surface, "#ffffff", 0.08)
        soft = _mix(surface, "#ffffff", 0.05)
        line = _mix(surface, "#ffffff", 0.18)
        muted = _flatten(_rgba(ink, 0.7), surface)
    else:
        surface_alt = (token("--bs-secondary-bg") or _mix(surface, "#000000", 0.03)).strip()
        soft = (token("--bs-tertiary-bg") or surface_alt).strip()
        line = (token("--bs-border-color") or _mix(ink, surface, 0.85)).strip()
        muted = _flatten((token("--bs-secondary-color") or _mix(ink, surface, 0.45)).strip(), surface)
        for name, value in (("surface_alt", surface_alt), ("soft", soft), ("line", line)):
            if not _hex_to_rgb(re.sub(r"rgba?\([^)]*\)", "#000000", value or "")):
                LOGGER.debug("Jeton '%s' non hexadécimal pour %s (%s) : repli.", name, slug, value)
        if not _hex_to_rgb(surface_alt):
            surface_alt = _mix(surface, "#000000", 0.03)
        if not _hex_to_rgb(soft):
            soft = surface_alt

    # Teinte de la couleur principale (pastilles, bandeaux, boutons « ghost »).
    primary_light = _mix(primary, surface, 0.88)

    # Les textes du site ne se posent pas que sur la surface principale : les
    # bandeaux alternés, le fond doux et la teinte colorée sont plus clairs (ou
    # plus sombres) et peuvent faire tomber un gris sous le seuil WCAG. On écarte
    # d'abord ces fonds du texte, puis on rehausse les textes si besoin.
    surface_alt = _push_away(surface_alt, ink)
    soft = _push_away(soft, ink)
    primary_light = _push_away(primary_light, ink)
    backgrounds = (surface, surface_alt, soft, primary_light)

    read_ink = _readable_on(ink, backgrounds)
    read_muted = _readable_on(muted, backgrounds)
    # Vert « positif » (économies, disponibilité) : rehaussé pour rester lisible
    # sur les surfaces du thème, clair comme sombre.
    read_ok = _readable_on("#1E8449", backgrounds)

    on_primary = ensure_readable(_button_token(css, "--bs-btn-color") or readable_text(primary), primary)
    # Le survol d'un bouton principal assombrit (ou éclaircit) le fond : le libellé
    # doit rester lisible sur cet état aussi.
    primary_dark = _push_away(_button_token(css, "--bs-btn-hover-bg") or _mix(primary, "#000000", 0.22), on_primary)

    return Theme(
        slug=slug,
        label=slug.replace("-", " ").title(),
        primary=primary,
        # Teinte douce de la couleur principale, calculée sur la surface du thème :
        # elle reste lisible aussi bien sur un thème clair que sur un thème sombre.
        primary_dark=primary_dark,
        primary_light=primary_light,
        # Version très claire de la couleur principale : elle sert de texte
        # accentué sur les visuels sombres (héros), où `primary_light` — parfois
        # presque noire sur un thème sombre — serait illisible.
        primary_tint=_mix(primary, "#ffffff", 0.62),
        primary_text=_readable_on(primary, backgrounds),
        primary_soft_text=_readable_on(primary, (primary_light,)),
        on_primary=on_primary,
        surface=surface,
        surface_alt=surface_alt,
        surface_glass=_rgba(surface, 0.94),
        soft=soft,
        ink=read_ink,
        muted=read_muted,
        ok_text=read_ok,
        line=line,
        radius_px=max(4.0, min(radius, 26.0)),
        radius_sm_px=max(3.0, min(radius * 0.55, 15.0)),
        font_family=_font_from_import(css) or _first_family(
            token("--bs-body-font-family") or token("--bs-font-sans-serif")
        ) or "",
        google_font=_font_from_import(css) or "",
        is_dark=is_dark,
        size_bytes=size_bytes or len(css.encode("utf-8")),
        sha256=hashlib.sha256(css.encode("utf-8")).hexdigest(),
        file=str(path) if path else "",
        _css=css,
    )


def _button_token(css: str, name: str) -> str | None:
    """Récupère un jeton du bouton principal du thème (``.btn-primary``)."""
    for selector, body in _iter_rules(css):
        if selector.endswith(".btn-primary") or selector == ".btn-primary":
            value = _declarations(body).get(name)
            if value and _hex_to_rgb(value.strip()):
                return value.strip()
    return None


# --------------------------------------------------------------------------- #
# Téléchargement
# --------------------------------------------------------------------------- #
def fetch_theme_list() -> list[tuple[str, str]]:
    """
    Récupère la liste officielle des thèmes Bootswatch : ``[(slug, libellé), ...]``.

    En cas d'échec réseau, la liste :data:`FALLBACK_THEMES` est utilisée.
    """
    try:
        response = requests.get(BOOTSWATCH_API, timeout=30)
        response.raise_for_status()
        payload = response.json()
        themes = [
            (str(item["name"]).strip().lower(), str(item["name"]).strip())
            for item in payload.get("themes", [])
            if item.get("name")
        ]
        if themes:
            LOGGER.info("API Bootswatch : %d thèmes (v%s).", len(themes), payload.get("version"))
            return themes
    except (requests.RequestException, ValueError, KeyError) as exc:
        LOGGER.warning("API Bootswatch indisponible (%s) : liste de repli utilisée.", exc)
    return [(slug, slug.title()) for slug in FALLBACK_THEMES]


def download_themes(destination: Path | None = None, force: bool = False) -> dict:
    """
    Télécharge **tous** les thèmes Bootswatch et écrit le manifeste.

    :param destination: dossier de destination (défaut : :func:`themes_dir`).
    :param force: retélécharge même si le fichier existe déjà.
    :return: le manifeste écrit.
    """
    target = Path(destination).resolve() if destination else themes_dir(create=True)
    target.mkdir(parents=True, exist_ok=True)
    themes_meta = fetch_theme_list()
    entries: list[dict] = []
    failures: list[str] = []

    for index, (slug, label) in enumerate(themes_meta, start=1):
        folder = target / slug
        css_path = folder / MARKER
        folder.mkdir(parents=True, exist_ok=True)

        css = ""
        if css_path.exists() and not force:
            css = css_path.read_text(encoding="utf-8")
            LOGGER.info("[%2d/%d] %-12s déjà présent (%s).", index, len(themes_meta), slug, f"{len(css):,} car.")
        else:
            for template in CDN_URLS:
                url = template.format(version=BOOTSWATCH_VERSION, slug=slug)
                try:
                    response = requests.get(url, timeout=60)
                    response.raise_for_status()
                    css = response.text
                    css_path.write_text(css, encoding="utf-8")
                    LOGGER.info("[%2d/%d] %-12s téléchargé (%s car.)", index, len(themes_meta), slug, f"{len(css):,}")
                    time.sleep(0.1)
                    break
                except requests.RequestException as exc:
                    LOGGER.warning("Échec %s : %s", url, exc)
            if not css:
                failures.append(slug)
                LOGGER.error("[%2d/%d] %-12s ÉCHEC", index, len(themes_meta), slug)
                continue

        theme = analyze_theme(slug, css, path=css_path, size_bytes=len(css.encode("utf-8")))
        theme.label = label
        entries.append(theme.to_manifest_entry())
        LOGGER.info(
            "        %-12s primary=%s fond=%s police=%s%s",
            slug, theme.primary, theme.surface, theme.font_family, " (sombre)" if theme.is_dark else "",
        )

    manifest = {
        "bootswatch_version": BOOTSWATCH_VERSION,
        "bootstrap_version": "5.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "directory": str(target),
        "count": len(entries),
        "failures": failures,
        "themes": entries,
    }
    (target / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info(
        "Manifeste écrit : %s (%d thèmes, %d échec(s)).",
        target / MANIFEST_NAME, len(entries), len(failures),
    )
    _cache_clear()
    return manifest


# --------------------------------------------------------------------------- #
# Accès aux thèmes disponibles
# --------------------------------------------------------------------------- #
_MANIFEST_CACHE: dict[str, dict] = {}


def _cache_clear() -> None:
    """Vide le cache mémoire du manifeste (après téléchargement)."""
    _MANIFEST_CACHE.clear()


def load_manifest(reload: bool = False) -> dict:
    """Charge le manifeste des thèmes (``{}`` s'il n'existe pas)."""
    path = themes_dir() / MANIFEST_NAME
    key = str(path)
    if not reload and key in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[key]
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        LOGGER.error("Manifeste illisible (%s) : %s", path, exc)
        return {}
    _MANIFEST_CACHE[key] = manifest
    return manifest


def available_themes() -> list[Theme]:
    """
    Retourne tous les thèmes disponibles localement, triés par nom.

    Les thèmes sont lus depuis le manifeste ; un dossier de thème présent sans
    manifeste est analysé à la volée.
    """
    themes: list[Theme] = []
    manifest = load_manifest()
    for entry in manifest.get("themes", []):
        data = {key: value for key, value in entry.items() if key in Theme.__dataclass_fields__}
        if not (themes_dir() / entry["slug"] / MARKER).exists():
            LOGGER.warning("Thème '%s' manquant sur le disque (manifeste obsolète ?).", entry["slug"])
            continue
        themes.append(Theme(**data))

    known = {theme.slug for theme in themes}
    for folder in sorted(p for p in themes_dir().glob(f"*/{MARKER}") if p.parent.name not in known):
        css = folder.read_text(encoding="utf-8")
        themes.append(analyze_theme(folder.parent.name, css, path=folder, size_bytes=len(css.encode("utf-8"))))

    return sorted(themes, key=lambda item: item.label.lower())


def theme_names() -> list[str]:
    """Liste les identifiants des thèmes disponibles localement."""
    return [theme.slug for theme in available_themes()]


def get_theme(identifier: str | None) -> Theme | None:
    """
    Retourne un thème par identifiant (``darkly``) ou par libellé (``Darkly``).

    :return: le thème, ou ``None`` si introuvable (ou si ``identifier`` est vide).
    """
    if not identifier:
        return None
    wanted = str(identifier).strip().lower()
    if wanted in ("", "none", "aucun", "random", "aléatoire", "aleatoire", "auto"):
        return None
    for theme in available_themes():
        if wanted in (theme.slug.lower(), theme.label.lower()):
            return theme
    LOGGER.debug("Thème introuvable : %s", identifier)
    return None


def pick_theme(seed: str | int | None = None, themes: list[Theme] | None = None, exclude: list[str] | None = None) -> Theme | None:
    """
    Choisit un thème au hasard.

    :param seed: graine optionnelle. Avec une chaîne (nom du commerce), le tirage
        devient reproductible : le même commerce garde toujours le même thème.
    :param themes: vivier de thèmes (défaut : tous les thèmes locaux).
    :param exclude: identifiants à écarter du tirage.
    :return: le thème tiré, ou ``None`` si aucun thème n'est disponible.
    """
    pool = themes if themes is not None else available_themes()
    if exclude:
        excluded = {slug.lower() for slug in exclude}
        pool = [theme for theme in pool if theme.slug.lower() not in excluded]
    if not pool:
        return None
    generator = random.Random(seed) if seed is not None else random  # noqa: S311 - pas de crypto ici
    return generator.choice(pool)


def resolve_theme(business: dict | None = None, theme: str | Theme | None = None) -> Theme | None:
    """
    Détermine le thème d'un site.

    * ``theme`` est un :class:`Theme` → il est retourné tel quel ;
    * ``theme`` est un identifiant (« ``sketchy`` », « ``Darkly`` ») → ce thème ;
    * ``theme`` vaut ``"aucun"`` / ``"none"`` → aucun thème (couleurs du métier) ;
    * ``theme`` est vide ou ``"aléatoire"`` → tirage reproductible à partir du
      nom et de l'adresse du commerce (le même commerce garde donc toujours le
      même thème, et deux commerces différents en reçoivent deux différents).

    :return: le thème retenu, ou ``None`` pour un rendu sans thème.
    """
    if isinstance(theme, Theme):
        return theme
    if isinstance(theme, str) and theme.strip():
        normalized = theme.strip().lower()
        # « aucun » peut arriver seul ou dans un libellé d'interface
        # (« ❌ Aucun (couleur du métier) ») : on reconnaît les deux.
        if normalized in ("aucun", "none", "false", "non") or "aucun" in normalized:
            return None
        explicit = get_theme(theme)
        if explicit:
            return explicit
    if not available_themes():
        LOGGER.warning("Aucun thème Bootswatch local : rendu avec les couleurs du métier.")
        return None
    seed = None
    if business:
        seed = f"{business.get('name', '')}|{business.get('address', '')}|{business.get('place_id', '')}"
    return pick_theme(seed=seed)


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #
def main() -> int:
    """Point d'entrée : ``python themes.py --download|--list|--check``."""
    parser = argparse.ArgumentParser(description="Thèmes Bootswatch locaux pour SiteBuilder Pro")
    parser.add_argument("--download", action="store_true", help="télécharge tous les thèmes")
    parser.add_argument("--force", action="store_true", help="retélécharge les fichiers déjà présents")
    parser.add_argument("--reanalyze", action="store_true", help="recalcule le manifeste depuis les fichiers locaux")
    parser.add_argument("--list", action="store_true", help="liste les thèmes disponibles")
    parser.add_argument("--check", action="store_true", help="vérifie l'intégrité des fichiers")
    parser.add_argument("--destination", default=None, help="dossier de destination")
    parser.add_argument(
        "--version",
        action="version",
        version=f"SiteBuilder Pro {__version__} (Bootswatch {BOOTSWATCH_VERSION})",
        help="affiche la version et quitte",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s | %(message)s")

    if args.reanalyze:
        manifest = download_themes(Path(args.destination) if args.destination else None, force=False)
        print(f"\nManifeste recalculé : {manifest['count']} thèmes dans {manifest['directory']}")
        return 0

    if args.download:
        manifest = download_themes(Path(args.destination) if args.destination else None, force=args.force)
        print(
            f"\n{manifest['count']} thèmes téléchargés dans {manifest['directory']}"
            + (f" — échecs : {manifest['failures']}" if manifest["failures"] else "")
        )
        return 0

    themes = available_themes()
    if not themes:
        print(f"Aucun thème trouvé dans {themes_dir()}. Lancez : python themes.py --download")
        return 1

    if args.check:
        broken = [theme.slug for theme in themes if not theme_css_path(theme.slug).exists()]
        print(f"{len(themes)} thèmes déclarés · {len(broken)} fichier(s) manquant(s)")
        for theme in themes:
            print(f"  {theme.slug:12s} {theme.label:12s} {theme.size_bytes:>9,} octets  {theme.file}")
        return 1 if broken else 0

    total = sum(theme.size_bytes for theme in themes)
    print(f"{len(themes)} thèmes Bootswatch {BOOTSWATCH_VERSION} dans {themes_dir()} ({total / 1024 / 1024:.1f} Mo)")
    for theme in themes:
        kind = "sombre" if theme.is_dark else "clair "
        print(
            f"  {theme.slug:12s} {theme.label:12s} {kind} primary={theme.primary:8s} "
            f"fond={theme.surface:8s} rayon={theme.radius_px:4.0f}px  police={theme.font_family}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
