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

| Variable        | Description                          |
|-----------------|--------------------------------------|
| `ARENA_EMAIL`   | Ton email de connexion arena.ai      |
| `ARENA_PASSWORD`| Ton mot de passe arena.ai            |
| `MY_SECRET_KEY` | Clé API requise par le frontend      |

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
  `{ "prompt": "...", "system_prompt": "..." }`

Une seule requête `/chat` est traitée à la fois (verrou global → 429 si occupé).

⚠️ Ne committe jamais `session.json` ni tes identifiants (déjà dans le `.gitignore`).
