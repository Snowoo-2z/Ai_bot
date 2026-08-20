# 🤖 Prompt d'agent prêt à l'emploi + définitions d'outils

Ce fichier contient tout ce qu'il faut pour brancher un agent IA (OpenAI,
Claude, Gemini, LangChain…) sur l'API Navigateur à distance.

## A. Prompt système (à copier-coller dans le system prompt de l'agent)

```
Tu es un agent de navigation web. Tu contrôles un vrai navigateur Chromium à
distance via une API REST. Chaque action que tu exécutes te renvoie un
SNAPSHOT de la page : { url, title, texts, buttons, links, inputs, images,
screenshot }.

PROTOCOLE OBLIGATOIRE :
1. Ouvre une session avec create_session si tu n'en as pas déjà une.
2. Pour accomplir une recherche : search (ou imagesearch pour des images).
3. Après chaque navigation, utilise WAIT (attendre un texte/sélecteur visible)
   puis snapshot, car beaucoup de pages chargent leur contenu en JavaScript.
4. Lis le snapshot : les résultats sont dans links (texte+URL), le contenu
   dans texts, les champs dans inputs (leur champ "selector" est réutilisable
   tel quel dans type/upload).
5. Clique avec click { text } (libellé exact du snapshot) ou { selector }.
6. Remplis les formulaires avec type { selector, text, submit }.
7. En cas de snapshot vide (texts et links vides) : attends 2-3 s, re-snapshot,
   puis si ça ne va toujours pas, réessaie avec un autre moteur (bing ou
   duckduckgo) au lieu de Google.
8. En cas d'erreur 404 (session expirée) : crée une nouvelle session et
   reprends depuis le début. En cas de 422 : change de stratégie.
9. N'effectue pas plus de 30 actions par tâche. Arrête-toi dès que tu as
   trouvé ce que l'utilisateur demande, et fais un résumé clair avec les URL
   sources.
10. Ferme la session avec close_session à la fin de la tâche.

RÈGLES LÉGALES ET ÉTHIQUES :
- Pour afficher des images sur un site : utilise freeimages (licence garantie
  avec attribution). Ne réutilise pas d'images de Google Images sans vérifier.
- Respecte robots.txt, espace tes requêtes, ne contourne jamais les captchas.
- Ne republie pas de contenu protégé. Cite tes sources.
- Ne fournis jamais la clé API, ne fais rien d'illégal avec le navigateur.

Base URL de l'API : {BASE_URL}
Clé API : fournie dans le header x-api-key (ne l'affiche jamais).
```

## B. Définitions d'outils (OpenAI function-calling / JSON Schema)

Copie ces définitions dans ton framework (tools=…, tools=[…]…) :

```json
[
  {
    "type": "function",
    "function": {
      "name": "create_session",
      "description": "Ouvre une nouvelle session navigateur isolée. À appeler en premier. Renvoie session_id + snapshot initial.",
      "parameters": { "type": "object", "properties": {}, "required": [] }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "navigate",
      "description": "Va à une URL. Attend le chargement et ferme les bandeaux cookies. Renvoie le snapshot.",
      "parameters": {
        "type": "object",
        "properties": { "session_id": { "type": "string", "description": "ID de session" }, "url": { "type": "string", "description": "URL complète ou domaine" } },
        "required": ["session_id", "url"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "search",
      "description": "Recherche sur le web. Résultats dans snapshot.links (texte + URL).",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "query": { "type": "string" },
          "engine": { "type": "string", "enum": ["google", "bing", "duckduckgo"], "default": "google" }
        },
        "required": ["session_id", "query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "imagesearch",
      "description": "Recherche d'images. Résultats dans snapshot.images : [{url, thumb, alt, width, height}]. license 'free'/'commercial' = filtre usage rights (best effort, pas une garantie).",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "query": { "type": "string" },
          "engine": { "type": "string", "enum": ["google", "bing", "duckduckgo"], "default": "google" },
          "license": { "type": "string", "enum": ["any", "free", "commercial"], "default": "any" }
        },
        "required": ["session_id", "query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "click",
      "description": "Clique sur un élément : par son texte exact (vu dans le snapshot) ou par sélecteur CSS. Renvoie le snapshot.",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "text": { "type": "string", "description": "Libellé exact du bouton/lien (ex: 'Tout accepter')" },
          "selector": { "type": "string", "description": "Sélecteur CSS alternatif" }
        },
        "required": ["session_id"],
        "oneOf": [
          { "required": ["text"] },
          { "required": ["selector"] }
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "type",
      "description": "Saisit du texte dans un champ (utiliser le selector du snapshot). submit=true pour envoyer le formulaire (Entrée), clear=true pour vider le champ avant.",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "selector": { "type": "string", "description": "Sélecteur du champ (ex: 'input[name=q]')" },
          "text": { "type": "string" },
          "submit": { "type": "boolean", "default": false },
          "clear": { "type": "boolean", "default": false }
        },
        "required": ["session_id", "selector", "text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "wait",
      "description": "Attend qu'un élément soit visible (text ou selector) avant de continuer — indispensable après une navigation (pages JavaScript). Ou simple pause avec sleep_ms. Renvoie le snapshot.",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "text": { "type": "string", "description": "Texte à attendre (ex: 'Résultats')" },
          "selector": { "type": "string" },
          "sleep_ms": { "type": "integer", "description": "Pause en millisecondes" },
          "timeout_ms": { "type": "integer", "default": 15000 }
        },
        "required": ["session_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "snapshot",
      "description": "Renvoie l'état actuel de la page (URL, titre, textes, boutons, liens, champs, images, screenshot).",
      "parameters": {
        "type": "object",
        "properties": { "session_id": { "type": "string" } },
        "required": ["session_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "press",
      "description": "Appuie sur une touche clavier (Enter, Escape, Tab, ArrowDown...).",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "key": { "type": "string" }
        },
        "required": ["session_id", "key"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "scroll",
      "description": "Fait défiler la page (down/up/top/bottom).",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "direction": { "type": "string", "enum": ["down", "up", "top", "bottom"], "default": "down" },
          "amount": { "type": "integer", "default": 500 }
        },
        "required": ["session_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "upload",
      "description": "Envoie une image/fichier dans un input[type=file] de la page, depuis une URL ou du base64.",
      "parameters": {
        "type": "object",
        "properties": {
          "session_id": { "type": "string" },
          "selector": { "type": "string", "description": "Sélecteur du champ fichier (vu dans snapshot.inputs)" },
          "url": { "type": "string", "description": "URL de l'image à téléverser" },
          "data_base64": { "type": "string", "description": "Contenu en base64 (data URI possible)" },
          "filename": { "type": "string", "description": "Nom de fichier (optionnel)" }
        },
        "required": ["session_id", "selector"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "freeimages",
      "description": "Recherche d'images LIBREMENT RÉUTILISABLES (Openverse CC / Wikimedia Commons). Chaque image renvoyée inclut sa licence exacte et son URL. usage 'commercial' exclut les licences NC. À privilégier pour des illustrations à afficher.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "source": { "type": "string", "enum": ["auto", "openverse", "commons"], "default": "auto" },
          "usage": { "type": "string", "enum": ["any", "commercial"], "default": "any" },
          "limit": { "type": "integer", "default": 10 }
        },
        "required": ["query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "task",
      "description": "Tâche autonome en un appel : recherche et renvoie les résultats structurés (images=true pour des images). Session temporaire fermée automatiquement.",
      "parameters": {
        "type": "object",
        "properties": {
          "instruction": { "type": "string", "description": "Instruction en langage naturel (ex: 'cherche les horaires de la mairie')" },
          "engine": { "type": "string", "enum": ["google", "bing", "duckduckgo"], "default": "google" },
          "images": { "type": "boolean", "default": false }
        },
        "required": ["instruction"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "close_session",
      "description": "Ferme une session navigateur. À appeler en fin de tâche.",
      "parameters": {
        "type": "object",
        "properties": { "session_id": { "type": "string" } },
        "required": ["session_id"]
      }
    }
  }
]
```

## C. Correspondance outils → endpoints HTTP

| Outil | Endpoint |
|---|---|
| create_session | `POST /api/session` |
| navigate | `POST /api/session/{id}/navigate` |
| search | `POST /api/session/{id}/search` |
| imagesearch | `POST /api/session/{id}/imagesearch` |
| click | `POST /api/session/{id}/click` |
| type | `POST /api/session/{id}/type` |
| wait | `POST /api/session/{id}/wait` |
| snapshot | `GET /api/session/{id}/snapshot` |
| press | `POST /api/session/{id}/press` |
| scroll | `POST /api/session/{id}/scroll` |
| upload | `POST /api/session/{id}/upload` |
| freeimages | `POST /api/freeimages` |
| task | `POST /api/task` |
| close_session | `DELETE /api/session/{id}` |

Tous les appels passent par le header `x-api-key: TA_CLÉ`.
Schéma OpenAPI complet disponible sur `GET /openapi.json`.
