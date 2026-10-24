# -*- coding: utf-8 -*-
"""Chiffre les supports avant de les déposer dans le dépôt.

Usage : python3 outils/chiffrer.py DOSSIER_EN_CLAIR [ANNEE]

Chaque fichier cité dans ANNEE/publication.json (source et annexes, hors documents
"clair": true) est lu dans DOSSIER_EN_CLAIR et écrit chiffré dans
ANNEE/coffre/<chemin>.enc2, avec la clé publique du site (outils/cle-publique.pem).
Aucun secret n'est nécessaire : seul le workflow de publication, qui connaît CLE_SITE,
peut déchiffrer. Les fichiers déjà chiffrés à l'identique ne sont pas réécrits.

Format d'un fichier .enc2 : "SIO2", la clé publique X25519 éphémère (32 octets), puis le
contenu chiffré par openssl enc (AES-256-CBC, PBKDF2), avec un mot de passe tiré du secret
partagé entre la clé éphémère et la clé du site.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CLE_PUBLIQUE = RACINE / "outils" / "cle-publique.pem"
EMPREINTES = "empreintes.json"     # dans ANNEE/coffre : empreinte du fichier clair de chaque paquet


def chiffrer(source, cible, dossier):
    eph = dossier / "eph.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "X25519", "-out", str(eph)],
                   check=True, capture_output=True)
    der = subprocess.run(["openssl", "pkey", "-in", str(eph), "-pubout", "-outform", "DER"],
                         check=True, capture_output=True).stdout
    brute = der[-32:]
    partage = subprocess.run(["openssl", "pkeyutl", "-derive", "-inkey", str(eph),
                              "-peerkey", str(CLE_PUBLIQUE)], check=True, capture_output=True).stdout
    mdp = hashlib.sha256(b"sio-paquet|" + partage).hexdigest()
    tmp = dossier / "paquet.bin"
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "100000",
                    "-md", "sha256", "-in", str(source), "-out", str(tmp), "-pass", "env:MDP"],
                   check=True, env={**os.environ, "MDP": mdp})
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(b"SIO2" + brute + tmp.read_bytes())
    eph.unlink()
    tmp.unlink()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    clair = Path(sys.argv[1])
    annee = sys.argv[2] if len(sys.argv) > 2 else "2026-2027"
    manifeste = json.loads((RACINE / annee / "publication.json").read_text(encoding="utf-8"))
    coffre = RACINE / annee / "coffre"
    fichier_empreintes = coffre / EMPREINTES
    empreintes = {}
    if fichier_empreintes.exists():
        empreintes = json.loads(fichier_empreintes.read_text(encoding="utf-8"))
    chemins = set()
    for rubrique in manifeste["rubriques"]:
        for doc in rubrique["documents"]:
            if doc.get("clair"):
                continue
            chemins.add(doc.get("source", doc["fichier"]))
            chemins.update(doc.get("annexes", []))
    dossier = Path(tempfile.mkdtemp(prefix="chiffrer-"))
    try:
        for chemin in sorted(chemins):
            source = clair / chemin
            if not source.exists():
                if (coffre / (chemin + ".enc")).exists() or (coffre / (chemin + ".enc2")).exists():
                    continue          # déjà dans le coffre (ancien document)
                sys.exit(f"fichier introuvable : {source}")
            empreinte = hashlib.sha256(source.read_bytes()).hexdigest()
            cible = coffre / (chemin + ".enc2")
            if empreintes.get(chemin) == empreinte and cible.exists():
                continue
            chiffrer(source, cible, dossier)
            empreintes[chemin] = empreinte
            print("chiffré :", chemin)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    fichier_empreintes.write_text(json.dumps(empreintes, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
