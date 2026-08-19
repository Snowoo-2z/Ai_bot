import os
import json
import time
import math
import random
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

EMAIL = os.getenv("ARENA_EMAIL")
PASSWORD = os.getenv("ARENA_PASSWORD")
SESSION_FILE = os.getenv("SESSION_FILE", "session.json")
# Optionnel : session persistée dans une variable d'environnement.
# Utile sur Render (disque éphémère) : la session survit aux redémarrages,
# ce qui évite de se reconnecter (et donc de déclencher un reCAPTCHA) à chaque fois.
SESSION_JSON = os.getenv("SESSION_JSON", "")

# Nom affiché dans le message d'erreur "trop de demandes"
SERVICE_NAME = os.getenv("SERVICE_NAME", "xHigh")

# Nombre de relances (via le lien direct chat) avant d'abandonner
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5"))
# Pause (en secondes) entre deux tentatives
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "10"))

# ── Comportement "humain" ──────────────────────────────────────────────
# Réduit le déclenchement des protections en tapant/temporisant de façon naturelle.
# (mettre HUMANIZE=0 pour retrouver l'ancien comportement instantané)
HUMANIZE = os.getenv("HUMANIZE", "1") != "0"
TYPE_DELAY_MIN = int(os.getenv("TYPE_DELAY_MIN", "15"))    # ms entre chaque caractère
TYPE_DELAY_MAX = int(os.getenv("TYPE_DELAY_MAX", "55"))    # ms entre chaque caractère
HUMAN_TYPE_CHUNK = int(os.getenv("HUMAN_TYPE_CHUNK", "300"))  # nbre de caractères tapés naturellement (le reste est collé)
THINK_MIN = float(os.getenv("THINK_MIN", "1.0"))           # s avant de commencer à taper
THINK_MAX = float(os.getenv("THINK_MAX", "3.0"))           # s avant de commencer à taper
PRE_SEND_MIN = float(os.getenv("PRE_SEND_MIN", "0.4"))     # s avant d'appuyer sur Entrée
PRE_SEND_MAX = float(os.getenv("PRE_SEND_MAX", "1.4"))     # s avant d'appuyer sur Entrée
RESPONSE_TIMEOUT = int(os.getenv("RESPONSE_TIMEOUT", "60"))  # s max d'attente de la réponse
TYPO_RATE = float(os.getenv("TYPO_RATE", "0.03"))          # proba d'une faute de frappe (corrigée aussitôt)
BURST_MIN = int(os.getenv("BURST_MIN", "2"))               # nb min de caractères par rafale
BURST_MAX = int(os.getenv("BURST_MAX", "6"))               # nb max de caractères par rafale

HOME_URL = "https://arena.ai"
DIRECT_CHAT_URL = "https://arena.ai/direct"

CHROMIUM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


class CaptchaBlockedError(Exception):
    """reCAPTCHA / hCaptcha détecté, ou clic intercepté par un overlay (timeout)."""


class TooManyRequestsError(Exception):
    """Trop de tentatives bloquées : on abandonne avec un message propre."""


def _build_full_prompt(prompt: str, system_prompt: str) -> str:
    if system_prompt:
        return f"[INSTRUCTIONS SYSTÈME : {system_prompt}]\n\n{prompt}"
    return prompt


def _has_session() -> bool:
    """Une session est-elle disponible (fichier ou variable d'env) ?"""
    return os.path.exists(SESSION_FILE) or bool(SESSION_JSON.strip())


def _storage_state():
    """Renvoie le storage_state à passer au navigateur (chemin ou dict)."""
    if os.path.exists(SESSION_FILE):
        return SESSION_FILE
    if SESSION_JSON.strip():
        try:
            return json.loads(SESSION_JSON)
        except Exception:
            pass
    return SESSION_FILE


async def _human_pause(min_s: float, max_s: float):
    """Pause aléatoire façon humaine (désactivable via HUMANIZE=0)."""
    if not HUMANIZE:
        return
    await asyncio.sleep(random.uniform(min_s, max_s))


# Dernière position connue de la souris (pour des trajectoires continues et naturelles)
_last_mouse_pos = None


def _reset_mouse():
    global _last_mouse_pos
    _last_mouse_pos = None


async def _human_mouse_move(page, x: float, y: float):
    """Déplace la souris jusqu'à (x, y) avec une trajectoire courbe et saccadée."""
    global _last_mouse_pos
    if not HUMANIZE:
        await page.mouse.move(x, y)
        _last_mouse_pos = (x, y)
        return

    vp = page.viewport_size or {"width": 1280, "height": 800}
    if _last_mouse_pos is None:
        sx = random.uniform(0, vp["width"])
        sy = random.uniform(0, vp["height"])
    else:
        sx, sy = _last_mouse_pos

    dx = x - sx
    dy = y - sy
    dist = math.hypot(dx, dy)
    # léger "arc" aléatoire perpendiculaire à la trajectoire (façon main humaine)
    curve = random.uniform(-1, 1) * min(dist * 0.25, 160)
    steps = random.randint(10, 28)

    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)  # ease in-out (accélération/décélération naturelle)
        cx = sx + dx * e
        cy = sy + dy * e
        if dist > 0:
            px = -dy / dist
            py = dx / dist
            arc = math.sin(t * math.pi) * curve
            cx += px * arc
            cy += py * arc
        await page.mouse.move(cx, cy)
        await asyncio.sleep(random.uniform(0.003, 0.018))

    await page.mouse.move(x, y)
    _last_mouse_pos = (x, y)


async def _human_idle_mouse(page):
    """Petit déplacement de souris 'nerveux', comme quelqu'un qui patiente."""
    if not HUMANIZE:
        return
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        await _human_mouse_move(
            page,
            random.uniform(0, vp["width"]),
            random.uniform(0, vp["height"]),
        )
    except Exception:
        pass


async def _human_click(page, locator):
    """Déplace la souris vers l'élément (trajectoire humaine) puis clique.

    Ajoute la petite "correction de visée" humaine : on arrive légèrement à côté
    de la cible, puis on se recentre dessus avant de cliquer.
    """
    try:
        box = await locator.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            # survol un peu à côté, puis recentrage sur la cible
            await _human_mouse_move(page, cx + random.uniform(-14, 14), cy + random.uniform(-10, 10))
            await _human_pause(0.03, 0.12)
            await _human_mouse_move(page, cx, cy)
            await _human_pause(0.05, 0.25)
    except Exception:
        pass
    await locator.click(timeout=5000)


async def _human_scroll(page, amount: int = None):
    """Défilement de page progressif et saccadé, comme un humain qui lit."""
    if not HUMANIZE:
        if amount:
            await page.mouse.wheel(0, amount)
        return
    total = amount if amount is not None else random.randint(180, 520)
    steps = random.randint(3, 7)
    for _ in range(steps):
        await page.mouse.wheel(0, total / steps)
        await asyncio.sleep(random.uniform(0.03, 0.12))


# Voisins de clavier (Qwerty/Azerty) plausibles pour simuler des fautes de frappe
_NEARBY_KEYS = {
    "a": "qzsw", "z": "asx", "e": "wrd", "r": "etf", "t": "rgy",
    "y": "tgu", "u": "yij", "i": "uok", "o": "ipl", "p": "ok",
    "q": "aws", "s": "azxdc", "d": "sefc", "f": "drgv", "g": "ftyhb",
    "h": "gyujn", "j": "huikm", "k": "jiol", "l": "kop", "m": "njk",
    "w": "qase", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn", "n": "bhjm",
}


def _nearby_key(ch: str) -> str:
    candidates = _NEARBY_KEYS.get(ch.lower())
    if not candidates:
        return random.choice("aeiountsrl")
    return random.choice(candidates)


async def _human_type(page, text: str):
    """Tape le texte par rafales, avec fautes de frappe corrigées, comme un humain."""
    if not HUMANIZE or not text:
        await page.keyboard.insert_text(text)
        return

    natural_part = text[:HUMAN_TYPE_CHUNK]
    rest = text[HUMAN_TYPE_CHUNK:]

    i = 0
    n = len(natural_part)
    while i < n:
        # une "rafale" de quelques caractères tapés rapidement
        burst = random.randint(BURST_MIN, BURST_MAX)
        for _ in range(burst):
            if i >= n:
                break
            ch = natural_part[i]
            # faute de frappe rare, corrigée aussitôt (backspace) — ne change jamais le texte final
            if i >= 2 and TYPO_RATE > 0 and random.random() < TYPO_RATE:
                await page.keyboard.type(_nearby_key(ch), delay=random.randint(TYPE_DELAY_MIN, TYPE_DELAY_MAX))
                await asyncio.sleep(random.uniform(0.06, 0.22))   # temps de "réaliser" la faute
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.03, 0.12))
            await page.keyboard.type(ch, delay=random.randint(TYPE_DELAY_MIN, TYPE_DELAY_MAX))
            i += 1
        # pause entre deux rafales (réflexion) + la souris bouge parfois
        await asyncio.sleep(random.uniform(0.15, 0.6))
        if random.random() < 0.3:
            await _human_idle_mouse(page)

    # le reste du (long) message est collé d'un coup — plus rapide et tout aussi naturel
    if rest:
        await page.keyboard.insert_text(rest)


async def _detect_captcha(page) -> bool:
    """Détecte la présence d'un reCAPTCHA / hCaptcha / vérification humaine sur la page."""
    try:
        found = await page.evaluate(
            """() => {
                const iframes = Array.from(document.querySelectorAll('iframe'));
                for (const f of iframes) {
                    const src = (f.src || '').toLowerCase();
                    const title = (f.title || '').toLowerCase();
                    if (src.includes('recaptcha') || src.includes('hcaptcha') || src.includes('captcha')
                        || title.includes('recaptcha') || title.includes('captcha')) {
                        return true;
                    }
                }
                const body = (document.body ? document.body.innerText : '').toLowerCase();
                const hints = [
                    'not a robot',
                    'verify you are human',
                    'verify that you are human',
                    "confirm you're human",
                    'vérifiez que vous êtes',
                    'prouvez que vous êtes humain',
                    'security check',
                    'vérification de sécurité',
                ];
                for (const h of hints) {
                    if (body.includes(h)) return true;
                }
                return false;
            }"""
        )
        return bool(found)
    except Exception:
        return False


async def _click_first_available(page, selectors) -> bool:
    """Clique sur le premier sélecteur visible. Gère les overlays qui interceptent les clics."""
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            await loc.wait_for(state="visible", timeout=2000)
        except Exception:
            continue
        # Déplace la souris vers l'élément de façon humaine avant de cliquer
        try:
            box = await loc.bounding_box()
            if box:
                await _human_mouse_move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await _human_pause(0.05, 0.25)
        except Exception:
            pass
        try:
            await loc.click(timeout=5000)
            return True
        except PlaywrightTimeoutError:
            # Un overlay (bannière cookie, captcha…) intercepte le clic → clic forcé.
            try:
                await loc.click(timeout=5000, force=True)
                return True
            except Exception:
                continue
        except Exception:
            continue
    return False


EXTRACT_JS = """(userPrompt) => {
    const lineClamps = document.querySelectorAll('.line-clamp-1, [class*="line-clamp-1"]');
    let bestText = "";
    lineClamps.forEach(el => {
        let parent = el.closest('div[class*="message"], article, section, div[class*="group"], div.relative');
        if (!parent) parent = el.parentElement?.parentElement;
        if (parent) {
            let t = parent.innerText.trim();
            if (t && !t.includes(userPrompt) && t.length > 5) bestText = t;
        }
    });
    return bestText;
}"""


async def _extract_result(page, full_prompt: str) -> str:
    """Récupère le texte de la réponse ("" si pas encore disponible)."""
    raw_result = await page.evaluate(EXTRACT_JS, full_prompt)
    lines = (raw_result or "").split("\n")
    filtered = [l.strip() for l in lines if l.strip() and "Response provided by" not in l
                and l.strip() not in ["Max", "Google", "Claude", "GPT-4", "Gemini"]]
    return " ".join(filtered).strip()


async def _wait_for_response(page, full_prompt: str) -> str:
    """Attend (de façon non robotique) que la réponse arrive, avec timeout."""
    deadline = time.time() + RESPONSE_TIMEOUT
    ticks = 0
    while time.time() < deadline:
        if await _detect_captcha(page):
            raise CaptchaBlockedError("reCAPTCHA apparu après l'envoi.")
        result = await _extract_result(page, full_prompt)
        if result:
            return result
        await asyncio.sleep(random.uniform(1.5, 3.0))
        # de temps en temps, la souris bouge un peu pendant l'attente
        ticks += 1
        if ticks % 3 == 0:
            await _human_idle_mouse(page)
    raise CaptchaBlockedError("Aucune réponse détectée (blocage probable).")


async def login_and_save_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        context = await browser.new_context()
        page = await context.new_page()
        _reset_mouse()
        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded")
            await _human_pause(2.5, 4.5)

            if await _detect_captcha(page):
                raise CaptchaBlockedError("reCAPTCHA détecté sur la page de connexion.")

            # Menu de connexion (robuste : force le clic si un élément intercepte les clics)
            await _click_first_available(page, ["button[aria-label*='menu' i]", "button:has(svg)"])
            await _human_pause(0.8, 1.8)

            await _click_first_available(page, ["text=Log in", "button:has-text('Log in')"])
            await _human_pause(1.2, 2.5)

            email_input = page.locator("input[type='email']").first
            await _human_click(page, email_input)
            await _human_type(page, EMAIL)
            await _human_pause(0.6, 1.5)

            await _click_first_available(page, [
                "button:has-text('Continue with Email')",
                "form:has(input[type='email']) button[type='submit']",
            ])
            await _human_pause(1.5, 3.0)

            pwd_input = page.locator("input[type='password']").first
            await _human_click(page, pwd_input)
            await _human_type(page, PASSWORD)
            await _human_pause(0.5, 1.5)
            await pwd_input.press("Enter")
            await _human_pause(3.5, 6.0)

            if await _detect_captcha(page):
                raise CaptchaBlockedError("reCAPTCHA détecté pendant la connexion.")

            storage = await context.storage_state()
            with open(SESSION_FILE, "w") as f:
                json.dump(storage, f)
            print("✅ Session sauvegardée.")
            # Astuce Render : copie cette valeur dans la variable d'env SESSION_JSON
            # pour que la session survive aux redémarrages (disque éphémère).
            print(f"💡 SESSION_JSON={json.dumps(storage)}")
        finally:
            await context.close()
            await browser.close()


async def _send_once(full_prompt: str) -> str:
    """Un seul envoi via le lien direct chat (https://arena.ai/direct)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        try:
            context = await browser.new_context(storage_state=_storage_state())
            try:
                page = await context.new_page()
                _reset_mouse()
                await page.goto(DIRECT_CHAT_URL, wait_until="domcontentloaded")
                await _human_pause(2.5, 4.5)

                if await _detect_captcha(page):
                    raise CaptchaBlockedError("reCAPTCHA détecté sur la page de chat.")

                # Session expirée ? On se reconnecte puis on recharge la page de chat.
                if await page.locator("text=Log in").first.is_visible(timeout=2000):
                    print("⚠️ Session expirée, reconnexion...")
                    await context.close()
                    context = None
                    await login_and_save_session()
                    context = await browser.new_context(storage_state=_storage_state())
                    page = await context.new_page()
                    _reset_mouse()
                    await page.goto(DIRECT_CHAT_URL, wait_until="domcontentloaded")
                    await _human_pause(2.5, 4.5)
                    if await _detect_captcha(page):
                        raise CaptchaBlockedError("reCAPTCHA détecté après reconnexion.")

                # "Lecture" de la page avant d'agir : léger scroll + souris qui bouge
                await _human_scroll(page)
                await _human_pause(0.4, 1.1)
                await _human_idle_mouse(page)

                textarea = page.locator("textarea[placeholder*='Send'], textarea").first
                await textarea.wait_for(state="visible", timeout=15000)
                await textarea.scroll_into_view_if_needed()
                await _human_pause(0.3, 0.9)

                await _human_click(page, textarea)
                await _human_pause(THINK_MIN, THINK_MAX)
                await _human_type(page, full_prompt)
                await _human_pause(PRE_SEND_MIN, PRE_SEND_MAX)
                await textarea.press("Enter")

                return await _wait_for_response(page, full_prompt)
            finally:
                if context is not None:
                    await context.close()
        finally:
            await browser.close()


async def send_prompt_to_ai(prompt: str, system_prompt: str = "") -> str:
    full_prompt = _build_full_prompt(prompt, system_prompt)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Session absente ? On tente de se connecter (peut être bloqué par un captcha).
        if not _has_session():
            try:
                await login_and_save_session()
            except CaptchaBlockedError as e:
                print(f"⚠️ Connexion bloquée ({e}) — tentative {attempt}/{MAX_ATTEMPTS}.")
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                continue

        try:
            return await _send_once(full_prompt)
        except (CaptchaBlockedError, PlaywrightTimeoutError) as e:
            print(f"⚠️ Tentative {attempt}/{MAX_ATTEMPTS} bloquée ({e}). Relance via le lien direct...")
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    raise TooManyRequestsError(
        f"Trop de demandes sur {SERVICE_NAME} pour le moment. "
        "Nous réessayerons d'ici quelques minutes automatiquement."
    )
