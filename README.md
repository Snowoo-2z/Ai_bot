# 🤖 Ai_bot — Bot Arena (FastAPI + Playwright + Render)

Bot qui se connecte à [arena.ai](https://arena.ai) via Playwright, sauvegarde la session, puis expose une API FastAPI pour envoyer des prompts. Déployable sur [Render](https://render.com) depuis ce repo GitHub.

## Structure

```
Ai_bot/
├── main.py            # API FastAPI (/chat, /health, frontend statique)
├── bot_logic.py       # Login arena.ai + envoi de prompt (Playwright)
├── requirements.txt
├── render.yaml        # Déploiement automatique Render
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

## Lancement local

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload
```

Puis ouvre http://localhost:8000 et entre ta clé API (`MY_SECRET_KEY`).

## Endpoints

- `GET  /health` → vérifie que le serveur tourne
- `POST /chat` → header `x-api-key` obligatoire, body JSON :
  `{ "prompt": "...", "system_prompt": "..." }`

Une seule requête `/chat` est traitée à la fois (verrou global → 429 si occupé).

⚠️ Ne committe jamais `session.json` ni tes identifiants (déjà dans le `.gitignore`).
