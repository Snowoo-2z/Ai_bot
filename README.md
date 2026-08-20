# 🧭 Navigateur IA à distance — API de contrôle de navigateur

Une **API qui pilote un vrai navigateur Chromium à distance** : ton autre site
(ou une IA) envoie des instructions — navigation, recherche web, clic, saisie,
défilement… — et l'API renvoie **ce que la page affiche** : textes visibles,
boutons, liens, champs de saisie, URL, titre et capture d'écran.

C'est un "browser as a service" : le site appelant décide de l'action suivante
en fonction du snapshot renvoyé (boucle agent), ou utilise l'endpoint
`/api/task` pour une recherche autonome.

> Remplace l'ancien bot arena.ai (Playwright + file d'attente) : plus aucune
> connexion à arena.ai, plus de captcha, plus de file d'attente.

## Comment ça marche

```
Ton site ──(x-api-key)──▶ POST /api/session          → session_id
Ton site ──▶ POST /api/session/{id}/search {query}   → le navigateur cherche sur Google
Ton site ◀── { snapshot : url, title, texts, buttons, links, inputs, screenshot }
Ton site ──▶ POST /api/session/{id}/click {text}     → clic sur le bouton/lien
Ton site ◀── { snapshot }                            → nouvelle page, on recommence
```

Chaque session est un **onglet isolé** (contexte Chromium séparé : cookies,
stockage, etc.). Plusieurs sessions peuvent tourner en parallèle. Les sessions
inactives sont fermées automatiquement après `SESSION_IDLE_TIMEOUT_MIN`
minutes (défaut : 15).

## Structure

```
Ai_bot/
├── main.py          # API FastAPI (sessions, actions, tâches, console)
├── browser_api.py   # Gestionnaire de navigateur + actions Playwright + snapshot
├── requirements.txt
├── Dockerfile       # Python 3.13 + Chromium (installé avec ses dépendances)
├── render.yaml      # Déploiement Render (runtime Docker)
└── static/
    └── index.html   # Console de test (navigateur visuel)
```

## Variables d'environnement

| Variable                  | Description                                 | Défaut          |
|---------------------------|---------------------------------------------|-----------------|
| `API_KEY`                 | Clé API exigée dans le header `x-api-key` (repli : `MY_SECRET_KEY`) | `change-moi` |
| `HEADLESS`                | `0` pour voir le navigateur (debug local)   | `1`             |
| `SESSION_IDLE_TIMEOUT_MIN`| Fermeture auto des sessions inactives (min) | `15`            |
| `MAX_SESSIONS`            | Nombre max de sessions simultanées          | `20`            |
| `NAV_TIMEOUT_MS`          | Timeout de navigation (ms)                  | `30000`         |
| `BROWSER_UA`              | User-Agent du navigateur                    | Chrome 138      |

## Endpoints

Tous les endpoints `/api/*` exigent le header `x-api-key: TA_CLÉ`.
Le CORS est ouvert (ta console peut l'appeler depuis n'importe quel domaine).

### Sessions

| Méthode | Route                          | Description |
|---------|--------------------------------|-------------|
| POST    | `/api/session`                 | Ouvre une nouvelle session navigateur → `{ session_id, snapshot }` |
| GET     | `/api/sessions`                | Liste des sessions actives |
| GET     | `/api/session/{id}`            | Snapshot complet (avec screenshot) |
| GET     | `/api/session/{id}/snapshot`   | Snapshot complet (avec screenshot) |
| GET     | `/api/session/{id}/screenshot` | Capture d'écran PNG (`?full=1` = page entière) |
| DELETE  | `/api/session/{id}`            | Ferme la session |

### Actions

Chaque action renvoie le **snapshot après coup**.

| Méthode | Route                              | Body (JSON) |
|---------|------------------------------------|-------------|
| POST    | `/api/session/{id}/navigate`       | `{ "url": "https://…" }` |
| POST    | `/api/session/{id}/search`         | `{ "query": "…", "engine": "google"\|"duckduckgo"\|"bing" }` |
| POST    | `/api/session/{id}/click`          | `{ "selector": "a.btn" }` **ou** `{ "text": "Acheter" }` |
| POST    | `/api/session/{id}/type`           | `{ "selector": "input[placeholder=…]", "text": "…", "submit": false, "clear": false }` |
| POST    | `/api/session/{id}/press`          | `{ "key": "Enter" }` (Escape, Tab, ArrowDown…) |
| POST    | `/api/session/{id}/scroll`         | `{ "direction": "down"\|"up"\|"top"\|"bottom", "amount": 500 }` |
| POST    | `/api/session/{id}/back`           | — |
| POST    | `/api/session/{id}/forward`        | — |
| POST    | `/api/session/{id}/reload`         | — |
| POST    | `/api/session/{id}/action`         | `{ "action": "navigate", "url": "…", "screenshot": true }` — version générique |

### Tâche autonome

| Méthode | Route      | Body | Description |
|---------|------------|------|-------------|
| POST    | `/api/task`| `{ "instruction": "cherche les meilleurs restaurants à Paris", "engine": "google" }` | Ouvre une session temporaire, fait la recherche, renvoie les 10 premiers résultats `{ title, url }` + le snapshot, puis ferme la session. |

### Snapshot (ce que l'API renvoie)

```json
{
  "url": "https://www.google.com/search?q=…",
  "title": "…",
  "texts": ["blocs de texte visibles…"],
  "buttons": [{ "text": "Tout accepter" }],
  "links":   [{ "text": "Titre du lien", "href": "https://…" }],
  "inputs":  [{ "type": "text", "placeholder": "Rechercher…", "selector": "input[placeholder=\"Rechercher…\"]", "value": "" }],
  "screenshot": "data:image/png;base64,…"   // seulement si demandé
}
```

Le champ `selector` des inputs est prêt à être réutilisé dans `/type`.

## Exemples

```bash
# 1. Ouvrir une session
curl -X POST https://TON-SERVEUR/api/session \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" -d '{}'

# 2. Rechercher
curl -X POST https://TON-SERVEUR/api/session/abc123/search \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" \
  -d '{"query": "météo à La Rochelle", "engine": "google"}'

# 3. Cliquer sur un bouton vu dans le snapshot
curl -X POST https://TON-SERVEUR/api/session/abc123/click \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" \
  -d '{"text": "Tout accepter"}'

# 4. Tâche autonome : recherche + résultats structurés
curl -X POST https://TON-SERVEUR/api/task \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" \
  -d '{"instruction": "cherche les horaires de la mairie de Soubise"}'
```

## Lancement local

```bash
pip install -r requirements.txt
playwright install chromium
export API_KEY="ma-cle"
uvicorn main:app --reload
```

Puis ouvre http://localhost:8000 : la console de test permet d'ouvrir une
session, naviguer, chercher, cliquer sur les boutons du snapshot, etc.

## Déploiement sur Render

1. Render Dashboard → **New +** → **Blueprint** → choisis ce repo →
   `render.yaml` est appliqué (runtime Docker, Chromium installé dans l'image).
2. Définis la variable `API_KEY` dans le service (Settings → Environment).
3. Le health check `/health` confirme que le service tourne.

> ⚠️ Ne définis pas `API_KEY` à `change-moi` en production : l'API contrôle un
> vrai navigateur, elle doit rester privée.
