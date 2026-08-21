# 🌍 CubeWorld — RP multijoueur top-down (v1)

> **Un jeu web multijoueur dans lequel les joueurs vivent librement dans un village : économie, métiers, propriétés, surveillance, vols, etc. L'inspiration : les grands RP YouTubers sur Minecraft, mais en 2D top-down, en navigateur, sans installation.**
>
> Cette v1 pose la fondation technique : **personnalisation de cube + déplacement multijoueur en temps réel**. Tout le reste (économie, métiers, propriétés) viendra se brancher dessus.

---

## 🎯 Vision long terme (le « pourquoi »)

L'objectif est de faire un **phénomène** : un jeu dont on parle au quotidien. Pour ça, le gameplay repose sur la **liberté totale** dans un cadre de rôle-play :

- 🪙 Une **économie** (plusieurs monnaies ?) avec échanges, salaires, taxes
- 🏠 Des **propriétés** (maisons, commerces) que les joueurs achètent, louent, revendent
- 👮 Des **métiers** (policier, voleur, vendeur, médecin, mécanicien…)
- 🎥 Des **systèmes de surveillance** (caméras à la Verisure) que les joueurs installent eux-mêmes et que d'autres peuvent monitorer
- 🚨 Du **vol**, des **enquêtes**, des **procès RP**
- 💬 Du **chat textuel** au-dessus des persos
- 🗺️ Un **village → une ville** qui évolue avec ses habitants

> Note : tout est techniquement possible avec la stack actuelle. Les v1+ consistent à ajouter des champs au modèle `Player` et des nouveaux types d'événements Socket.io.

---

## ✅ Ce qui est livré (v1)

| Fonctionnalité | Statut |
|---|---|
| Serveur Node.js + Express + Socket.io | ✅ |
| Client Phaser 3 (vectoriel, zéro asset) | ✅ |
| Map top-down 3000×3000 avec sol carrelé | ✅ |
| Déplacement ZQSD / flèches + normalisation diagonale | ✅ |
| Caméra qui suit le joueur + interpolation des autres | ✅ |
| Customizer de cube complet (corps, yeux, bouche, joues, cheveux 8 styles, accessoires 6) | ✅ |
| Synchro temps réel des positions (throttle 20Hz) | ✅ |
| Synchro temps réel des skins (mise à jour live en jeu) | ✅ |
| UI : compteur de joueurs en ligne + aide contrôles | ✅ |
| Anti-triche côté serveur (sanitisation couleurs / styles, clamp de la position) | ✅ |
| Bouton « personnaliser » accessible en jeu | ✅ |
| Bouton « 🎲 Aléatoire » pour tester vite | ✅ |

---

## 🧱 Stack technique (et pourquoi)

| Choix | Raison |
|---|---|
| **Node.js + Express** | Léger, parfait pour servir HTTP + WebSocket dans le même process |
| **Socket.io** | Reconnexion automatique, fallbacks, très simple pour broadcaster l'état du monde |
| **Phaser 3** (CDN) | Moteur 2D web le plus populaire, `RenderTexture` permet de dessiner des avatars en vectoriel sans assets |
| **JavaScript vanilla côté client** | Pas de build step à maintenir pour la v1, déploiement trivial (Vercel, Render, Railway) |
| **Pas de base de données pour v1** | L'état est en mémoire — c'est OK pour prototyper. À passer en Redis/Postgres quand on aura > 100 joueurs ou des données persistantes (propriétés, banques…) |

### Pourquoi Phaser plutôt que Kaboom/PixiJS/Three.js ?
- Phaser a un **système de scènes** propre (`Boot → Customizer → World`)
- Il gère nativement les `Graphics` + `RenderTexture` (on dessine nos cubes en quelques lignes)
- Compatible avec le `RESIZE` mode (s'adapte à toutes les tailles d'écran)
- CDN stable, pas de bundler

---

## 📁 Structure du projet

```
Ai_bot/
├── README.md                  ← (le bot Arena original)
├── main.py, bot_logic.py      ← (bot Arena — ne pas toucher)
├── static/                    ← (front du bot — ne pas toucher)
├── Dockerfile, render.yaml    ← (deploy bot)
├── requirements.txt
└── game/                      ← 🆕 LE JEU
    ├── package.json
    ├── README.md              ← (ce fichier)
    ├── .gitignore
    ├── server/
    │   └── index.js           ← Serveur Express + Socket.io
    └── public/
        ├── index.html         ← Page d'accueil (charge Phaser + game.js)
        └── game.js            ← Tout le client (scènes, customizer, input, rendu)
```

> ⚠️ Le bot Arena (`main.py`, `bot_logic.py`, etc.) est **indépendant** du jeu. On les garde tous les deux dans le même repo pour faciliter le déploiement, mais ils ne partagent aucun code.

---

## 🚀 Lancer en local

```bash
cd game
npm install
npm start
# → http://localhost:3000
```

Pour tester en multijoueur : ouvrir 2 onglets (ou 1 onglet + 1 fenêtre privée).

### Variables d'environnement (optionnel pour v1)

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `3000` | Port HTTP |

---

## ☁️ Déploiement

### Vercel (recommandé pour la v1)
⚠️ Vercel n'est **pas idéal** pour Socket.io car les fonctions serverless ne maintiennent pas de connexion WebSocket longue. Ça peut marcher en mode `polling` mais c'est lent.

**Options qui marchent vraiment :**
- **Render** (gratuit, simple, le repo a déjà un `Dockerfile` pour le bot) → utiliser un second service Render pour le jeu
- **Railway** (gratuit jusqu'à un certain point, supporte les WebSocket)
- **Fly.io** (gratuit, parfait pour ce use case)
- **Un VPS** (Hetzner, OVH) si on veut contrôler tout

### Render (le plus simple)
1. Créer un nouveau service Web sur Render
2. Connecter ce repo, brancher sur `arena/01a0244a-ai-bot` (ou `main` après merge)
3. **Root Directory** : `game`
4. **Build Command** : `npm install`
5. **Start Command** : `npm start`
6. **Runtime** : Node (pas Docker)
7. Ajouter une variable `PORT=10000` (Render l'exige)
8. Déployer

---

## 🧠 Architecture (comprendre pour continuer)

### Modèle de données (côté serveur)

```js
// players : Map<socketId, Player>
{
  id: socketId,
  name: string,          // 16 char max, sanitisé
  x: number, y: number,  // position top-down
  dir: 'up'|'down'|'left'|'right',
  skin: {
    body, outline, eyeColor, pupilColor, mouthColor,
    hairStyle, hairColor,
    accessory, accessoryColor,
    cheekColor
  },
  joinedAt: number
}
```

### Événements Socket.io

**Client → Serveur :**

| Event | Payload | Rôle |
|---|---|---|
| `player:join` | `{ name, skin }` | Se présenter au serveur. Une fois par session. |
| `player:move` | `{ x, y, dir }` | Update de position (throttle 20Hz côté client) |
| `player:skin` | `skin` | Update du skin (depuis le customizer) |

**Serveur → Client :**

| Event | Payload | Rôle |
|---|---|---|
| `world:hello` | `{ you, world, players[] }` | Réponse au `join` |
| `players:add` | `player` | Quelqu'un vient de rejoindre |
| `players:list` | `players[]` | Sync d'autorité (toutes les N secondes, futur) |
| `players:move` | `{ id, x, y, dir }` | Quelqu'un a bougé |
| `players:skin` | `{ id, skin }` | Quelqu'un a changé de skin |
| `players:remove` | `{ id }` | Quelqu'un s'est déconnecté |

> **Important** : le client **ne** se fie **jamais** à sa propre position pour l'affichage des autres. Il envoie sa position, le serveur la valide (clamp), puis broadcast aux autres. Chaque client fait sa propre interpolation locale.

### Phases du client (scenes)

1. **`BootScene`** : affiche brièvement « CONNEXION… », puis lance le customizer
2. **`CustomizerScene`** : UI de personnalisation + aperçu live
3. **`WorldScene`** : le jeu à proprement parler

Transition `World → Customizer` : on garde l'identité (`myName`, `mySkin`) et on émet un nouveau `player:join` quand on revient. C'est volontaire (simple). Plus tard, on pourra juste mettre à jour le skin sans re-join.

---

## 🛠️ Guide d'extension pour une IA qui reprend

### Pour ajouter un nouveau champ au skin (ex. : `nose`)
1. Ajouter la valeur par défaut dans `DEFAULT_SKIN` (client) et `sanitizeSkin` (serveur)
2. Ajouter le rendu dans `drawCubeAvatar` (client)
3. Ajouter un picker dans `CustomizerScene` (couleur ou style)
4. Tester avec 2 onglets

### Pour ajouter un nouveau type d'événement (ex. : chat)
1. Côté serveur : ajouter le handler dans `io.on('connection', ...)` avec sanitisation
2. Côté client : émettre via `socket.emit('chat:message', ...)` et écouter via `socket.on('chat:message', ...)`
3. Afficher au-dessus du perso via un `Phaser.GameObjects.Text` qu'on repositionne à chaque `update()`

### Pour ajouter une feature « monde » (ex. : bâtiment, shop, banque)
1. Étendre `WORLD` dans le serveur (liste de bâtiments avec position, type, propriétaire)
2. Envoyer cette liste dans le `world:hello`
3. Dessiner les bâtiments dans `WorldScene.create()` avec `this.add.rectangle(...)`
4. Implémenter l'interaction : zone de proximité (`Phaser.Geom.Circle`) → touche `E` → UI

### Pour ajouter l'économie
- Ajouter `coins: 0` au modèle `Player`
- Ajouter `shop: { items: [...] }` au `WORLD`
- Émettre `player:earn` / `player:spend` côté serveur avec **toujours** validation serveur
- Afficher le solde dans l'UI (coin en haut à droite)

### Pour ajouter le système de propriétés
- Créer une `Map<propertyId, Property>` côté serveur
- Événements : `property:buy`, `property:sell`, `property:enter`
- Côté client : dessiner les bâtiments comme « à vendre » / « owned by Alice » selon l'état

### Pour ajouter les caméras de surveillance (le « système Verisure »)
- Une caméra = un objet `Camera` côté serveur avec `{ ownerId, position, direction, range, recording: bool }`
- Le propriétaire peut la placer (UI sur la map), l'orienter
- Le flux vidéo = en v1, on affiche juste un **cercle de vision** (Phaser.Graphics) à l'écran du propriétaire
- Plus tard : faire des mini-cartes des flux (un onglet par caméra)

### Pour ajouter les métiers (policier, voleur…)
- Ajouter `job: 'none'|'police'|'thief'|'...'` au `Player`
- Actions contextuelles selon le métier (le policier a accès au menu « amende », le voleur a « crocheter »…)
- Toujours valider côté serveur

---

## 🧪 Tests manuels à faire avant chaque release

- [ ] Ouvrir 2 onglets côte à côte, vérifier qu'on se voit
- [ ] Bouger en diagonale (pas de saccade)
- [ ] Marcher vers le bord (clamp, on ne sort pas)
- [ ] Changer de skin en jeu → l'autre onglet voit le changement
- [ ] Déconnecter un onglet → l'autre voit le joueur disparaître
- [ ] Recharger la page → on revient avec son dernier skin (en mémoire, pas persisté pour la v1)

---

## 🐛 Limitations connues (assumées pour v1)

- **Pas de persistance** : les joueurs sont en RAM, redémarrer le serveur = tout le monde est déconnecté
- **Pas d'authentification** : n'importe qui prend n'importe quel pseudo (ajouter OAuth + pseudo unique plus tard)
- **Pas de chat** : à ajouter
- **Pas de bâtiments** : la map est vide à part le sol
- **Pas de zones** : la map est ouverte, pas de bâtiments, pas de collisions
- **Bots Arena** : on a remarqué que l'environnement Arena ne semble pas afficher correctement le serveur WebSocket (le port 3000 n'est pas exposé dans le preview). C'est pour ça qu'on déploie sur Vercel/Render/Railway.

---

## 📋 Roadmap suggérée (par ordre de valeur)

1. **Chat textuel** au-dessus des persos (1-2h)
2. **Compteur de pièces** + shop NPC (3-4h)
3. **Bâtiments du village** : mairie, banque, commissariat, habitation (4-6h)
4. **Inventaire + items** (drop, pickup, give) (4h)
5. **Métiers** (police, voleur, vendeur) avec permissions serveur (6-8h)
6. **Propriétés** (achat, vente, location) (8-10h)
7. **Système de surveillance** (caméras) (10-15h)
8. **Persistance** (Redis/Postgres) (4-6h)
9. **Auth** (Discord OAuth recommandé) (3-4h)
10. **Mobile** (Phaser touch controls) (4h)

---

## 📜 Licence & contribution

Ce projet est un side-project personnel inspiré des grands RP communautaires. Contributions bienvenues : ouvrir une PR avec une description claire.

Pour toute question : voir le `git log` pour l'historique des décisions.
