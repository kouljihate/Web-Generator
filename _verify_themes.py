"""Vérification temporaire : thèmes Bootswatch embarqués, tokens, hasard et repli sans thème."""
import re
from collections import Counter
from html.parser import HTMLParser

import themes as theme_library
from builder import TEMPLATES_CONFIG, create_both_versions, detect_template_type, get_site_theme

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class StructureChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag not in self.stack:
            self.errors.append(f"</{tag}> fermée sans ouverture")
            return
        while self.stack:
            opened = self.stack.pop()
            if opened == tag:
                return
            self.errors.append(f"<{opened}> non fermée avant </{tag}>")


def check_html(html):
    parser = StructureChecker()
    parser.feed(html)
    problems = list(parser.errors)
    if parser.stack:
        problems.append(f"balises non fermées : {parser.stack}")
    for leak in ("{{", "{%", "{#", "Undefined"):
        if leak in html:
            problems.append(f"fuite de gabarit : {leak!r}")
    if "</html>" not in html:
        problems.append("pas de </html>")
    return problems


def css_var(html, name):
    match = re.search(rf"--{name}:\s*([^;]+);", html)
    return match.group(1).strip() if match else None


def main():
    failures = []
    themes = theme_library.available_themes()
    print(f"=== 0. Thèmes locaux ({theme_library.themes_dir()}) ===")
    print(f"{len(themes)} thèmes · {sum(t.size_bytes for t in themes) / 1024 / 1024:.1f} Mo")
    if len(themes) != 26:
        failures.append(f"{len(themes)} thèmes trouvés au lieu de 26")

    biz = {
        "name": "Jus d'Orange & Cie", "address": "Rue Ibnou Katib, Maârif, Casablanca",
        "city": "Casablanca", "street": "Maârif", "types": ["restaurant"],
        "phone": "+212 522 25 33 44", "rating": 4.6, "reviews": 213,
    }

    print("\n=== 1. Rendu du gabarit restaurant avec les 26 thèmes ===")
    for theme in themes:
        html, shop = create_both_versions(biz, "restaurant", theme=theme.slug)
        problems = check_html(html)
        marker = f'data-theme="{theme.slug}"'
        if marker not in html:
            problems.append("balise de thème absente")
        if f'id="bootswatch-{theme.slug}"' not in html:
            problems.append("style du thème absent")
        if css_var(html, "primary").lower() != theme.primary.lower():
            problems.append(f"--primary={css_var(html, 'primary')} != {theme.primary}")
        if theme.font_family and theme.font_family not in html:
            problems.append(f"police du thème ({theme.font_family}) absente")
        if marker not in shop:
            problems.append("thème différent sur la version e-commerce")
        status = "OK " if not problems else "KO "
        print(f"{status}{theme.slug:11s} {'sombre' if theme.is_dark else 'clair ':6s} "
              f"{len(html):>8,} car. primary={theme.primary:8s} police={theme.font_family or '(métier)':16s} {problems}")
        if problems:
            failures.append(f"{theme.slug}: {problems}")

    print("\n=== 2. Les 8 gabarits × 3 thèmes (clair, sombre, sans thème) ===")
    for slug in ["minty", "darkly", None]:
        label = slug or "aucun"
        for key in TEMPLATES_CONFIG:
            static, shop = create_both_versions(biz, key, theme=slug if slug else "aucun")
            for name, html in (("vitrine", static), ("ecommerce", shop)):
                problems = check_html(html)
                if problems:
                    failures.append(f"{label}/{key}/{name}: {problems}")
                print(f"{'OK ' if not problems else 'KO '}{label:8s} {key:11s} {name:9s} {len(html):>8,} car. {problems}")
            if slug is None:
                if 'id="bootswatch-' in static:
                    failures.append(f"{key}: thème présent alors que 'aucun' demandé")
                if css_var(static, "primary").lower() != TEMPLATES_CONFIG[key]["color"].lower():
                    failures.append(f"{key}: couleur du métier absente sans thème")

    print("\n=== 3. Autres gabarits avec un thème sombre (tokens de surface) ===")
    for key in ["cafe", "salon", "shop", "pharmacy", "bakery", "gym", "default"]:
        for slug in ["darkly", "vapor"]:
            html, _ = create_both_versions(biz, key, theme=slug)
            theme = theme_library.get_theme(slug)
            bad = []
            for var, expected in (("surface", theme.surface), ("ink", theme.ink), ("soft", theme.soft),
                                  ("line", theme.line), ("on-primary", theme.on_primary),
                                  ("primary-light", theme.primary_light)):
                if (css_var(html, var) or "").lower() != expected.lower():
                    bad.append(f"--{var}={css_var(html, var)} != {expected}")
            # plus aucune surface blanche codée en dur
            leftover = re.findall(r"background:\s*#fff\b", html)
            if leftover:
                bad.append(f"{len(leftover)} fond(s) blanc(s) en dur")
            print(f"{'OK ' if not bad else 'KO '}{slug:8s} {key:11s} {bad}")
            if bad:
                failures.append(f"{key}/{slug}: {bad}")

    print("\n=== 4. Tirage aléatoire par commerce ===")
    names = [f"Commerce {i}" for i in range(1, 27)]
    picks = []
    for name in names:
        item = dict(biz, name=name, address=f"{name}, Maârif, Casablanca")
        picked = get_site_theme(item)
        picks.append(picked.slug)
        again = get_site_theme(item)
        if picked.slug != again.slug:
            failures.append(f"{name}: tirage non reproductible ({picked.slug} puis {again.slug})")
    counts = Counter(picks)
    print(f"26 commerces → {len(counts)} thèmes distincts : {dict(list(counts.items())[:6])}...")
    if len(counts) < 12:
        failures.append(f"tirage trop peu varié : {len(counts)} thèmes distincts")
    unthemed = [p for p in picks if not p]
    if unthemed:
        failures.append("certains commerces sans thème")

    print("\n=== 5. Cohérence vitrine / e-commerce et intégrité du CSS embarqué ===")
    sample = theme_library.get_theme("sketchy")
    html, shop = create_both_versions(biz, "restaurant", theme="sketchy")
    css = sample.css()
    for expected in (":root", "--bs-primary", "--bs-body-bg", "grid-template-columns" if False else "@media"):
        if expected not in css:
            failures.append(f"CSS du thème sans '{expected}'")
    if "@charset" in css:
        failures.append("@charset non retiré du CSS embarqué (invaliderait l'@import de la police)")
    if "@import" not in css:
        print("   (sketchy n'importe pas de police ?)", [line[:80] for line in css.splitlines()[:3]])
    injected = len(re.findall(r'id="bootswatch-', shop))
    if injected != 1:
        failures.append(f"{injected} balise(s) de thème dans la version e-commerce")
    print(f"OK  css={len(css):,} car. · vitrine={len(html):,} · e-commerce={len(shop):,} · balise thème unique={injected == 1}")

    print("\n=== RÉSULTAT ===")
    if failures:
        print(f"{len(failures)} problème(s) :")
        for item in failures:
            print(f"  - {item}")
    else:
        print("Tout est vert.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
