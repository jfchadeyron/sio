# -*- coding: utf-8 -*-
"""Chiffre les supports avant de les déposer dans le dépôt.

Usage : CLE_SITE=... python3 outils/chiffrer.py DOSSIER_EN_CLAIR [ANNEE]
Chaque fichier cité dans ANNEE/publication.json (source et annexes) est lu dans
DOSSIER_EN_CLAIR et écrit chiffré dans ANNEE/coffre/<chemin>.enc.
Les documents marqués "clair": true sont ignorés : ils sont publiés depuis ANNEE/clair/.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def main():
    if "CLE_SITE" not in os.environ:
        sys.exit("Variable CLE_SITE absente.")
    clair = Path(sys.argv[1])
    annee = sys.argv[2] if len(sys.argv) > 2 else "2026-2027"
    manifeste = json.loads((RACINE / annee / "publication.json").read_text(encoding="utf-8"))
    chemins = set()
    for rubrique in manifeste["rubriques"]:
        for doc in rubrique["documents"]:
            if doc.get("clair"):
                continue
            chemins.add(doc.get("source", doc["fichier"]))
            chemins.update(doc.get("annexes", []))
    for chemin in sorted(chemins):
        cible = RACINE / annee / "coffre" / (chemin + ".enc")
        cible.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "200000",
                        "-md", "sha256", "-in", str(clair / chemin), "-out", str(cible),
                        "-pass", "env:CLE_SITE"], check=True)
        print("chiffré :", chemin)


if __name__ == "__main__":
    main()
