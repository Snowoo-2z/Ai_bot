# 🤖 Ai_bot — Bot Arena (FastAPI + Playwright + Render)

Bot qui se connecte à [arena.ai](https://arena.ai) via Playwright, sauvegarde la session, puis expose une API FastAPI pour envoyer des prompts. Déployable sur [Render](https://render.com) depuis ce repo GitHub (runtime **Docker**).

> ⚠️ **Pourquoi Docker ?** Sur l'environnement natif Render, le build tourne sans droits root, donc
> `playwright install --with-deps chromium` échoue avec `su: Authentication failure`.
> Avec un `Dockerfile`, le build est root : on installe Chromium **et** ses dépendances système proprement.

## Structure

```
Ai_bot/
├── main.py            # API FastAPI (/chat, /health, frontend statique)
├── bot_logic.py       # Login arena.ai + envoi de prompt (Playwright)
├── requirements.txt   # Dépendances Python (versions épinglées)
├── Dockerfile         # Image Python 3.13 + Chromium + dépendances système
├── render.yaml        # Déploiement automatique Render (runtime Docker)
├── static/
│   └── index.html     # Frontend avec champ clé API
└── .gitignore
```

## Variables d'environnement (définies dans le dashboard Render)

| Variable        | Description                          | Défaut  |
|-----------------|--------------------------------------|---------|
| `ARENA_EMAIL`   | Ton email de connexion arena.ai      | —       |
| `ARENA_PASSWORD`| Ton mot de passe arena.ai            | —       |
| `MY_SECRET_KEY` | Clé API requise par le frontend      | —       |
| `SESSION_JSON`  | Session Playwright persistée en variable d'env (survit aux redémarrages Render) | — |
| `SESSION_FILE`  | Chemin du fichier de session (par défaut `session.json`) | `session.json` |
| `SERVICE_NAME`  | Nom affiché dans l'erreur "trop de demandes" | `xHigh` |
| `MAX_ATTEMPTS`  | Relances via le lien direct chat avant d'abandonner | `5` |
| `RETRY_DELAY_SECONDS` | Pause entre deux tentatives | `10` |
| `AUTO_RETRY_MINUTES` | Délai avant ré-essai automatique après "trop de demandes" | `3` |
| `MAX_AUTO_RETRIES` | Nombre max de ré-essais automatiques | `1` |
| `HUMANIZE` | Comportement "humain" (frappe + pauses aléatoires) | `1` (on) |
| `TYPE_DELAY_MIN` / `TYPE_DELAY_MAX` | Délai (ms) entre chaque caractère tapé | `15` / `55` |
| `THINK_MIN` / `THINK_MAX` | Pause (s) avant de commencer à taper | `1.0` / `3.0` |
| `RESPONSE_TIMEOUT` | Temps max (s) d'attente de la réponse | `60` |
| `TYPO_RATE` | Proba d'une faute de frappe (corrigée aussitôt) | `0.03` |
| `BURST_MIN` / `BURST_MAX` | Nombre de caractères par "rafale" de frappe | `2` / `6` |

## Déploiement sur Render

Le service existant peut être basculé en runtime Docker sans être recréé :

1. Render Dashboard → ton service → **Settings** → section **Build** → **Source** → **Edit**
2. Garde le repo `Snowoo-2z/Ai_bot` et la branche `main`, choisis **Runtime : Docker**
3. **Deploy** (les variables d'environnement restent inchangées)

Ou via **Blueprint** : Dashboard → **New +** → **Blueprint** → choisis ce repo → `render.yaml` est appliqué automatiquement.

## Lancement local

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload
```

Ou avec Docker :

```bash
docker build -t ai-bot .
docker run -p 8000:10000 --env-file .env ai-bot
```

Puis ouvre http://localhost:8000 et entre ta clé API (`MY_SECRET_KEY`).

## Endpoints

- `GET  /health` → vérifie que le serveur tourne
- `POST /chat` → header `x-api-key` obligatoire, body JSON :
  `{ "prompt": "...", "system_prompt": "..." }`.
  Ajoute la demande à la **file d'attente** et répond immédiatement avec
  `{ "job_id", "status", "position" }`.
- `GET  /status/{job_id}` → état actuel d'une demande :
  `{ "status": "queued"|"processing"|"done"|"error", "position", "result", "error" }`.
- `GET  /queue` → aperçu de la file (nombre en attente + place de chacun).

Les demandes sont traitées **une par une dans l'ordre d'arrivée (FIFO)**.
Le frontend envoie la demande puis **poll** `/status/{job_id}` pour afficher la place
dans la file et le résultat final.

### Comportement face aux reCAPTCHA

Quand un reCAPTCHA (ou un overlay qui intercepte les clics) bloque l'envoi, le bot :

1. détecte le blocage (iframe recaptcha/hcaptcha, texte de vérification humaine,
   ou timeout de clic type *"intercepts pointer events"*),
2. **relance via le lien direct** `https://arena.ai/direct` (nouveau navigateur, nouvelle page),
3. réessaie jusqu'à `MAX_ATTEMPTS` fois (pause de `RETRY_DELAY_SECONDS` entre chaque),
4. après le dernier échec, renvoie l'erreur :
   `Trop de demandes sur xHigh pour le moment. Nous réessayerons d'ici quelques minutes automatiquement.`
   et **passe à la demande suivante** de la file.

La demande échouée est **remise en file automatiquement** après `AUTO_RETRY_MINUTES`
(au maximum `MAX_AUTO_RETRIES` fois).

### 💡 Éviter les reCAPTCHA : persister la session (important sur Render)

Le disque de Render est **éphémère** : `session.json` disparaît à chaque redéploiement/redémarrage,
donc le bot doit **se reconnecter à chaque fois** → c'est ce qui déclenche le reCAPTCHA.

Pour éviter ça :

1. Lance le bot une fois, il se connecte et affiche dans les logs une ligne :
   `💡 SESSION_JSON={...}`
2. Copie cette valeur dans une variable d'environnement `SESSION_JSON` (Dashboard Render →
   ton service → Environment).
3. Au redémarrage, le bot réutilise cette session et **saute la connexion** (donc pas de reCAPTCHA).

La session expirera quand même un jour ; le bot se reconnectera alors automatiquement.

### 🎭 Pourquoi les reCAPTCHA apparaissent si souvent (et comment les réduire)

Le **premier facteur**, c'est l'**IP du serveur**. Les serveurs Render tournent sur des IP de
**datacenter** (AWS/GCP), que Google/reCAPTCHA marquent d'un mauvais "score de confiance" :
résultat, le captcha apparaît même pour de vrais humains qui passent par là.

Pour réduire fortement les captchas (sans rien contourner) :

1. **Faire tourner le bot chez toi** (sur ta connexion internet = IP résidentielle) — c'est LE
   gros levier. Le projet se lance en local : `pip install -r requirements.txt && playwright install chromium`
   puis `uvicorn main:app`. Tu peux l'exposer à ton téléphone avec un tunnel type `cloudflared` ou `ngrok`.
2. **Persister la session** (`SESSION_JSON`) pour éviter de te reconnecter sans arrêt (voir plus haut).
3. **Espacer les demandes** et garder `HUMANIZE=1` : le bot tape le texte **par rafales** avec
   **fautes de frappe corrigées**, fait des pauses aléatoires, **déplace la souris en trajectoires
   courbes** (arcs, accélération/décélération, correction de visée avant clic, micro-mouvements
   pendant l'attente), scrolle la page comme s'il lisait, et attend la réponse sans timing
   robotique. Ça évite de **déclencher** la protection, sans jamais la contourner.
4. (Optionnel) Un **proxy résidentiel** (payant) si tu tiens à rester hébergé sur Render.

⚠️ Ne committe jamais `session.json` ni tes identifiants (déjà dans le `.gitignore`).
