// Construit l'évaluation en ligne « SQL et PHP » à partir de la banque de questions.
//
// Usage : node outils/construire-quiz.mjs CHEMIN/banque-source.mjs DOSSIER_ENSEIGNANT [DOSSIER_ELEVES]
//
// Produit :
//   DOSSIER_ELEVES/quiz/banque.js       le sujet chiffré, à publier sur le site (sans les réponses) ;
//   DOSSIER_ENSEIGNANT/pilotage-quiz.html  la page du professeur : codes, réponses, clé de lecture des copies.
//
// Chaque lancement tire de nouveaux codes et de nouvelles clés : la page de pilotage et le
// banque.js publié doivent toujours venir du même lancement.
//
// Rien de secret n'est écrit dans le dépôt : la banque en clair et la page de pilotage restent
// chez le professeur. Le sujet publié est chiffré question par question (PBKDF2 + AES-GCM) ;
// chaque question ne s'ouvre qu'avec le code donné en classe.
// Aucune dépendance : Node 20 ou plus récent (WebCrypto intégré).

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const subtle = globalThis.crypto.subtle;
const ITER = 200000;
const ALPHABET = "ACDEFHJKMNPRTUVWXY3479";     // ni O/0, ni I/1/L, ni S/5, ni B/8, ni G/6, ni Z/2
const NTFY = process.env.NTFY_URL || "https://ntfy.sh";   // NTFY_URL : relais de test uniquement
const URL_ELEVES = "https://jfchadeyron.github.io/sio/2026-2027/quiz/";
const EDITIONS = [
  { ed: "g1", label: "Groupe 1" },
  { ed: "g2", label: "Groupe 2" },
  { ed: "rt", label: "Rattrapage" },
  { ed: "es", label: "Essai (répétition)" },
];
const TIERS_TEMPS = 1.33;

const b64 = (buf) => Buffer.from(buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf).toString("base64");
const alea = (n) => globalThis.crypto.getRandomValues(new Uint8Array(n));

function code(n = 6) {
  const out = [];
  while (out.length < n) {
    for (const x of alea(32)) {
      if (x < 242 && out.length < n) out.push(ALPHABET[x % 22]);     // 242 = 11 × 22 : tirage sans biais
    }
  }
  return out.join("");
}

function sujet() {
  const a = "abcdefghijkmnpqrstuvwxyz23456789";
  return "sio-" + Array.from(alea(20), (x) => a[x % 32]).join("");
}

async function cle(motDePasse, sel) {
  const base = await subtle.importKey("raw", new TextEncoder().encode(motDePasse), "PBKDF2", false, ["deriveKey"]);
  return subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: sel, iterations: ITER },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt"]);
}

async function sceller(objet, motDePasse) {
  const sel = alea(16), iv = alea(12);
  const k = await cle(motDePasse, sel);
  const donnees = await subtle.encrypt({ name: "AES-GCM", iv }, k, new TextEncoder().encode(JSON.stringify(objet)));
  return { s: b64(sel), i: b64(iv), d: b64(donnees) };
}

async function main() {
  const [source, dossierProf, dossierEleves = "2026-2027/clair-quiz"] = process.argv.slice(2);
  if (!source || !dossierProf) {
    console.error("Usage : node outils/construire-quiz.mjs banque-source.mjs DOSSIER_ENSEIGNANT [DOSSIER_ELEVES]");
    process.exit(1);
  }
  const banque = await import(pathToFileURL(path.resolve(source)).href);
  const slots = banque.slots;
  slots.forEach((s, i) => { s.seq = i + 1; });
  const ids = new Set(slots.map((s) => s.id));
  if (ids.size !== slots.length) throw new Error("deux thèmes ont le même id");
  for (const s of slots) for (const v of s.variants) {
    if (!(v.ok >= 0 && v.ok < v.o.length)) throw new Error(`bonne réponse hors limites : ${s.id}`);
  }

  const publiques = [], privees = [];
  for (const { ed, label } of EDITIONS) {
    const paire = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveKey"]);
    const pub = await subtle.exportKey("jwk", paire.publicKey);
    const priv = await subtle.exportKey("jwk", paire.privateKey);
    const codes = {
      seance: code(), tiers: code(), fin: code(), correction: code(),
      questions: Object.fromEntries(slots.map((s) => [s.id, code()])),
    };
    const ctrl = sujet(), res = sujet();
    const entete = (mult) => ({
      ed, label, mult, ntfy: NTFY, ctrl, res, pub: { kty: pub.kty, crv: pub.crv, x: pub.x, y: pub.y },
      slots: slots.map((s) => ({ id: s.id, seq: s.seq, tp: s.tp, tag: s.tag, duree: s.duree })),
    });
    const q = {};
    for (const s of slots) {
      q[s.id] = await sceller({
        id: s.id, tag: s.tag,
        variants: s.variants.map((v) => ({ q: v.q, code: v.code || "", table: !!v.table, oc: !!v.oc, o: v.o })),
      }, codes.questions[s.id]);
    }
    const corr = {
      slots: Object.fromEntries(slots.map((s) => [s.id, {
        theme: s.theme, tp: s.tp, axe: s.axe, ref: s.ref,
        ok: s.variants.map((v) => v.ok), ex: s.variants.map((v) => v.ex || ""),
      }])),
    };
    publiques.push({
      a: await sceller(entete(1), codes.seance),
      b: await sceller(entete(TIERS_TEMPS), codes.tiers),
      f: await sceller({ fin: ed }, codes.fin),
      q,
      c: await sceller(corr, codes.correction),
    });
    privees.push({ ed, label, codes, ctrl, res, priv, pub });
    console.log(`édition ${label} : prête`);
  }

  // Le sujet publié : l'ordre des éditions est mélangé pour ne rien révéler.
  const melange = publiques.map((p, i) => [alea(1)[0], p]).sort((x, y) => x[0] - y[0]).map((x) => x[1]);
  const js = "/* Évaluation SQL et PHP : sujet chiffré. Chaque question s'ouvre avec le code donné en classe. */\n"
    + "window.BANQUE_QUIZ = " + JSON.stringify({ v: 1, iter: ITER, editions: melange }) + ";\n";
  await mkdir(path.join(dossierEleves, "quiz"), { recursive: true });
  await writeFile(path.join(dossierEleves, "quiz", "banque.js"), js, "utf8");

  // La page du professeur.
  const ici = path.dirname(fileURLToPath(import.meta.url));
  const modele = await readFile(path.join(ici, "pilotage-quiz-modele.html"), "utf8");
  const donnees = {
    titre: banque.titre, url: URL_ELEVES, ntfy: NTFY, tiers: TIERS_TEMPS, alphabet: ALPHABET,
    editions: privees,
    slots: slots.map((s) => ({
      id: s.id, seq: s.seq, tp: s.tp, tag: s.tag, duree: s.duree, theme: s.theme, axe: s.axe, ref: s.ref,
      variants: s.variants.map((v) => ({ q: v.q, code: v.code || "", table: !!v.table, oc: !!v.oc, o: v.o, ok: v.ok, ex: v.ex || "" })),
    })),
  };
  const json = JSON.stringify(donnees).replace(/</g, "\\u003c");
  const page = modele.replace("/*__DONNEES__*/null", json);
  if (page === modele) throw new Error("repère /*__DONNEES__*/ introuvable dans le modèle");
  await mkdir(dossierProf, { recursive: true });
  await writeFile(path.join(dossierProf, "pilotage-quiz.html"), page, "utf8");
  console.log(`sujet : ${path.join(dossierEleves, "quiz", "banque.js")}`);
  console.log(`pilotage : ${path.join(dossierProf, "pilotage-quiz.html")}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
