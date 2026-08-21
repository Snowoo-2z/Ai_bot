# 🧭 Navigateur IA à distance — Documentation complète d'intégration

Cette API permet à **n'importe quel agent IA** de contrôler un vrai navigateur
Chromium à distance : rechercher, naviguer, lire les pages, cliquer, remplir des
formulaires, envoyer/recevoir des images… et de **voir** ce que la page affiche
à chaque étape.

> **Principe fondamental** : chaque appel d'action renvoie un **snapshot** de la
> page (URL, titre, textes, boutons, liens, champs, images). L'agent lit le
> snapshot, décide de l'action suivante, recommence. C'est une boucle
> « yeux → cerveau → mains ».
>
> **Schéma OpenAPI machine-readable** : `GET /openapi.json` (généré par FastAPI)
> — la plupart des frameworks d'agents (OpenAI tools, LangChain, etc.) peuvent
> l'importer directement.

---

## 1. Démarrage rapide

**Base URL** : `https://TON-SERVEUR` (Render, VPS, ou `http://localhost:8000` en local)

**Authentification** : header `x-api-key: TA_CLÉ` sur **tous** les endpoints `/api/*`.
Clé définie par la variable d'env `API_KEY` (défaut local : `change-moi`).

```bash
# 1. Ouvrir une session navigateur
curl -X POST https://TON-SERVEUR/api/session \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" -d '{}'
# → { "ok": true, "session_id": "abc123def0", "snapshot": { ... } }

# 2. Faire une recherche
curl -X POST https://TON-SERVEUR/api/session/abc123def0/search \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" \
  -d '{"query": "météo à La Rochelle", "engine": "google"}'
# → { "ok": true, "session_id": "abc123def0", "action": "search", "snapshot": { ... } }

# 3. Cliquer sur un résultat vu dans le snapshot
curl -X POST https://TON-SERVEUR/api/session/abc123def0/click \
  -H "x-api-key: TA_CLÉ" -H "Content-Type: application/json" \
  -d '{"text": "La Rochelle — Météo France"}'

# 4. Fermer la session quand c'est fini
curl -X DELETE https://TON-SERVEUR/api/session/abc123def0 \
  -H "x-api-key: TA_CLÉ"
```

Une session = un onglet isolé (cookies, historique de navigation, session de
login). Les sessions inactives sont fermées automatiquement après
`SESSION_IDLE_TIMEOUT_MIN` minutes (défaut : 15).

---

## 2. Endpoints — vue d'ensemble

### 2.1 Sessions

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/api/session` | Ouvre une session → `{ session_id, snapshot }` |
| `GET` | `/api/sessions` | Liste des sessions actives (URL, titre, âge, inactivité) |
| `GET` | `/api/session/{id}` | Snapshot complet **avec screenshot** |
| `GET` | `/api/session/{id}/snapshot` | Snapshot complet **avec screenshot** |
| `GET` | `/api/session/{id}/screenshot?full=1` | Capture PNG (binaire). `full=1` = page entière |
| `GET` | `/api/session/{id}/image?url=…&as_base64=1` | Télécharge une image via la session (binaire, ou JSON base64) |
| `DELETE` | `/api/session/{id}` | Ferme la session |

### 2.2 Actions (chacune renvoie le snapshot après coup)

| Méthode | Route | Body |
|---|---|---|
| `POST` | `/api/session/{id}/navigate` | `{ "url": "https://…" }` |
| `POST` | `/api/session/{id}/search` | `{ "query": "…", "engine": "google"\|"duckduckgo"\|"bing" }` |
| `POST` | `/api/session/{id}/imagesearch` | `{ "query": "…", "engine": "…", "license": "any"\|"free"\|"commercial" }` + `?with_data=1` pour les vignettes en base64 |
| `POST` | `/api/session/{id}/click` | `{ "selector": "a.btn" }` **ou** `{ "text": "Acheter" }` |
| `POST` | `/api/session/{id}/type` | `{ "selector": "input[placeholder=…]", "text": "…", "submit": false, "clear": false }` |
| `POST` | `/api/session/{id}/upload` | `{ "selector": "input[type=file]", "url": "https://…" }` ou `{ "selector": "…", "data_base64": "…", "filename": "x.png" }` |
| `POST` | `/api/session/{id}/press` | `{ "key": "Enter" }` |
| `POST` | `/api/session/{id}/wait` | `{ "selector": ".result" }` ou `{ "text": "Résultats" }` ou `{ "sleep_ms": 2000 }` (+ `"timeout_ms": 15000`) |
| `POST` | `/api/session/{id}/scroll` | `{ "direction": "down"\|"up"\|"top"\|"bottom", "amount": 500 }` |
| `POST` | `/api/session/{id}/back` | — |
| `POST` | `/api/session/{id}/forward` | — |
| `POST` | `/api/session/{id}/reload` | — |
| `POST` | `/api/session/{id}/action` | `{ "action": "navigate", "url": "…", "screenshot": true }` — version générique (1 seul endpoint pour tout) |

### 2.3 Tâches & images libres (sans session)

| Méthode | Route | Body | Description |
|---|---|---|---|
| `POST` | `/api/task` | `{ "instruction": "cherche les horaires de la mairie", "engine": "google" }` | Recherche autonome : session temporaire, résultats structurés `{ title, url }` (10 max), puis fermeture |
| `POST` | `/api/task` | `{ "instruction": "cherche des photos de voiliers", "images": true }` | Idem en mode images → `images: [{ url, thumb, … }]` |
| `POST` | `/api/freeimages` | `{ "query": "…", "source": "openverse"\|"commons"\|"auto", "usage": "any"\|"commercial", "limit": 10 }` | Images **librement réutilisables** avec leur licence exacte (voir §7) |

### 2.4 Divers

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/health` | État du service + nombre de sessions |
| `GET` | `/openapi.json` | Schéma OpenAPI complet (importable par les agents) |
| `GET` | `/` | Console de test visuelle |

---

## 3. Le snapshot — ce que l'agent « voit »

Chaque réponse d'action contient le champ `snapshot` :

```json
{
  "url": "https://www.google.com/search?q=meteo+larochelle",
  "title": "meteo larochelle - Recherche Google",
  "texts": [
    "Météo La Rochelle 14 jours - Météo France",
    "La Rochelle (17000) - Prévisions météo à 14 jours..."
  ],
  "buttons": [ { "text": "Tout accepter" } ],
  "links": [
    { "text": "Météo La Rochelle 14 jours", "href": "https://meteofrance.com/la-rochelle" },
    { "text": "Météo marine La Rochelle",    "href": "https://www.windguru.cz/..." }
  ],
  "inputs": [
    { "type": "text", "placeholder": "Rechercher", "selector": "input[placeholder=\"Rechercher\"]", "value": "" }
  ],
  "images": [
    { "url": "https://exemple.com/photo.jpg", "thumb": "https://exemple.com/photo_t.jpg",
      "alt": "Voilier en mer", "width": 800, "height": 600 }
  ],
  "screenshot": "data:image/png;base64,...",
  "taken_at": 1755774000.123
}
```

### Règles d'interprétation pour l'agent

1. **`texts`** : blocs de texte visibles (paragraphes, titres, cellules) — la
   « lecture » de la page. Tronqués à 3000 caractères, max 40.
2. **`buttons`** : tout ce qui est cliquable de type bouton. Cliquer avec
   `{ "text": "…" }` (le libellé exact du snapshot).
3. **`links`** : liens avec texte + URL. Ouvrir avec `navigate` ou cliquer par texte.
4. **`inputs`** : champs de saisie. **Le `selector` est prêt à être réutilisé**
   dans `/type` (et `/upload` pour `type: "file"`).
5. **`images`** : images visibles de la page (≥ 80 px) ; sur Google/Bing Images
   ce sont les résultats de recherche avec leur URL directe.
6. **`screenshot`** : présent quand l'action a été appelée avec `screenshot: true`
   (ou sur les endpoints snapshot/session). C'est l'aperçu visuel.
7. **`url` / `title`** : état courant de la navigation.

> ⚠️ **Limites du snapshot** : il reflète ce qui est **rendu au moment T**.
> Les pages JavaScript chargent souvent le contenu après coup → utilise
> l'action `wait` puis re-demande un snapshot.

---

## 4. Détail des actions

### `navigate`
```json
{ "url": "https://example.com" }
```
`http://` est ajouté automatiquement si absent. Ferme les bandeaux cookies
courants (best effort).

### `search`
```json
{ "query": "horaires mairie Soubise", "engine": "google" }
```
Moteurs : `google`, `bing`, `duckduckgo`. Ouvre la page de résultats → le
snapshot contient les résultats dans `links` (texte + URL) et `texts`.

### `imagesearch`
```json
{ "query": "voiliers", "engine": "google", "license": "any" }
```
- `license`: `"any"` (défaut) | `"free"` | `"commercial"` — filtre « usage
  rights » du moteur (**best effort**, pas une garantie légale). DuckDuckGo :
  non supporté.
- Les résultats sont dans `snapshot.images` avec l'**URL directe** de l'image.
- `?with_data=1` : les 10 premières vignettes sont jointes en base64
  (`image.data`) — l'agent reçoit le contenu sans second appel.

### `click`
```json
{ "text": "Tout accepter" }        // ou
{ "selector": "#submit-btn" }
```
Fournir **soit** `text` (libellé vu dans le snapshot) **soit** `selector`
(selecteur CSS). Le clic attend la visibilité, scrolle vers l'élément.

### `type`
```json
{ "selector": "input[name=q]", "text": "météo", "submit": true, "clear": false }
```
- `clear: true` : remplace tout le contenu du champ.
- `submit: true` : appuie sur Entrée après la saisie (envoi du formulaire).

### `upload` — envoyer une image/fichier dans un champ
```json
{ "selector": "input[type=file]", "url": "https://exemple.com/photo.png" }
// ou en base64 :
{ "selector": "input[type=file]", "data_base64": "data:image/png;base64,....", "filename": "photo.png" }
```
Le fichier est téléchargé (via la session, donc mêmes droits que la page),
écrit dans un fichier temporaire, puis déposé dans le champ. Le champ `file`
est visible dans `snapshot.inputs` même s'il est masqué.

### `press`
```json
{ "key": "Enter" }
```
Touches Playwright : `Enter`, `Escape`, `Tab`, `ArrowDown`, `ArrowUp`,
`Backspace`, `F5`, `Control+A`…

### `wait` — LA clé pour les pages dynamiques
```json
{ "text": "Résultats", "timeout_ms": 15000 }
{ "selector": ".result-item" }
{ "sleep_ms": 2000 }
```
Attend qu'un élément soit visible (puis renvoie le snapshot), ou fait une
simple pause. **Pattern recommandé** : `navigate` → `wait {text}` →
snapshot → décision.

### `scroll`
```json
{ "direction": "down", "amount": 500 }
```
`direction`: `down`, `up`, `top`, `bottom`.

### `back` / `forward` / `reload`
Body vide (`{}`).

---

## 5. Tâche autonome `/api/task`

Pour une recherche en **un seul appel** (sans gérer la session) :

```json
{ "instruction": "cherche les horaires de la mairie de Soubise", "engine": "google" }
```
```json
{ "instruction": "cherche des photos de couchers de soleil", "images": true, "engine": "bing" }
```

Réponse (mode texte) :
```json
{
  "ok": true, "instruction": "...", "query": "horaires de la mairie de Soubise",
  "engine": "google",
  "results": [
    { "title": "Mairie de Soubise — horaires", "url": "https://..." },
    ...
  ],
  "snapshot": { ... }
}
```

L'instruction peut être en langage naturel (« cherche… », « trouve… »,
« search for… ») ou une requête brute. La session temporaire est fermée à la fin.

---

## 6. Gestion des erreurs

| Code HTTP | Cas | Réponse |
|---|---|---|
| `401` | Clé API invalide | `{ "detail": "Clé API invalide..." }` |
| `404` | Session inconnue (fermée/expirée) | `{ "detail": "Session 'xxx' introuvable..." }` → en créer une nouvelle |
| `422` | Action impossible (élément absent, timeout, paramètre invalide) | `{ "detail": "message explicite" }` |
| `429` | Trop de sessions simultanées | `{ "detail": "Nombre maximum de sessions atteint..." }` |
| `500` | Erreur interne | `{ "detail": "Erreur interne..." }` |
| `502` | Téléchargement d'image échoué (`/image`) | `{ "detail": "Téléchargement échoué : HTTP 404" }` |

**Politique de retry recommandée pour l'agent** :
- `401` → vérifier la clé, ne pas réessayer.
- `404` → créer une nouvelle session (l'ancienne a expiré), reprendre depuis le début.
- `422` avec « Élément introuvable » → attendre (`sleep_ms` 1000–3000) et
  re-snapshot 1 à 2 fois avant de changer de stratégie (la page charge peut-être).
- `429` → attendre quelques secondes, ou fermer des sessions inutilisées.

---

## 7. Images libres de droit — `/api/freeimages`

Pour des illustrations affichables sans risque, ne pas scraper Google Images :
utiliser des sources dont la licence est **connue et renvoyée** :

```json
{ "query": "voilier en mer", "source": "auto", "usage": "commercial", "limit": 10 }
```

Réponse :
```json
{
  "ok": true, "source": "openverse", "usage": "commercial",
  "images": [
    { "title": "Voilier au coucher du soleil",
      "url": "https://images.openverse.org/.../full.jpg",
      "thumbnail": "https://images.openverse.org/.../thumb.jpg",
      "license": "CC BY-SA 4.0",
      "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
      "creator": "Jean Dupont",
      "source": "flickr" }
  ]
}
```

- `source`: `openverse` (toutes licences Creative Commons) | `commons`
  (Wikimedia Commons) | `auto` (→ openverse).
- `usage`: `any` | `commercial` (exclut les licences NC — non commerciales).
- **Attribution** : si la licence l'exige (CC BY, CC BY-SA…), afficher
  « Photo par {creator} · {license} » avec un lien vers `license_url`.
- ⚖️ Les filtres `license` de `/imagesearch` (Google/Bing) sont un best effort ;
  seules Openverse/Commons garantissent la licence.

---

## 8. Bonnes pratiques pour l'agent

1. **Boucle type** : `create_session` → `navigate`/`search` → `wait` (élément
   attendu) → snapshot → analyser → `click`/`type`/… → snapshot → … → `DELETE session`.
2. **Une session par tâche** (ou par conversation), pas une par action : les
   cookies et l'historique se conservent dans la session.
3. **Toujours `wait` après une navigation** vers un site JavaScript, puis
   re-snapshot. Ne jamais supposer qu'une page est prête.
4. **Fallback moteur** : si Google renvoie un captcha ou un snapshot vide
   (`texts`/`links` vides), réessayer avec `bing` ou `duckduckgo`.
5. **Limiter le nombre d'actions** par tâche (ex. 30) pour éviter les boucles
   infinies ; définir un objectif clair (« je m'arrête quand la réponse contient X »).
6. **Vérifier l'URL et le titre** à chaque snapshot : un clic peut avoir
   ouvert une popup ou une redirection inattendue.
7. **Respecter les sites** : espace raisonnable entre les requêtes, respecter
   `robots.txt`, ne pas contourner les captchas, ne pas republier du contenu
   protégé. La responsabilité de l'usage reste à l'intégrateur.
8. **Images** : pour des illustrations, préférer `/api/freeimages` (licence
   garantie) ; pour la recherche générale, `imagesearch` + attribution quand
   elle s'applique.

---

## 9. Exemple de code — agent minimal en Python

```python
import requests

BASE = "https://TON-SERVEUR"
KEY = "TA_CLÉ"
H = {"x-api-key": KEY, "Content-Type": "application/json"}

def snapshot(sid, action, **params):
    r = requests.post(f"{BASE}/api/session/{sid}/{action}", headers=H, json=params)
    r.raise_for_status()
    return r.json()["snapshot"]

# 1. Session
sid = requests.post(f"{BASE}/api/session", headers=H, json={}).json()["session_id"]
try:
    # 2. Recherche
    s = snapshot(sid, "search", query="prix moyen maison Soubise", engine="google")
    print("Titre:", s["title"], "| URL:", s["url"])
    for l in s["links"][:5]:
        print("-", l["text"], "→", l["href"])

    # 3. Ouvrir le premier résultat
    if s["links"]:
        snapshot(sid, "navigate", url=s["links"][0]["href"])
        snapshot(sid, "wait", text="prix")          # page dynamique
        s = snapshot(sid, "snapshot")
        print("Contenu:", s["texts"][:3])
finally:
    requests.delete(f"{BASE}/api/session/{sid}", headers=H)
```

---

## 10. Déploiement & configuration

### Variables d'environnement

| Variable | Description | Défaut |
|---|---|---|
| `API_KEY` | Clé API exigée dans `x-api-key` (repli : `MY_SECRET_KEY`) | `change-moi` |
| `HEADLESS` | `0` pour voir le navigateur (debug) | `1` |
| `SESSION_IDLE_TIMEOUT_MIN` | Fermeture auto des sessions inactives (min) | `15` |
| `MAX_SESSIONS` | Nombre max de sessions simultanées | `20` |
| `NAV_TIMEOUT_MS` | Timeout de navigation (ms) | `30000` |
| `BROWSER_UA` | User-Agent du navigateur | Chrome 138 |
| `BROWSER_PROXY` | Proxy pour les sessions, ex. `http://user:pass@host:port` (IP résidentielle pour éviter les blocages captcha sur les gros sites) | vide |

### Render
1. Dashboard → **New +** → **Blueprint** → ce repo → `render.yaml` appliqué.
2. Définir `API_KEY` (Settings → Environment). Ajouter `BROWSER_PROXY` si besoin.
3. Health check : `/health`.

### Local
```bash
pip install -r requirements.txt
playwright install chromium
export API_KEY="ma-cle"
uvicorn main:app --reload   # http://localhost:8000
```

---

## 11. Limites connues (à connaître avant d'intégrer)

- **IP datacenter** : sur Render/AWS/GCP, certains sites (Google, Cloudflare,
  Amazon, réseaux sociaux…) peuvent afficher un captcha ou un 403. Solution :
  `BROWSER_PROXY` avec un proxy résidentiel.
- **Pages 100 % JavaScript** : contenu chargé après coup → utiliser `wait` +
  re-snapshot.
- **Sites avec login** : la session garde les cookies — l'agent peut se
  connecter une fois (via `type` + `click`) puis continuer dans la même session.
- **Screenshot** : l'aperçu est un PNG (pas de video temps réel).
- **Pas de garantie légale** sur les filtres de licence des moteurs (voir §7).
