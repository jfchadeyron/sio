# -*- coding: utf-8 -*-
"""Prépare le site : ne déchiffre que les documents dont la date d'ouverture est passée.

Lancé par GitHub Actions chaque jour. La clé de déchiffrement est lue dans la
variable d'environnement CLE_SITE (secret du dépôt). Aucune dépendance externe :
Python 3 et openssl suffisent.
"""
import html
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "_site"
FUSEAU = ZoneInfo("Europe/Paris")
ANNEES = ["2026-2027"]


def dechiffrer(source, cible, cle):
    cible.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                    "-md", "sha256", "-in", str(source), "-out", str(cible), "-pass", "env:CLE_SITE"],
                   check=True, env={**os.environ, "CLE_SITE": cle})


def ouvert(doc, maintenant):
    return datetime.fromisoformat(doc["ouverture"]).replace(tzinfo=FUSEAU) <= maintenant


def publier_annee(annee, cle, maintenant):
    dossier = RACINE / annee
    manifeste = json.loads((dossier / "publication.json").read_text(encoding="utf-8"))
    coffre = dossier / "coffre"
    sortie = SITE / annee

    # Pour chaque fichier publié, on retient la version ouverte la plus récente.
    retenus = {}
    for rubrique in manifeste["rubriques"]:
        for doc in rubrique["documents"]:
            if not ouvert(doc, maintenant):
                continue
            actuel = retenus.get(doc["fichier"])
            if actuel is None or doc["ouverture"] >= actuel["ouverture"]:
                retenus[doc["fichier"]] = doc

    for fichier, doc in retenus.items():
        source = doc.get("source", fichier)
        dechiffrer(coffre / (source + ".enc"), sortie / fichier, cle)
        for annexe in doc.get("annexes", []):
            dechiffrer(coffre / (annexe + ".enc"), sortie / annexe, cle)

    # Page d'accueil de l'année : uniquement les documents ouverts.
    fixes, seances = [], []
    for rubrique in manifeste["rubriques"]:
        vus, liens = set(), []
        for doc in rubrique["documents"]:
            if doc["fichier"] in retenus and doc["fichier"] not in vus:
                vus.add(doc["fichier"])
                liens.append(doc)
        if liens:
            (fixes if rubrique.get("fixe") else seances).append((rubrique, liens))
    blocs = []
    for rubrique, liens in fixes + list(reversed(seances)):
        items = "\n".join(
            f'<li><a href="{html.escape(d["fichier"])}">{html.escape(d["libelle"])}</a></li>'
            for d in liens)
        blocs.append(f'<h2>{html.escape(rubrique["titre"])}</h2>\n<ul>\n{items}\n</ul>')
    if not blocs:
        blocs.append("<p>Aucun document pour le moment.</p>")
    (sortie).mkdir(parents=True, exist_ok=True)
    (sortie / "index.html").write_text(
        gabarit(manifeste["titre"], manifeste.get("presentation", ""), "\n".join(blocs)),
        encoding="utf-8")
    return len(retenus)


def gabarit(titre, presentation, corps):
    sous_titre = f'<p class="sous-titre">{html.escape(presentation)}</p>' if presentation else ""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<style>
body {{ margin: 0 auto; max-width: 760px; padding: 26px 22px 40px; background: #ffffff; color: #1b1b1b;
  font-family: Cambria, Georgia, "Times New Roman", serif; font-size: 17px; line-height: 1.55; }}
.entete {{ display: table; width: 100%; border-bottom: 1px solid #1b1b1b; padding-bottom: 5px;
  font-family: Arial, Helvetica, sans-serif; font-size: 12.5px; color: #3a3a3a; }}
.entete span {{ display: table-cell; }}
.entete .droite {{ text-align: right; }}
h1 {{ font-size: 29px; font-weight: normal; color: #13305a; margin: 26px 0 4px; }}
.sous-titre {{ font-style: italic; color: #4a4a4a; margin: 0 0 18px; padding-bottom: 12px; border-bottom: 3px double #b8c2cc; }}
h2 {{ font-size: 19px; color: #13305a; margin: 28px 0 8px; padding-bottom: 3px; border-bottom: 1px solid #b8c2cc; }}
ul {{ margin: 6px 0 10px; padding-left: 24px; }}
li {{ margin: 5px 0; }}
a {{ color: #13305a; }}
.pied {{ margin-top: 44px; padding-top: 6px; border-top: 1px solid #b8c2cc; font-family: Arial, Helvetica, sans-serif;
  font-size: 12px; color: #6a6a6a; text-align: center; }}
</style>
</head>
<body>
<div class="entete"><span>BTS SIO 1<sup>re</sup> année · Bloc 1</span><span class="droite">Développement web</span></div>
<h1>{html.escape(titre)}</h1>
{sous_titre}
{corps}
<div class="pied">BTS SIO · Bloc 1 · Support et mise à disposition de services informatiques</div>
</body>
</html>
"""


def main():
    cle = os.environ.get("CLE_SITE", "")
    if not cle:
        sys.exit("Le secret CLE_SITE est absent : ajoute-le dans Settings > Secrets and variables > Actions.")
    maintenant = datetime.now(FUSEAU)
    if os.environ.get("DATE_SIMULEE"):          # pour vérifier une publication future
        maintenant = datetime.fromisoformat(os.environ["DATE_SIMULEE"]).replace(tzinfo=FUSEAU)
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    total = 0
    for annee in ANNEES:
        total += publier_annee(annee, cle, maintenant)
    derniere = ANNEES[-1]
    (SITE / "index.html").write_text(
        f'<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={derniere}/"><title>Supports de cours</title></head>'
        f'<body><p><a href="{derniere}/">Supports de cours {derniere}</a></p></body></html>\n',
        encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"{maintenant:%d/%m/%Y %H:%M} : {total} document(s) publié(s).")


if __name__ == "__main__":
    main()
