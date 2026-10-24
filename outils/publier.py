# -*- coding: utf-8 -*-
"""Prépare le site : ne déchiffre que les documents dont la date d'ouverture est passée.

Lancé par GitHub Actions plusieurs fois par jour (voir .github/workflows/publication.yml).

Pour chaque document cité dans ANNEE/publication.json :
- "clair": true          : copié tel quel depuis ANNEE/clair/<chemin> ;
- ANNEE/coffre/<chemin>.enc2 : chiffré avec la clé publique du site (outils/cle-publique.pem),
                           déchiffré ici avec la clé privée tirée du secret CLE_SITE ;
- ANNEE/coffre/<chemin>.enc  : ancien format, chiffré directement avec CLE_SITE.

Le secret CLE_SITE (Settings > Secrets and variables > Actions) ne sert qu'ici : la clé
privée en est tirée à chaque passage et n'est jamais écrite dans le dépôt. La clé publique
correspondante est publiée à la racine du site (cle-publique.pem) : elle permet de chiffrer
de nouveaux documents sans connaître le secret (outils/chiffrer.py).

Le fichier ANNEE/assets/publie.json liste les documents en ligne : les pages s'en servent
pour griser les liens vers les documents pas encore ouverts.

Pour vérifier une publication future : DATE_SIMULEE=2026-11-09T08:00 python3 outils/publier.py
Aucune dépendance externe : Python 3 et openssl suffisent.
"""
import base64
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "_site"
FUSEAU = ZoneInfo("Europe/Paris")
ANNEES = ["2026-2027"]

PKCS8_X25519 = bytes.fromhex("302e020100300506032b656e04220420")
SPKI_X25519 = bytes.fromhex("302a300506032b656e032100")
ENTETE2 = b"SIO2"


def pem(etiquette, der):
    corps = base64.encodebytes(der).decode("ascii")
    return f"-----BEGIN {etiquette}-----\n{corps}-----END {etiquette}-----\n"


class Cles:
    """Clé privée X25519 tirée du secret CLE_SITE (fichier temporaire, supprimé à la fin)."""

    def __init__(self, cle_site):
        self.cle_site = cle_site
        self.dossier = Path(tempfile.mkdtemp(prefix="cles-"))
        graine = hashlib.sha256(b"sio-x25519|" + cle_site.encode("utf-8")).digest()
        self.privee = self.dossier / "privee.pem"
        self.privee.write_text(pem("PRIVATE KEY", PKCS8_X25519 + graine), encoding="ascii")
        os.chmod(self.privee, 0o600)
        res = subprocess.run(["openssl", "pkey", "-in", str(self.privee), "-pubout"],
                             check=True, capture_output=True, text=True)
        self.publique = res.stdout

    def fermer(self):
        shutil.rmtree(self.dossier, ignore_errors=True)


def dechiffrer_ancien(source, cible, cles):
    cible.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                    "-md", "sha256", "-in", str(source), "-out", str(cible), "-pass", "env:CLE_SITE"],
                   check=True, env={**os.environ, "CLE_SITE": cles.cle_site})


def dechiffrer2(source, cible, cles):
    donnees = source.read_bytes()
    if not donnees.startswith(ENTETE2) or len(donnees) < 36:
        raise RuntimeError(f"format inattendu : {source}")
    ephemere = cles.dossier / "ephemere.pem"
    ephemere.write_text(pem("PUBLIC KEY", SPKI_X25519 + donnees[4:36]), encoding="ascii")
    partage = subprocess.run(["openssl", "pkeyutl", "-derive", "-inkey", str(cles.privee),
                              "-peerkey", str(ephemere)], check=True, capture_output=True).stdout
    mdp = hashlib.sha256(b"sio-paquet|" + partage).hexdigest()
    chiffre = cles.dossier / "paquet.bin"
    chiffre.write_bytes(donnees[36:])
    cible.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                          "-md", "sha256", "-in", str(chiffre), "-out", str(cible), "-pass", "env:MDP"],
                         env={**os.environ, "MDP": mdp}, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"déchiffrement impossible de {source} : la clé CLE_SITE a-t-elle changé ?")


def sortir(coffre, chemin, cible, cles):
    if (coffre / (chemin + ".enc2")).exists():
        dechiffrer2(coffre / (chemin + ".enc2"), cible, cles)
    else:
        dechiffrer_ancien(coffre / (chemin + ".enc"), cible, cles)


def copier(source, cible):
    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, cible)


def ouvert(doc, maintenant):
    return datetime.fromisoformat(doc["ouverture"]).replace(tzinfo=FUSEAU) <= maintenant


def publier_annee(annee, cles, maintenant):
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
        if doc.get("clair"):
            copier(dossier / "clair" / source, sortie / fichier)
            for annexe in doc.get("annexes", []):
                copier(dossier / "clair" / annexe, sortie / annexe)
            continue
        sortir(coffre, source, sortie / fichier, cles)
        for annexe in doc.get("annexes", []):
            sortir(coffre, annexe, sortie / annexe, cles)

    # Liste des documents en ligne, lue par les pages (assets/app.js).
    (sortie / "assets").mkdir(parents=True, exist_ok=True)
    (sortie / "assets" / "publie.json").write_text(
        json.dumps({"documents": sorted(retenus)}, ensure_ascii=False) + "\n", encoding="utf-8")

    # Page d'accueil : fournie par le manifeste (document index.html), sinon fabriquée ici.
    if "index.html" not in retenus:
        (sortie / "index.html").write_text(accueil_simple(manifeste, retenus), encoding="utf-8")
    return len(retenus)


def accueil_simple(manifeste, retenus):
    fixes, seances = [], []
    for rubrique in manifeste["rubriques"]:
        if rubrique.get("cache"):
            continue
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
    titre = html.escape(manifeste["titre"])
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<style>
body {{ margin: 0 auto; max-width: 760px; padding: 26px 22px 40px; background: #fff; color: #1d2530;
  font-family: "Segoe UI", Arial, sans-serif; font-size: 16px; line-height: 1.55; }}
h1 {{ color: #1f3a5f; border-bottom: 2px solid #1f3a5f; padding-bottom: 8px; }}
h2 {{ color: #1f3a5f; font-size: 19px; border-bottom: 1px solid #d3d9e0; padding-bottom: 3px; }}
a {{ color: #1a4f8b; }}
</style>
</head>
<body>
<h1>{titre}</h1>
{chr(10).join(blocs)}
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
    cles = Cles(cle)
    try:
        total = 0
        for annee in ANNEES:
            total += publier_annee(annee, cles, maintenant)
        (SITE / "cle-publique.pem").write_text(cles.publique, encoding="ascii")
    finally:
        cles.fermer()
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
