"""
version.py
==========

Source unique de la version de **SiteBuilder Pro — Jinja2 Edition**.

La version vit dans le fichier ``VERSION`` (une ligne, par exemple ``1.1.0``) :
c'est le seul endroit à modifier pour publier une nouvelle version. ``version.py``
la lit à l'import et l'expose aux autres modules.

Utilisation ::

    >>> from version import __version__, APP_NAME
    >>> __version__.count(".")
    2

Rappel du versionnage sémantique (https://semver.org/lang/fr/) :

* **MAJEUR** — changement qui casse l'usage existant (API publique, format des leads) ;
* **MINEUR** — nouvelle fonctionnalité compatible (nouveau gabarit, nouveau thème) ;
* **CORRECTIF** — correction de bug ou de lisibilité sans changement d'usage.
"""

from __future__ import annotations

from pathlib import Path

#: Nom commercial de l'application.
APP_NAME = "SiteBuilder Pro — Jinja2 Edition"

#: Fichier contenant la version courante (à la racine du projet).
VERSION_FILE = Path(__file__).with_name("VERSION")


def read_version() -> str:
    """
    Lit la version depuis le fichier ``VERSION``.

    :return: la version (``"1.1.0"``), ou ``"0.0.0"`` si le fichier est absent
        ou illisible — l'application reste utilisable dans tous les cas.
    """
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return value or "0.0.0"


#: Version courante, par exemple ``"1.1.0"``.
__version__ = read_version()

#: Alias explicite pour les imports ``from version import VERSION``.
VERSION = __version__

#: Version sous forme de tuple comparable : ``(1, 1, 0)``.
VERSION_INFO = tuple(int(part) for part in __version__.split(".") if part.isdigit())


def version_string(prefix: str = "v") -> str:
    """
    Version formatée pour l'affichage.

    :param prefix: préfixe ajouté devant le numéro (``"v"`` par défaut).
    :return: ``"v1.1.0"``.
    """
    return f"{prefix}{__version__}"


__all__ = ["APP_NAME", "VERSION", "VERSION_FILE", "VERSION_INFO", "__version__", "read_version", "version_string"]
