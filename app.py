"""
app.py
======

**SiteBuilder Pro — Jinja2 Edition**

Application Streamlit qui permet à un freelance de :

1. choisir une ville, un quartier et un type de commerce,
2. lister les commerces de la zone (Google Places, OpenStreetMap ou démo),
3. détecter ceux qui n'ont **pas** de site web (les leads),
4. générer automatiquement deux sites par lead : une version vitrine et une
   version e-commerce avec panier et commande WhatsApp,
5. prévisualiser, télécharger et partir vendre.

Lancement ::

    streamlit run app.py
"""

from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import datetime

import streamlit as st

import themes as theme_library
from builder import (
    TEMPLATES_CONFIG,
    create_both_versions,
    detect_template_type,
    get_template_config,
    save_html_to_file,
    slugify,
)
from checker import check_websites_batch, get_leads, summarize_leads
from finder import BUSINESS_TYPE_CHOICES, get_businesses
from version import __version__ as APP_VERSION, version_string

st.set_page_config(
    page_title="SiteBuilder Pro — Jinja2 Edition",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

POPULAR_ZONES = ["Maârif", "Gauthier", "Anfa", "Bourgogne", "Oasis", "CIL", "Derb Sultan", "Hay Hassani"]
TEMPLATE_LABELS = {key: f"{cfg['emoji']} {cfg['name']}" for key, cfg in TEMPLATES_CONFIG.items()}

#: Choix de thème dans la barre latérale.
THEME_RANDOM = "🎲 Aléatoire (un thème différent par commerce)"
THEME_NONE = "❌ Aucun (couleur du métier)"


# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #
def init_state() -> None:
    """Initialise les clés de session utilisées par l'application."""
    st.session_state.setdefault("analyzed", [])
    st.session_state.setdefault("generated", {})
    st.session_state.setdefault("search_info", {})
    st.session_state.setdefault("last_search", "")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def current_filters() -> tuple[float, int]:
    """Retourne les seuils de filtrage (note minimale, nombre d'avis minimum)."""
    return (
        st.session_state.get("min_rating", 0.0),
        st.session_state.get("min_reviews", 0),
    )


def apply_filters(businesses: list[dict]) -> list[dict]:
    """Applique les filtres de qualité (note et nombre d'avis) aux commerces."""
    min_rating, min_reviews = current_filters()
    selected = []
    for item in businesses:
        try:
            rating = float(item.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        try:
            reviews = int(item.get("reviews") or 0)
        except (TypeError, ValueError):
            reviews = 0
        # Les fiches sans note (OpenStreetMap) restent visibles par défaut.
        if rating and rating < min_rating:
            continue
        if reviews and reviews < min_reviews:
            continue
        selected.append(item)
    return selected


def build_pitch(lead: dict, template_name: str) -> str:
    """Rédige les arguments de vente à utiliser devant le commerçant."""
    cfg = get_template_config(template_name)
    score = lead.get("lead_score", 0)
    rating = lead.get("rating") or 0
    reviews = lead.get("reviews") or 0
    bullets = [
        f"**Aucun site web** : {lead.get('website_reason', 'pas de site trouvé')}. "
        "Ses clients ne le trouvent pas sur Google.",
        f"**Activité qui tourne** : {rating or '?'}/5"
        + (f" avec {reviews} avis" if reviews else "")
        + ". Il a les moyens de payer un site.",
        f"**Gabarit recommandé** : {cfg['name']} (couleur {cfg['color']}, police {cfg['font']}).",
        "**Preuve immédiate** : montre-lui les deux versions sur ton téléphone, avec son nom, "
        "son adresse et sa carte déjà intégrés.",
    ]
    if lead.get("phone"):
        bullets.append(
            f"**Contact direct** : il est joignable au {lead['phone']} — appelle avant de passer."
        )
    if lead.get("lead_grade") == "A":
        bullets.append("**Priorité A** : démarche-le en premier, il coche toutes les cases.")
    if cfg.get("ecommerce_allowed"):
        bullets.append(
            "**Upsell** : la version e-commerce (panier + commande WhatsApp) se vend "
            "au double de la vitrine."
        )
    return "\n".join(f"- {line}" for line in bullets)


def theme_choices() -> list[str]:
    """Options du sélecteur de thème : aléatoire, chaque thème local, aucun."""
    return [THEME_RANDOM] + [theme.label for theme in theme_library.available_themes()] + [THEME_NONE]


def current_theme_choice() -> str:
    """Thème choisi dans la barre latérale (libellé, ``"aucun"`` ou tirage auto)."""
    choice = st.session_state.get("theme_choice", THEME_RANDOM)
    if choice == THEME_NONE:
        return "aucun"
    if choice == THEME_RANDOM:
        return ""
    return choice


def theme_for(business: dict) -> "theme_library.Theme | None":
    """Thème qui sera appliqué à un commerce donné."""
    return theme_library.resolve_theme(business, current_theme_choice())


def theme_caption(business: dict) -> str:
    """Texte d'information sur le thème appliqué à un commerce."""
    theme = theme_for(business)
    if not theme:
        return "Aucun thème : le site utilise la couleur et la police du métier."
    kind = "thème sombre" if theme.is_dark else "thème clair"
    font = f", police {theme.font_family}" if theme.font_family else ""
    return f"Thème Bootswatch « {theme.label} » ({kind}{font}) — embarqué dans le fichier HTML."


def build_leads_zip(leads: list[dict], generated: dict) -> bytes:
    """Construit une archive ZIP contenant les deux versions de chaque lead généré."""
    buffer = io.BytesIO()
    manifest = [
        f"SiteBuilder Pro {version_string()} — export du {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for lead in leads:
            key = lead.get("place_id") or lead.get("name")
            bundle = generated.get(key)
            if not bundle:
                continue
            slug = slugify(lead.get("name", "commerce"))
            folder = slug
            archive.writestr(f"{folder}/site-vitrine.html", bundle["static"])
            if bundle.get("ecommerce"):
                archive.writestr(f"{folder}/site-ecommerce.html", bundle["ecommerce"])
            manifest.append(
                f"- {lead.get('name')} : {TEMPLATE_LABELS.get(bundle['template'], bundle['template'])}"
                f" · {bundle.get('theme') or 'sans thème'}"
            )
        archive.writestr("LISEZ-MOI.txt", "\n".join(manifest))
    buffer.seek(0)
    return buffer.read()


def leads_to_csv(leads: list[dict]) -> bytes:
    """Exporte les leads en CSV (ouvrable dans Excel) pour le suivi commercial."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Nom", "Adresse", "Téléphone", "Note", "Avis", "Type détecté",
         "Statut site", "Score", "Priorité", "Google Maps"]
    )
    for lead in leads:
        writer.writerow(
            [
                lead.get("name", ""),
                lead.get("address", ""),
                lead.get("phone", ""),
                lead.get("rating", ""),
                lead.get("reviews", ""),
                TEMPLATES_CONFIG.get(lead.get("template_type", "default"), {}).get("name", ""),
                lead.get("website_reason", ""),
                lead.get("lead_score", 0),
                lead.get("lead_grade", ""),
                f"https://www.google.com/maps/search/?api=1&query={str(lead.get('name', '')).replace(' ', '+')}",
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def run_search(source: str, api_key: str, city: str, zone: str, business_type: str) -> None:
    """Lance la recherche puis l'analyse des sites web, avec barres de progression."""
    with st.spinner(f"Recherche des commerces à {zone}, {city}..."):
        businesses, message = get_businesses(
            source=source, city=city, street=zone, business_type=business_type, api_key=api_key
        )

    if message:
        st.error(message)
    if not businesses:
        st.session_state["analyzed"] = []
        return

    progress = st.progress(0.0, text="Vérification des sites web...")
    analyzed = check_websites_batch(
        businesses,
        progress_callback=lambda done, total: progress.progress(
            done / total, text=f"Vérification des sites web... {done}/{total}"
        ),
    )
    progress.empty()

    for item in analyzed:
        item["template_type"] = detect_template_type(item.get("types"), item.get("name", ""))

    st.session_state["analyzed"] = analyzed
    st.session_state["generated"] = {}
    st.session_state["search_info"] = {
        "city": city, "zone": zone, "source": source,
        "business_type": BUSINESS_TYPE_CHOICES.get(business_type, "Tous"),
        "at": datetime.now().strftime("%H:%M"),
    }
    st.session_state["last_search"] = f"{zone}, {city}"


# --------------------------------------------------------------------------- #
# Barre latérale : configuration de la prospection
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    """Affiche les réglages de recherche dans la barre latérale."""
    with st.sidebar:
        st.title("🏗️ SiteBuilder Pro")
        st.caption(
            f"Jinja2 Edition · {version_string()} — vendez des sites aux commerces sans site web."
        )

        st.subheader("1. Source des données")
        source = st.radio(
            "Source",
            options=["demo", "google", "osm"],
            format_func=lambda value: {
                "demo": "🟢 Démonstration (hors ligne)",
                "google": "🔵 Google Places API",
                "osm": "🟠 OpenStreetMap (gratuit)",
            }[value],
            label_visibility="collapsed",
        )

        api_key = ""
        if source == "google":
            api_key = st.text_input(
                "Clé API Google Places",
                value=os.environ.get("GOOGLE_PLACES_API_KEY", ""),
                type="password",
                help="Activez « Places API » dans Google Cloud Console. "
                     "Sans clé, utilisez la démo ou OpenStreetMap.",
            )
            if not api_key:
                st.warning("Sans clé API, les résultats Google seront vides.")
        elif source == "osm":
            st.caption(
                "OpenStreetMap : gratuit et sans clé (Nominatim + Overpass), mais les fiches "
                "sont moins complètes et les serveurs publics peuvent mettre 30 à 60 secondes "
                "à répondre."
            )

        st.subheader("2. Zone à prospecter")
        city = st.text_input("Ville", value="Casablanca")
        zone_pick = st.selectbox("Quartier connu", options=["— saisir librement —"] + POPULAR_ZONES)
        default_zone = zone_pick if zone_pick != "— saisir librement —" else "Maârif"
        zone = st.text_input("Quartier / rue / zone", value=default_zone)
        business_type = st.selectbox(
            "Type de commerce",
            options=list(BUSINESS_TYPE_CHOICES.keys()),
            format_func=lambda key: BUSINESS_TYPE_CHOICES[key],
        )

        st.subheader("3. Qualité des leads")
        st.slider("Note minimale", 0.0, 5.0, 0.0, 0.5, key="min_rating")
        st.number_input("Avis minimum", min_value=0, max_value=5000, value=0, step=5, key="min_reviews")

        st.subheader("4. Thème des sites")
        installed = theme_library.available_themes()
        if installed:
            st.selectbox(
                "Thème Bootswatch",
                options=theme_choices(),
                key="theme_choice",
                help="Chaque site embarque le thème choisi. « Aléatoire » donne un thème "
                     "stable à chaque commerce : deux commerces n'ont pas le même look. "
                     "Le thème est résolu une seule fois, la vitrine et l'e-commerce "
                     "du même commerce partagent donc le même thème.",
            )
            dark = [theme.slug for theme in installed if theme.is_dark]
            st.caption(
                f"{len(installed)} thèmes installés dans `{theme_library.themes_dir()}` "
                f"({len(dark)} sombres). `python themes.py --download` pour les mettre à jour."
            )
        else:
            st.warning(
                "Aucun thème Bootswatch local. Lancez `python themes.py --download` "
                "depuis le dossier du projet, ou générez les sites avec la couleur du métier."
            )

        submitted = st.button("🔍 Rechercher les commerces", type="primary", width="stretch")

        st.divider()
        st.caption(
            "Astuce : commencez par un quartier dense (Maârif, Gauthier), "
            "concentrez-vous sur les leads de priorité A, puis passez les voir le matin."
        )

        if submitted:
            if not city.strip() or not zone.strip():
                st.error("Renseignez une ville et un quartier.")
            else:
                run_search(source, api_key, city.strip(), zone.strip(), business_type)

        info = st.session_state.get("search_info")
        if info:
            st.divider()
            st.caption(
                f"Dernière recherche : {info['zone']}, {info['city']} "
                f"({info['business_type']}) — {info['at']}"
            )


# --------------------------------------------------------------------------- #
# Vues
# --------------------------------------------------------------------------- #
def render_welcome() -> None:
    """Écran d'accueil affiché avant la première recherche."""
    st.title("🏗️ SiteBuilder Pro — Jinja2 Edition")
    st.markdown(
        "Trouvez les commerces de votre quartier **qui n'ont pas de site web**, "
        "générez-leur deux sites en quelques secondes, et allez les vendre."
    )

    col1, col2 = st.columns([1.4, 1])
    with col1:
        st.markdown(
            """
            #### Comment ça marche
            1. **Choisissez** une ville, un quartier et un type de commerce dans la barre latérale.
            2. **L'application liste** tous les commerces de la zone (Google Places, OpenStreetMap ou démo).
            3. **Elle vérifie** pour chacun s'il a un site web — et si ce site fonctionne encore.
            4. **Elle ne garde que les leads** : ceux sans site web, ou avec un site mort.
            5. **Elle génère 2 sites par lead** : une vitrine et une version e-commerce avec commande WhatsApp.

            Le gabarit, la couleur, la police, les produits, la carte et les horaires
            sont choisis automatiquement selon le type de commerce.
            """
        )
    with col2:
        st.info(
            "**Pas de clé API ?** Aucun problème : le mode démonstration contient "
            "15 commerces de Casablanca, et OpenStreetMap est gratuit.\n\n"
            "Avec une clé Google Places, vous prospectez n'importe quelle ville du Maroc.\n\n"
            "**Thèmes Bootswatch :** chaque commerce reçoit, au hasard, l'un des "
            f"{len(theme_library.available_themes())} thèmes installés localement "
            "(clair ou sombre) — deux commerces n'ont donc jamais le même look."
        )
        if st.button("▶️ Charger la démo : Casablanca / Maârif", type="primary", width="stretch"):
            run_search("demo", "", "Casablanca", "Maârif", "")
            st.rerun()

    st.divider()
    installed = theme_library.available_themes()
    st.markdown(
        f"#### Les 8 gabarits métier disponibles"
        + (f" — croisés avec {len(installed)} thèmes Bootswatch" if installed else "")
    )
    columns = st.columns(4)
    for index, (key, cfg) in enumerate(TEMPLATES_CONFIG.items()):
        with columns[index % 4]:
            st.markdown(
                f"**{cfg['emoji']} {cfg['name']}**  \n"
                f"<span style='color:{cfg['color']};font-weight:700'>{cfg['color']}</span> · "
                f"{cfg['font']}  \n"
                f"<small>{len(cfg['products'])} produits pré-remplis</small>",
                unsafe_allow_html=True,
            )


def render_dashboard(analyzed: list[dict]) -> None:
    """Affiche les statistiques et le tableau des leads."""
    filtered = apply_filters(analyzed)
    leads = get_leads(filtered, only_leads=True)
    with_site = get_leads(filtered, only_leads=False)
    stats = summarize_leads(filtered)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Commerces analysés", stats["total"])
    col2.metric("Leads sans site web", stats["leads"], help="C'est votre liste d'appels.")
    col3.metric("Leads chauds (A / B)", stats["hot_leads"])
    col4.metric("Opportunité", f"{stats['opportunity_rate']} %", help="Part de commerces sans site web.")
    return leads, with_site


def render_lead_table(leads: list[dict]) -> None:
    """Affiche le tableau des leads avec export CSV."""
    st.subheader(f"🎯 {len(leads)} lead(s) à démarcher")

    rows = [
        {
            "Priorité": lead.get("lead_grade", ""),
            "Score": lead.get("lead_score", 0),
            "Commerce": lead.get("name", ""),
            "Type": TEMPLATES_CONFIG.get(lead.get("template_type", "default"), {}).get("name", ""),
            "Note": lead.get("rating") or "—",
            "Avis": lead.get("reviews") or 0,
            "Téléphone": lead.get("phone") or "—",
            "Statut du site": lead.get("website_reason", ""),
            "Adresse": lead.get("address", ""),
        }
        for lead in leads
    ]
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "Priorité": st.column_config.TextColumn("🔥"),
        },
    )
    st.download_button(
        "⬇️ Exporter les leads (CSV pour Excel)",
        data=leads_to_csv(leads),
        file_name=f"leads-{slugify(st.session_state.get('last_search', 'prospection'))}.csv",
        mime="text/csv",
    )


def render_generator(leads: list[dict]) -> None:
    """Génère et prévisualise les deux versions de site pour un lead choisi."""
    st.divider()
    st.subheader("🛠️ Générer les sites d'un lead")

    if not leads:
        st.warning("Aucun lead à traiter : assouplissez les filtres ou changez de quartier.")
        return

    options = {f"{lead['name']} — {lead.get('lead_grade', '')} ({lead.get('lead_score', 0)}/100)": lead for lead in leads}
    choice = st.selectbox("Lead à équiper", options=list(options.keys()))
    lead = options[choice]

    detected = lead.get("template_type") or detect_template_type(lead.get("types"), lead.get("name", ""))
    template_keys = list(TEMPLATES_CONFIG.keys())

    col1, col2 = st.columns([1, 1.4])
    with col1:
        template_name = st.selectbox(
            "Gabarit",
            options=template_keys,
            index=template_keys.index(detected) if detected in template_keys else len(template_keys) - 1,
            format_func=lambda key: TEMPLATE_LABELS[key],
            help="Il est détecté automatiquement d'après le type Google du commerce. Changez-le si besoin.",
        )
        cfg = get_template_config(template_name)
        st.caption(
            f"Gabarit {cfg['name']} · e-commerce "
            f"{'inclus' if cfg['ecommerce_allowed'] else 'non disponible'} · "
            f"{theme_caption(lead)}"
        )
        generate = st.button("🚀 Générer les 2 versions", type="primary", width="stretch")
        if st.button("💾 Enregistrer dans le dossier output/", width="stretch"):
            static_html, ecommerce_html = create_both_versions(
                lead, template_name, theme=current_theme_choice()
            )
            slug = slugify(lead.get("name", "commerce"))
            static_path = save_html_to_file(static_html, f"{slug}-site-vitrine.html")
            ecommerce_path = (
                save_html_to_file(ecommerce_html, f"{slug}-site-ecommerce.html")
                if ecommerce_html else None
            )
            st.success(f"Fichiers écrits : {static_path}")
            if ecommerce_path:
                st.caption(ecommerce_path)

    key = lead.get("place_id") or lead.get("name")
    if generate:
        with st.spinner("Rendu Jinja2 des deux versions..."):
            static_html, ecommerce_html = create_both_versions(
                lead, template_name, theme=current_theme_choice()
            )
        applied = theme_for(lead)
        st.session_state["generated"][key] = {
            "static": static_html,
            "ecommerce": ecommerce_html,
            "template": template_name,
            "theme": applied.label if applied else "",
        }

    bundle = st.session_state["generated"].get(key)
    with col2:
        st.markdown("**Fiche de vente**")
        st.markdown(build_pitch(lead, template_name))

    if not bundle:
        st.info("Cliquez sur « Générer les 2 versions » pour voir les sites de ce commerce.")
        return

    tab_static, tab_shop = st.tabs(["🖥️ Version vitrine (1 fichier)", "🛒 Version e-commerce (panier + WhatsApp)"])

    with tab_static:
        st.caption("Informations, horaires, galerie, carte et bouton d'appel — tout est déjà rempli.")
        st.iframe(bundle["static"], height=760)
        st.download_button(
            "⬇️ Télécharger la version vitrine (.html)",
            data=bundle["static"].encode("utf-8"),
            file_name=f"{slugify(lead.get('name', 'commerce'))}-site-vitrine.html",
            mime="text/html",
            width="stretch",
        )

    with tab_shop:
        if bundle.get("ecommerce"):
            st.caption(
                "Catalogue, panier persistant et commande envoyée sur le WhatsApp du commerce. "
                "Aucun serveur, aucun paiement en ligne : le commerçant reçoit la commande directement."
            )
            st.iframe(bundle["ecommerce"], height=760)
            st.download_button(
                "⬇️ Télécharger la version e-commerce (.html)",
                data=bundle["ecommerce"].encode("utf-8"),
                file_name=f"{slugify(lead.get('name', 'commerce'))}-site-ecommerce.html",
                mime="text/html",
                width="stretch",
            )
        else:
            st.info("Ce gabarit n'inclut pas la version e-commerce.")


def render_batch(leads: list[dict]) -> None:
    """Génère tous les sites d'un coup et prépare l'archive ZIP."""
    st.divider()
    st.subheader("⚡ Générer tous les sites")
    st.caption(
        "Un dossier par lead, avec la version vitrine et la version e-commerce, "
        "plus un fichier de rappel pour votre suivi commercial. "
        "Chaque commerce reçoit un thème Bootswatch différent."
    )

    if st.button(f"Générer les {len(leads)} leads en une fois", width="stretch"):
        progress = st.progress(0.0, text="Rendu en cours...")
        for index, lead in enumerate(leads, start=1):
            template_name = lead.get("template_type") or detect_template_type(
                lead.get("types"), lead.get("name", "")
            )
            static_html, ecommerce_html = create_both_versions(
                lead, template_name, theme=current_theme_choice()
            )
            applied = theme_for(lead)
            st.session_state["generated"][lead.get("place_id") or lead.get("name")] = {
                "static": static_html,
                "ecommerce": ecommerce_html,
                "template": template_name,
                "theme": applied.label if applied else "",
            }
            progress.progress(index / len(leads), text=f"Rendu {index}/{len(leads)} — {lead.get('name')}")
        progress.empty()
        st.success(f"{len(leads)} commerces équipés de 2 sites chacun.")

    if st.session_state["generated"]:
        st.download_button(
            "⬇️ Télécharger toute la tournée (ZIP)",
            data=build_leads_zip(leads, st.session_state["generated"]),
            file_name=f"sites-{slugify(st.session_state.get('last_search', 'prospection'))}.zip",
            mime="application/zip",
            type="primary",
            width="stretch",
        )


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
def main() -> None:
    """Point d'entrée Streamlit."""
    init_state()
    render_sidebar()

    st.title("SiteBuilder Pro — Jinja2 Edition")
    st.caption(
        "Prospection locale : trouver les commerces sans site web, générer deux sites, les vendre. "
        f"· version {APP_VERSION}"
    )

    analyzed = st.session_state["analyzed"]
    if not analyzed:
        render_welcome()
        return

    leads, with_site = render_dashboard(analyzed)

    tab_leads, tab_leads_web, tab_generate = st.tabs(
        ["🎯 Leads sans site web", "✅ Commerces déjà équipés", "🛠️ Générateur"]
    )

    with tab_leads:
        render_lead_table(leads)
        render_batch(leads)

    with tab_leads_web:
        st.subheader(f"✅ {len(with_site)} commerce(s) avec un site en ligne")
        st.caption("Ce ne sont pas des leads : notez-les pour plus tard, ou utilisez-les comme référence de marché.")
        st.dataframe(
            [
                {
                    "Commerce": item.get("name", ""),
                    "Site web": item.get("website", ""),
                    "Statut": item.get("website_reason", ""),
                    "Note": item.get("rating") or "—",
                    "Téléphone": item.get("phone") or "—",
                }
                for item in with_site
            ],
            width="stretch",
            hide_index=True,
        )

    with tab_generate:
        render_generator(leads)


if __name__ == "__main__":
    main()
