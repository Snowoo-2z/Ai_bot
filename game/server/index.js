// Serveur HTTP + Socket.io pour le monde RP.
// v1: gère les connexions, la position des joueurs et la synchro des skins.
// Architecture pensée pour évoluer vers économie / métiers / caméras plus tard.

const path = require('path');
const http = require('http');
const express = require('express');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*' }
});

app.use(express.static(path.join(__dirname, '..', 'public')));

// --- Monde ---
// Map très simple pour v1: un grand sol carrelé. On étend plus tard.
const WORLD = {
  width: 3000,
  height: 3000,
  tile: 64,
  bg: 0x1f2a3a,        // couleur du sol (sera remplacée par texture plus tard)
  grid: 0x2a3a52       // couleur des lignes de grille (debug)
};

// --- État des joueurs (en mémoire) ---
// Map socketId -> { id, name, x, y, dir, skin, joinedAt }
const players = new Map();

function sanitizeSkin(skin) {
  // Défense côté serveur: valeurs par défaut si le client envoie n'importe quoi.
  const safe = {
    body: typeof skin?.body === 'string' ? skin.body : '#5b9bd5',
    outline: typeof skin?.outline === 'string' ? skin.outline : '#0e1a2b',
    eyeColor: typeof skin?.eyeColor === 'string' ? skin.eyeColor : '#ffffff',
    pupilColor: typeof skin?.pupilColor === 'string' ? skin.pupilColor : '#111111',
    mouthColor: typeof skin?.mouthColor === 'string' ? skin.mouthColor : '#7a2f2f',
    hairStyle: ['none', 'short', 'long', 'ponytail', 'mohawk', 'bun', 'cap', 'hood'].includes(skin?.hairStyle) ? skin.hairStyle : 'none',
    hairColor: typeof skin?.hairColor === 'string' ? skin.hairColor : '#3a2a1a',
    accessory: ['none', 'glasses', 'mask', 'headphones', 'hat', 'crown'].includes(skin?.accessory) ? skin.accessory : 'none',
    accessoryColor: typeof skin?.accessoryColor === 'string' ? skin.accessoryColor : '#ffd54a',
    cheekColor: typeof skin?.cheekColor === 'string' ? skin.cheekColor : '#ff8fa3'
  };
  return safe;
}

function sanitizeName(name) {
  const cleaned = String(name || '').trim().slice(0, 16);
  return cleaned.length ? cleaned : 'Joueur';
}

function broadcastPlayers() {
  const list = [...players.values()].map(p => ({
    id: p.id,
    name: p.name,
    x: p.x, y: p.y, dir: p.dir,
    skin: p.skin
  }));
  io.emit('players:list', list);
}

io.on('connection', (socket) => {
  console.log(`[+] ${socket.id} connected`);

  // Le client envoie "hello" pour rejoindre avec son identité visuelle.
  socket.on('player:join', ({ name, skin } = {}) => {
    const player = {
      id: socket.id,
      name: sanitizeName(name),
      x: Math.floor(WORLD.width / 2),
      y: Math.floor(WORLD.height / 2),
      dir: 'down',
      skin: sanitizeSkin(skin),
      joinedAt: Date.now()
    };
    players.set(socket.id, player);

    // On confirme au nouveau joueur qui il est, et on lui envoie l'état du monde.
    socket.emit('world:hello', {
      you: player,
      world: WORLD,
      players: [...players.values()].filter(p => p.id !== socket.id)
    });

    // Et on annonce aux autres son arrivée.
    socket.broadcast.emit('players:add', player);
    console.log(`[join] ${player.name} (${socket.id}) skin=${player.skin.hairStyle}/${player.skin.accessory}`);
  });

  // Mises à jour de position (fréquentes, 20Hz max côté client).
  socket.on('player:move', ({ x, y, dir } = {}) => {
    const p = players.get(socket.id);
    if (!p) return;

    // Bornes anti-triche: clamp dans la map.
    const nx = Math.max(16, Math.min(WORLD.width - 16, Number(x) || p.x));
    const ny = Math.max(16, Math.min(WORLD.height - 16, Number(y) || p.y));
    const ndir = ['up', 'down', 'left', 'right'].includes(dir) ? dir : p.dir;

    p.x = nx; p.y = ny; p.dir = ndir;

    // Broadcast à tous les autres (le client fait déjà son interpolation locale).
    socket.broadcast.emit('players:move', { id: socket.id, x: nx, y: ny, dir: ndir });
  });

  // Changement de skin en jeu (depuis l'écran de custom).
  socket.on('player:skin', (skin) => {
    const p = players.get(socket.id);
    if (!p) return;
    p.skin = sanitizeSkin(skin);
    io.emit('players:skin', { id: socket.id, skin: p.skin });
  });

  socket.on('disconnect', () => {
    if (players.has(socket.id)) {
      const p = players.get(socket.id);
      players.delete(socket.id);
      io.emit('players:remove', { id: socket.id });
      console.log(`[-] ${p.name} (${socket.id}) disconnected`);
    } else {
      console.log(`[-] ${socket.id} disconnected (no player)`);
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, '0.0.0.0', () => {
  console.log(`🎮 Serveur de jeu démarré sur http://0.0.0.0:${PORT}`);
  console.log(`   Map: ${WORLD.width}x${WORLD.height} | tile=${WORLD.tile}px`);
});
