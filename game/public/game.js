/* =====================================================================
   CubeWorld — jeu RP top-down multijoueur (v1)
   - Personnalisation de cube (corps, yeux, bouche, joues, cheveux, accessoire)
   - Déplacement en ligne droite (Z/Q/S/D ou flèches)
   - Rendu vectoriel Phaser (aucun asset externe)
   - Synchro temps réel via Socket.io
   ===================================================================== */

// --- Skin par défaut (utilisé dans le customizer au premier chargement) ---
const DEFAULT_SKIN = {
  body: '#5b9bd5',
  outline: '#0e1a2b',
  eyeColor: '#ffffff',
  pupilColor: '#111111',
  mouthColor: '#7a2f2f',
  hairStyle: 'short',
  hairColor: '#3a2a1a',
  accessory: 'none',
  accessoryColor: '#ffd54a',
  cheekColor: '#ff8fa3'
};

const HAIR_STYLES = ['none', 'short', 'long', 'ponytail', 'mohawk', 'bun', 'cap', 'hood'];
const ACCESSORIES = ['none', 'glasses', 'mask', 'headphones', 'hat', 'crown'];

// --- Connexion au serveur ---
const socket = io({ transports: ['websocket', 'polling'] });

let mySkin = { ...DEFAULT_SKIN };
let myName = '';
let myPlayer = null;        // données serveur du joueur local
let world = { width: 3000, height: 3000, tile: 64, bg: 0x1f2a3a, grid: 0x2a3a52 };

const remotePlayers = new Map(); // id -> { container, x, y, dir, name, skin }

// =====================================================================
// RENDU D'UN CUBE PERSONNALISÉ
// On dessine le perso dans un RenderTexture, c'est rapide et ça permet
// d'afficher un aperçu live dans le customizer.
// =====================================================================

/**
 * Dessine un cube-personnage dans la RenderTexture `rt`.
 * Le perso fait 48px de large, dessiné centré.
 * @param {Phaser.GameObjects.RenderTexture} rt
 * @param {object} skin
 */
function drawCubeAvatar(rt, skin) {
  const ctx = rt;

  // Paramètres géométriques
  const cx = 24, cy = 24;          // centre du cube
  const bodyW = 32, bodyH = 36;    // taille du corps
  const top = cy - bodyH / 2;
  const left = cx - bodyW / 2;
  const right = cx + bodyW / 2;
  const bottom = cy + bodyH / 2;

  // 1) Ombre au sol (ellipse)
  ctx.fill(0x000000, 0.25);
  ctx.fillEllipse(cx, bottom + 2, bodyW * 0.9, 6);

  // 2) Capuche / Hood (derrière la tête, en premier pour être partiellement cachée)
  if (skin.hairStyle === 'hood') {
    fillRoundRect(ctx, left - 2, top - 2, bodyW + 4, bodyH + 4, 8, skin.hairColor);
    strokeRoundRect(ctx, left - 2, top - 2, bodyW + 4, bodyH + 4, 8, skin.outline, 2);
  }

  // 3) Corps (cube arrondi = la "tête" en vue top-down frontale)
  fillRoundRect(ctx, left, top, bodyW, bodyH, 6, skin.body);
  strokeRoundRect(ctx, left, top, bodyW, bodyH, 6, skin.outline, 2);

  // 4) Joues (petits ronds rosés)
  ctx.fill(skin.cheekColor, 0.55);
  ctx.fillCircle(left + 7, cy + 4, 2.2);
  ctx.fillCircle(right - 7, cy + 4, 2.2);

  // 5) Yeux (blancs + pupilles)
  const eyeY = cy - 3;
  const eyeOffsetX = 6;
  ctx.fill(skin.eyeColor);
  ctx.fillCircle(left + eyeOffsetX + 3, eyeY, 3.2);
  ctx.fillCircle(right - eyeOffsetX - 3, eyeY, 3.2);
  // pupilles
  ctx.fill(skin.pupilColor);
  ctx.fillCircle(left + eyeOffsetX + 3.5, eyeY, 1.4);
  ctx.fillCircle(right - eyeOffsetX - 2.5, eyeY, 1.4);
  // reflet
  ctx.fill(0xffffff);
  ctx.fillCircle(left + eyeOffsetX + 4, eyeY - 0.8, 0.7);
  ctx.fillCircle(right - eyeOffsetX - 2, eyeY - 0.8, 0.7);

  // 6) Bouche
  ctx.fill(skin.mouthColor);
  ctx.fillRoundedRect(cx - 3, cy + 5, 6, 2, 1);

  // 7) Cheveux
  drawHair(ctx, skin, left, top, right, bottom, bodyW, bodyH, cx, cy);

  // 8) Accessoire (devant les cheveux)
  drawAccessory(ctx, skin, left, top, right, bodyW, bodyH, cx, cy);
}

function drawHair(ctx, skin, left, top, right, bottom, w, h, cx, cy) {
  const style = skin.hairStyle;
  if (style === 'none') return;

  switch (style) {
    case 'short': {
      // Mèche courte au-dessus
      fillRoundRect(ctx, left - 1, top - 2, w + 2, 10, 4, skin.hairColor);
      strokeRoundRect(ctx, left - 1, top - 2, w + 2, 10, 4, skin.outline, 2);
      break;
    }
    case 'long': {
      // Cheveux longs qui descendent sur les côtés
      fillRoundRect(ctx, left - 2, top - 2, w + 4, h * 0.6, 6, skin.hairColor);
      strokeRoundRect(ctx, left - 2, top - 2, w + 4, h * 0.6, 6, skin.outline, 2);
      break;
    }
    case 'ponytail': {
      // Base courte + queue derrière
      fillRoundRect(ctx, left - 1, top - 2, w + 2, 9, 4, skin.hairColor);
      strokeRoundRect(ctx, left - 1, top - 2, w + 2, 9, 4, skin.outline, 2);
      // queue à droite
      fillRoundRect(ctx, right - 1, top + 4, 7, 14, 3, skin.hairColor);
      strokeRoundRect(ctx, right - 1, top + 4, 7, 14, 3, skin.outline, 2);
      break;
    }
    case 'mohawk': {
      // Crête centrale
      fillRoundRect(ctx, cx - 4, top - 4, 8, 14, 3, skin.hairColor);
      strokeRoundRect(ctx, cx - 4, top - 4, 8, 14, 3, skin.outline, 2);
      break;
    }
    case 'bun': {
      // Chignon au-dessus
      ctx.fill(skin.hairColor);
      ctx.fillCircle(cx, top - 2, 6);
      strokeCircle(ctx, cx, top - 2, 6, skin.outline, 2);
      // base
      fillRoundRect(ctx, left - 1, top - 1, w + 2, 8, 3, skin.hairColor);
      strokeRoundRect(ctx, left - 1, top - 1, w + 2, 8, 3, skin.outline, 2);
      break;
    }
    case 'cap': {
      // Casquette (visière vers la droite)
      fillRoundRect(ctx, left - 1, top - 2, w + 2, 8, 4, skin.hairColor);
      strokeRoundRect(ctx, left - 1, top - 2, w + 2, 8, 4, skin.outline, 2);
      // visière
      fillRoundRect(ctx, right - 1, top + 4, 10, 3, 2, skin.hairColor);
      strokeRoundRect(ctx, right - 1, top + 4, 10, 3, 2, skin.outline, 2);
      break;
    }
    case 'hood':
      // déjà dessiné en arrière-plan, rien à ajouter ici
      break;
  }
}

function drawAccessory(ctx, skin, left, top, right, w, h, cx, cy) {
  const acc = skin.accessory;
  if (acc === 'none') return;

  switch (acc) {
    case 'glasses': {
      // deux ronds + pont
      ctx.lineStyle(1.5, hexToInt(skin.accessoryColor), 1);
      ctx.strokeCircle(left + 6, cy - 3, 4);
      ctx.strokeCircle(right - 6, cy - 3, 4);
      ctx.beginPath();
      ctx.moveTo(left + 10, cy - 3);
      ctx.lineTo(right - 10, cy - 3);
      ctx.strokePath();
      break;
    }
    case 'mask': {
      // Masque chirurgical couvrant la bouche
      fillRoundRect(ctx, cx - 10, cy + 4, 20, 8, 2, skin.accessoryColor);
      strokeRoundRect(ctx, cx - 10, cy + 4, 20, 8, 2, skin.outline, 1);
      // attaches
      ctx.lineStyle(1, hexToInt(skin.outline), 1);
      ctx.beginPath();
      ctx.moveTo(cx - 10, cy + 6); ctx.lineTo(left, cy + 4);
      ctx.moveTo(cx + 10, cy + 6); ctx.lineTo(right, cy + 4);
      ctx.strokePath();
      break;
    }
    case 'headphones': {
      // Arceau
      ctx.lineStyle(3, hexToInt(skin.accessoryColor), 1);
      ctx.beginPath();
      ctx.arc(cx, cy - 2, 14, Phaser.Math.DegToRad(200), Phaser.Math.DegToRad(340), false);
      ctx.strokePath();
      // écouteurs
      ctx.fill(skin.accessoryColor);
      ctx.fillCircle(left, cy - 2, 4);
      ctx.fillCircle(right, cy - 2, 4);
      strokeCircle(ctx, left, cy - 2, 4, skin.outline, 1);
      strokeCircle(ctx, right, cy - 2, 4, skin.outline, 1);
      break;
    }
    case 'hat': {
      // Chapeau haut-de-forme
      fillRoundRect(ctx, cx - 10, top - 8, 20, 6, 2, skin.accessoryColor);
      strokeRoundRect(ctx, cx - 10, top - 8, 20, 6, 2, skin.outline, 1);
      fillRoundRect(ctx, cx - 6, top - 18, 12, 12, 2, skin.accessoryColor);
      strokeRoundRect(ctx, cx - 6, top - 18, 12, 12, 2, skin.outline, 1);
      break;
    }
    case 'crown': {
      // Couronne (5 pointes)
      ctx.fill(skin.accessoryColor);
      ctx.beginPath();
      ctx.moveTo(cx - 12, top - 1);
      ctx.lineTo(cx - 10, top - 9);
      ctx.lineTo(cx - 5, top - 3);
      ctx.lineTo(cx, top - 11);
      ctx.lineTo(cx + 5, top - 3);
      ctx.lineTo(cx + 10, top - 9);
      ctx.lineTo(cx + 12, top - 1);
      ctx.closePath();
      ctx.fillPath();
      strokePoly(ctx, [
        [cx - 12, top - 1], [cx - 10, top - 9], [cx - 5, top - 3],
        [cx, top - 11], [cx + 5, top - 3], [cx + 10, top - 9], [cx + 12, top - 1]
      ], skin.outline, 1);
      break;
    }
  }
}

// --- Helpers géométriques pour RenderTexture ---
function fillRoundRect(ctx, x, y, w, h, r, color) {
  ctx.fill(color, 1);
  ctx.fillRoundedRect(x, y, w, h, r);
}
function strokeRoundRect(ctx, x, y, w, h, r, color, width = 1) {
  ctx.lineStyle(width, hexToInt(color), 1);
  ctx.strokeRoundedRect(x, y, w, h, r);
}
function strokeCircle(ctx, x, y, r, color, width = 1) {
  ctx.lineStyle(width, hexToInt(color), 1);
  ctx.strokeCircle(x, y, r);
}
function strokePoly(ctx, points, color, width = 1) {
  ctx.lineStyle(width, hexToInt(color), 1);
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
  ctx.closePath();
  ctx.strokePath();
}
function hexToInt(hex) {
  return parseInt(hex.replace('#', ''), 16);
}

// =====================================================================
// SCÈNES PHASER
// =====================================================================

class BootScene extends Phaser.Scene {
  constructor() { super('Boot'); }

  create() {
    // Masquer le loader HTML
    const el = document.getElementById('loading');
    if (el) el.classList.add('hidden');

    // Aller à l'écran de customisation pour commencer
    this.scene.start('Customizer');
  }
}

class CustomizerScene extends Phaser.Scene {
  constructor() { super('Customizer'); }

  create() {
    const { width, height } = this.scale;

    // Fond
    this.cameras.main.setBackgroundColor('#0d1320');

    // Titre
    this.add.text(width / 2, 40, 'CRÉE TON CUBE', {
      fontFamily: 'system-ui, sans-serif', fontSize: '28px',
      color: '#e8eef7', fontStyle: 'bold'
    }).setOrigin(0.5);

    this.add.text(width / 2, 70, 'Personnalise ton personnage avant d\'entrer dans le monde', {
      fontFamily: 'system-ui, sans-serif', fontSize: '13px',
      color: '#9fb3c8'
    }).setOrigin(0.5);

    // Zone d'aperçu (gauche)
    const previewX = 220, previewY = height / 2;
    this.add.rectangle(previewX, previewY, 260, 260, 0x182236, 1).setStrokeStyle(2, 0x2a3a52);

    // RenderTexture pour prévisualisation
    this.previewRT = this.add.renderTexture(previewX - 100, previewY - 100, 200, 200);
    this.redrawPreview();

    // Champ nom
    this.add.text(previewX - 120, previewY - 145, 'PSEUDO', { fontSize: '11px', color: '#9fb3c8' });

    // DOM input pour le nom (Phaser gère mal les inputs clavier autrement)
    this.nameInput = document.createElement('input');
    this.nameInput.type = 'text';
    this.nameInput.maxLength = 16;
    this.nameInput.placeholder = 'Joueur';
    this.nameInput.value = myName;
    this.nameInput.style.cssText = `
      position: absolute; left: ${previewX - 120}px; top: ${previewY - 130}px;
      width: 200px; padding: 8px 10px; border: 1px solid #2a3a52;
      background: #0d1320; color: #e8eef7; border-radius: 6px;
      font-family: system-ui; font-size: 14px; outline: none;
    `;
    document.body.appendChild(this.nameInput);
    this.nameInput.addEventListener('input', (e) => {
      myName = e.target.value.slice(0, 16);
    });

    // --- Panneau de customisation (droite) ---
    const panelX = 480, panelY = 140;
    this.add.rectangle(panelX + 220, height / 2, 480, height - 200, 0x141d2e, 1)
      .setStrokeStyle(2, 0x2a3a52);

    this.add.text(panelX, 110, 'PERSONNALISATION', { fontSize: '12px', color: '#9fb3c8' });

    let yCursor = 145;
    const sectionGap = 78;

    // Couleurs (body, hair, eye, mouth, accessory)
    yCursor = this.addColorRow(panelX, yCursor, 'COULEUR DU CORPS', 'body', ['#5b9bd5', '#e85d75', '#5dc264', '#f0c14b', '#9b59b6', '#e67e22', '#1abc9c', '#ecf0f1', '#2c3e50']);
    yCursor = this.addColorRow(panelX, yCursor, 'COULEUR DE CHEVEUX', 'hairColor', ['#3a2a1a', '#1a1a1a', '#d4a373', '#ffd54a', '#ff5e5e', '#7c3aed', '#06b6d4', '#ec4899']);
    yCursor = this.addColorRow(panelX, yCursor, 'COULEUR DES YEUX', 'eyeColor', ['#ffffff', '#fff3a3', '#a3ffe0', '#a3d4ff', '#ffa3d4']);
    yCursor = this.addColorRow(panelX, yCursor, 'BOUCHE', 'mouthColor', ['#7a2f2f', '#000000', '#e85d75', '#ffffff']);
    yCursor = this.addColorRow(panelX, yCursor, 'ACCESSOIRE COULEUR', 'accessoryColor', ['#ffd54a', '#1a1a1a', '#e85d75', '#5b9bd5', '#5dc264', '#9b59b6', '#ffffff']);

    // Sélecteur de style de cheveux
    yCursor = this.addStyleRow(panelX, yCursor, 'COIFFURE', 'hairStyle', HAIR_STYLES);
    // Sélecteur d'accessoire
    yCursor = this.addStyleRow(panelX, yCursor, 'ACCESSOIRE', 'accessory', ACCESSORIES);

    // --- Boutons d'action (bas) ---
    const btnY = height - 50;
    const startBtn = this.add.rectangle(width / 2 - 100, btnY, 180, 44, 0x2ecc71, 1)
      .setStrokeStyle(2, 0x27ae60).setInteractive({ useHandCursor: true });
    this.add.text(width / 2 - 100, btnY, '▶ ENTRER DANS LE MONDE', {
      fontSize: '13px', color: '#0d1320', fontStyle: 'bold'
    }).setOrigin(0.5);
    startBtn.on('pointerover', () => startBtn.setFillStyle(0x58d68d));
    startBtn.on('pointerout', () => startBtn.setFillStyle(0x2ecc71));
    startBtn.on('pointerdown', () => this.enterWorld());

    const randomBtn = this.add.rectangle(width / 2 + 100, btnY, 100, 44, 0x34495e, 1)
      .setStrokeStyle(2, 0x2c3e50).setInteractive({ useHandCursor: true });
    this.add.text(width / 2 + 100, btnY, '🎲 ALÉATOIRE', {
      fontSize: '12px', color: '#ecf0f1'
    }).setOrigin(0.5);
    randomBtn.on('pointerover', () => randomBtn.setFillStyle(0x415b76));
    randomBtn.on('pointerout', () => randomBtn.setFillStyle(0x34495e));
    randomBtn.on('pointerdown', () => this.randomize());

    // Cleanup du DOM input si on quitte la scène
    this.events.once('shutdown', () => {
      if (this.nameInput && this.nameInput.parentNode) this.nameInput.parentNode.removeChild(this.nameInput);
    });
  }

  addColorRow(x, y, label, propName, colors) {
    this.add.text(x, y, label, { fontSize: '11px', color: '#9fb3c8' });
    const swatchY = y + 18;
    colors.forEach((c, i) => {
      const sx = x + i * 32;
      const sw = this.add.rectangle(sx + 12, swatchY, 24, 24, hexToInt(c), 1)
        .setStrokeStyle(2, mySkin[propName] === c ? 0xffffff : 0x2a3a52)
        .setInteractive({ useHandCursor: true });
      sw.on('pointerdown', () => {
        mySkin[propName] = c;
        this.refreshSwatches(propName, colors);
        this.redrawPreview();
      });
    });
    // mémo pour pouvoir re-stroker après refresh
    if (!this._swatchRows) this._swatchRows = {};
    this._swatchRows[propName] = { x, y: swatchY, colors };
    return y + 50;
  }

  refreshSwatches(propName, colors) {
    // Simple: on redessine toutes les rangées -> plus simple, on accepte le coût.
    this.children.list
      .filter(c => c.type === 'Rectangle' && c.input)
      .forEach(c => c.destroy());
    // Reload en recréant toute la UI -> lourd mais on a peu d'éléments
    // À la place, on met à jour juste les bordures (plus propre):
    if (this._swatchRows && this._swatchRows[propName]) {
      const row = this._swatchRows[propName];
      row.colors.forEach((c, i) => {
        const sx = row.x + i * 32;
        const swatch = this.children.list.find(ch =>
          ch.type === 'Rectangle' && Math.abs(ch.x - (sx + 12)) < 1 && Math.abs(ch.y - row.y) < 1
        );
        if (swatch) swatch.setStrokeStyle(2, mySkin[propName] === c ? 0xffffff : 0x2a3a52);
      });
    }
  }

  addStyleRow(x, y, label, propName, options) {
    this.add.text(x, y, label, { fontSize: '11px', color: '#9fb3c8' });
    const rowY = y + 18;
    options.forEach((opt, i) => {
      const sx = x + i * 52;
      const isActive = mySkin[propName] === opt;
      const btn = this.add.rectangle(sx + 22, rowY, 48, 26, isActive ? 0x5b9bd5 : 0x34495e, 1)
        .setStrokeStyle(2, isActive ? 0xffffff : 0x2a3a52)
        .setInteractive({ useHandCursor: true });
      this.add.text(sx + 22, rowY, opt, { fontSize: '10px', color: '#ecf0f1' }).setOrigin(0.5);
      btn.on('pointerdown', () => {
        mySkin[propName] = opt;
        // Recréer uniquement cette rangée
        this.refreshStyleRow(propName, options);
        this.redrawPreview();
      });
    });
    if (!this._styleRows) this._styleRows = {};
    this._styleRows[propName] = { x, y: rowY, options };
    return y + 50;
  }

  refreshStyleRow(propName, options) {
    const row = this._styleRows?.[propName];
    if (!row) return;
    row.options.forEach((opt, i) => {
      const sx = row.x + i * 52;
      const isActive = mySkin[propName] === opt;
      const btn = this.children.list.find(ch =>
        ch.type === 'Rectangle' && Math.abs(ch.x - (sx + 22)) < 1 && Math.abs(ch.y - row.y) < 1
      );
      if (btn) {
        btn.setFillStyle(isActive ? 0x5b9bd5 : 0x34495e);
        btn.setStrokeStyle(2, isActive ? 0xffffff : 0x2a3a52);
      }
    });
  }

  redrawPreview() {
    this.previewRT.clear();
    drawCubeAvatar(this.previewRT, mySkin);
  }

  randomize() {
    const pick = arr => arr[Math.floor(Math.random() * arr.length)];
    mySkin = {
      body: pick(['#5b9bd5', '#e85d75', '#5dc264', '#f0c14b', '#9b59b6', '#e67e22']),
      outline: '#0e1a2b',
      eyeColor: pick(['#ffffff', '#fff3a3', '#a3d4ff']),
      pupilColor: '#111111',
      mouthColor: pick(['#7a2f2f', '#000000', '#e85d75']),
      hairStyle: pick(HAIR_STYLES),
      hairColor: pick(['#3a2a1a', '#1a1a1a', '#d4a373', '#ffd54a', '#ff5e5e', '#7c3aed', '#06b6d4', '#ec4899']),
      accessory: pick(ACCESSORIES),
      accessoryColor: pick(['#ffd54a', '#e85d75', '#5b9bd5', '#5dc264', '#9b59b6', '#ffffff']),
      cheekColor: '#ff8fa3'
    };
    // Recharger toute la scène Customizer (simple et fiable)
    this.scene.restart();
  }

  enterWorld() {
    const finalName = (this.nameInput?.value || myName || 'Joueur').trim() || 'Joueur';
    myName = finalName;
    if (this.nameInput?.parentNode) this.nameInput.parentNode.removeChild(this.nameInput);
    this.scene.start('World');
  }
}

class WorldScene extends Phaser.Scene {
  constructor() { super('World'); }

  create() {
    this.cameras.main.setBackgroundColor('#' + world.bg.toString(16).padStart(6, '0'));

    // Émettre l'identité au serveur
    socket.emit('player:join', { name: myName, skin: mySkin });

    // --- Monde: sol carrelé + grille subtile ---
    const ground = this.add.graphics();
    ground.fillStyle(world.bg, 1);
    ground.fillRect(0, 0, world.width, world.height);
    // Grille (lignes fines, un peu de couleur)
    ground.lineStyle(1, world.grid, 0.4);
    for (let x = 0; x <= world.width; x += world.tile) {
      ground.lineBetween(x, 0, x, world.height);
    }
    for (let y = 0; y <= world.height; y += world.tile) {
      ground.lineBetween(0, y, world.width, y);
    }
    // Bordure du monde (visible)
    ground.lineStyle(4, 0x4a5b75, 1);
    ground.strokeRect(0, 0, world.width, world.height);
    this.ground = ground;

    // Conteneur principal pour les persos
    this.entityLayer = this.add.container(0, 0);

    // Sprite du joueur local (créé dès qu'on reçoit l'hello du serveur)
    this.localSprite = null;
    this.localNameText = null;

    // --- Clavier ---
    this.cursors = this.input.keyboard.createCursorKeys();
    this.wasd = this.input.keyboard.addKeys('W,A,S,D');

    // --- UI: nom et indicateur de joueurs en ligne ---
    this.onlineText = this.add.text(12, 12, 'Joueurs en ligne: 0', {
      fontSize: '14px', color: '#e8eef7',
      backgroundColor: '#0d1320', padding: { x: 10, y: 6 }
    }).setScrollFactor(0).setDepth(1000);

    this.helpText = this.add.text(12, 44, 'ZQSD / Flèches pour bouger • Échap pour personnaliser', {
      fontSize: '11px', color: '#9fb3c8',
      backgroundColor: '#0d1320', padding: { x: 10, y: 6 }
    }).setScrollFactor(0).setDepth(1000);

    this.add.text(window.innerWidth - 12, 12, '🟢 En ligne', {
      fontSize: '12px', color: '#2ecc71',
      backgroundColor: '#0d1320', padding: { x: 10, y: 6 }
    }).setOrigin(1, 0).setScrollFactor(0).setDepth(1000);

    // --- Bouton personnaliser ---
    const editBtn = this.add.rectangle(window.innerWidth - 100, window.innerHeight - 40, 180, 36, 0x34495e, 1)
      .setStrokeStyle(2, 0x5b9bd5).setInteractive({ useHandCursor: true })
      .setScrollFactor(0).setDepth(1000);
    this.add.text(window.innerWidth - 100, window.innerHeight - 40, '✏️  Personnaliser', {
      fontSize: '12px', color: '#e8eef7'
    }).setOrigin(0.5).setScrollFactor(0).setDepth(1000);
    editBtn.on('pointerdown', () => {
      socket.emit('player:skin', mySkin);
      this.scene.start('Customizer');
    });

    // --- Socket: réception des événements ---
    socket.on('world:hello', (data) => {
      world = data.world;
      this.createLocalPlayer(data.you);
      data.players.forEach(p => this.addRemotePlayer(p));
      this.updateOnlineCount();
    });

    socket.on('players:add', (p) => {
      if (p.id === socket.id) return;
      this.addRemotePlayer(p);
      this.updateOnlineCount();
    });

    socket.on('players:list', (list) => {
      // Sync d'autorité: le serveur a parlé, on s'aligne.
      const seen = new Set();
      list.forEach(p => {
        if (p.id === socket.id) {
          if (this.localSprite) {
            this.localSprite.setData('serverX', p.x);
            this.localSprite.setData('serverY', p.y);
          }
          return;
        }
        seen.add(p.id);
        const existing = remotePlayers.get(p.id);
        if (existing) {
          existing.skin = p.skin;
          redrawRemote(existing);
          existing.x = p.x; existing.y = p.y; existing.dir = p.dir;
          existing.container.setPosition(p.x, p.y);
        } else {
          this.addRemotePlayer(p);
        }
      });
      // Supprimer ceux qui ne sont plus là
      for (const id of [...remotePlayers.keys()]) {
        if (!seen.has(id)) this.removeRemotePlayer(id);
      }
      this.updateOnlineCount();
    });

    socket.on('players:move', ({ id, x, y, dir }) => {
      const r = remotePlayers.get(id);
      if (!r) return;
      r.targetX = x;
      r.targetY = y;
      r.dir = dir;
    });

    socket.on('players:skin', ({ id, skin }) => {
      const r = remotePlayers.get(id);
      if (r) { r.skin = skin; redrawRemote(r); }
    });

    socket.on('players:remove', ({ id }) => {
      this.removeRemotePlayer(id);
      this.updateOnlineCount();
    });

    // --- Nettoyage à la sortie ---
    this.events.once('shutdown', () => {
      socket.off('world:hello');
      socket.off('players:add');
      socket.off('players:list');
      socket.off('players:move');
      socket.off('players:skin');
      socket.off('players:remove');
    });

    // Resize handling
    this.scale.on('resize', () => {
      this.helpText.setPosition(12, 44);
    });
  }

  createLocalPlayer(p) {
    myPlayer = p;
    const tex = createAvatarTexture(this, 'me', mySkin);
    this.localSprite = this.add.image(p.x, p.y, 'me');
    this.localSprite.setDepth(100);

    // Nom au-dessus
    this.localNameText = this.add.text(p.x, p.y - 36, p.name, {
      fontSize: '12px', color: '#ffffff',
      backgroundColor: '#0d1320', padding: { x: 6, y: 2 }
    }).setOrigin(0.5).setDepth(101);

    this.cameras.main.startFollow(this.localSprite, true, 0.15, 0.15);
  }

  addRemotePlayer(p) {
    if (remotePlayers.has(p.id)) return;
    const key = 'avatar_' + p.id;
    createAvatarTexture(this, key, p.skin);
    const container = this.add.container(p.x, p.y);
    const img = this.add.image(0, 0, key);
    const nameText = this.add.text(0, -36, p.name, {
      fontSize: '11px', color: '#ffffff',
      backgroundColor: '#0d1320', padding: { x: 6, y: 2 }
    }).setOrigin(0.5);
    container.add([img, nameText]);
    container.setDepth(50);
    this.entityLayer.add(container);

    remotePlayers.set(p.id, {
      id: p.id, name: p.name, skin: p.skin,
      container, img, nameText,
      x: p.x, y: p.y,
      targetX: p.x, targetY: p.y,
      dir: p.dir
    });
  }

  removeRemotePlayer(id) {
    const r = remotePlayers.get(id);
    if (!r) return;
    r.container.destroy();
    if (this.textures.exists('avatar_' + id)) this.textures.remove('avatar_' + id);
    remotePlayers.delete(id);
  }

  updateOnlineCount() {
    const total = remotePlayers.size + (this.localSprite ? 1 : 0);
    this.onlineText.setText('Joueurs en ligne: ' + total);
  }

  update(time, delta) {
    if (!this.localSprite || !myPlayer) return;

    // --- Input local (mouvement grille libre) ---
    const speed = 180; // px/s
    let dx = 0, dy = 0;
    if (this.cursors.left.isDown || this.wasd.A.isDown) dx -= 1;
    if (this.cursors.right.isDown || this.wasd.D.isDown) dx += 1;
    if (this.cursors.up.isDown || this.wasd.W.isDown) dy -= 1;
    if (this.cursors.down.isDown || this.wasd.S.isDown) dy += 1;

    // Normalisation diagonale
    if (dx !== 0 && dy !== 0) {
      const inv = 1 / Math.sqrt(2);
      dx *= inv; dy *= inv;
    }

    let dir = myPlayer.dir;
    if (dx < 0) dir = 'left';
    else if (dx > 0) dir = 'right';
    else if (dy < 0) dir = 'up';
    else if (dy > 0) dir = 'down';

    const dt = delta / 1000;
    myPlayer.x += dx * speed * dt;
    myPlayer.y += dy * speed * dt;
    myPlayer.x = Phaser.Math.Clamp(myPlayer.x, 16, world.width - 16);
    myPlayer.y = Phaser.Math.Clamp(myPlayer.y, 16, world.height - 16);
    myPlayer.dir = dir;

    this.localSprite.setPosition(myPlayer.x, myPlayer.y);
    this.localNameText.setPosition(myPlayer.x, myPlayer.y - 36);

    // Envoi serveur (throttle à ~20Hz pour éviter de spam)
    this._lastSend = this._lastSend || 0;
    if (time - this._lastSend > 50) {
      socket.emit('player:move', { x: myPlayer.x, y: myPlayer.y, dir: myPlayer.dir });
      this._lastSend = time;
    }

    // --- Interpolation des autres joueurs ---
    const lerp = 0.2;
    remotePlayers.forEach((r) => {
      r.x += (r.targetX - r.x) * lerp;
      r.y += (r.targetY - r.y) * lerp;
      r.container.setPosition(r.x, r.y);
    });
  }
}

// Crée (ou recrée) la texture d'un avatar à partir d'un skin
function createAvatarTexture(scene, key, skin) {
  if (scene.textures.exists(key)) scene.textures.remove(key);
  const rt = scene.add.renderTexture(0, 0, 48, 48);
  drawCubeAvatar(rt, skin);
  rt.saveTexture(key);
  rt.destroy();
}

function redrawRemote(r) {
  if (!r.img || !r.img.scene) return;
  const scene = r.img.scene;
  createAvatarTexture(scene, 'avatar_' + r.id, r.skin);
  r.img.setTexture('avatar_' + r.id);
}

// =====================================================================
// Lancement Phaser
// =====================================================================
const config = {
  type: Phaser.AUTO,
  parent: 'game',
  backgroundColor: '#0d1320',
  scale: {
    mode: Phaser.Scale.RESIZE,
    autoCenter: Phaser.Scale.CENTER_BOTH,
    width: window.innerWidth,
    height: window.innerHeight
  },
  scene: [BootScene, CustomizerScene, WorldScene]
};

window.addEventListener('load', () => {
  // Attendre la connexion Socket.io avant de lancer (sinon la scène World ne reçoit rien)
  socket.on('connect', () => {
    if (!window._phaserStarted) {
      window._phaserStarted = true;
      new Phaser.Game(config);
    }
  });
  // Si déjà connecté (recharge):
  if (socket.connected && !window._phaserStarted) {
    window._phaserStarted = true;
    new Phaser.Game(config);
  }
});
