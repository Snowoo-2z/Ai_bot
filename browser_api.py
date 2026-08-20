"""API de contrôle d'un navigateur à distance (Playwright).

Permet à un autre site (ou une IA) d'ouvrir des sessions navigateur, d'exécuter
des actions (navigation, recherche, clic, saisie, défilement...) et de
récupérer ce que la page affiche : textes, boutons, liens, champs de saisie
et capture d'écran.
"""
import asyncio
import os
import re
import time
import urllib.parse
import uuid

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ─────────────────────────── Configuration ───────────────────────────
HEADLESS = os.getenv("HEADLESS", "1") != "0"
# Durée d'inactivité avant fermeture automatique d'une session (minutes)
SESSION_IDLE_TIMEOUT = int(os.getenv("SESSION_IDLE_TIMEOUT_MIN", "15")) * 60
# Nombre maximum de sessions navigateur simultanées
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "20"))
# Timeout de navigation (ms)
NAV_TIMEOUT = int(os.getenv("NAV_TIMEOUT_MS", "30000"))

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]
USER_AGENT = os.getenv(
    "BROWSER_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36",
)

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}

# ─────────────────────────── Erreurs ───────────────────────────
class BrowserError(Exception):
    """Erreur générique du navigateur distant."""


class SessionNotFoundError(BrowserError):
    """Session inconnue (expirée ou fermée)."""


class SessionLimitError(BrowserError):
    """Trop de sessions ouvertes."""


class ActionError(BrowserError):
    """Action invalide ou impossible à exécuter."""


# ─────────────────── Extraction de l'état visible (snapshot) ───────────────────
# Renvoie ce qu'un humain "voit" sur la page : titre, URL, blocs de texte,
# boutons, liens et champs de saisie.
SNAPSHOT_JS = r"""() => {
    const MAX_TEXTS = 40, MAX_LINKS = 60, MAX_BUTTONS = 60, MAX_INPUTS = 30;
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 1 && r.height > 1 && s.visibility !== 'hidden'
            && s.display !== 'none' && s.opacity !== '0';
    };
    const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
    const txt = (el) => clean(el.innerText || el.value || el.textContent || '');

    const texts = [];
    const seenTexts = new Set();
    document.querySelectorAll('h1,h2,h3,h4,h5,p,li,td,th,blockquote,pre,summary,label').forEach((el) => {
        if (texts.length >= MAX_TEXTS) return;
        if (!isVisible(el)) return;
        const t = txt(el);
        if (t.length < 12 || seenTexts.has(t)) return;
        seenTexts.add(t);
        texts.push(t.slice(0, 3000));
    });

    const buttons = [];
    const seenButtons = new Set();
    document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]').forEach((el) => {
        if (buttons.length >= MAX_BUTTONS) return;
        if (!isVisible(el)) return;
        const t = txt(el);
        if (!t || seenButtons.has(t)) return;
        seenButtons.add(t);
        buttons.push({ text: t.slice(0, 200) });
    });

    const links = [];
    const seenLinks = new Set();
    document.querySelectorAll('a[href]').forEach((el) => {
        if (links.length >= MAX_LINKS) return;
        if (!isVisible(el)) return;
        const t = txt(el);
        if (!t || seenLinks.has(t)) return;
        seenLinks.add(t);
        links.push({ text: t.slice(0, 200), href: el.href });
    });

    const inputs = [];
    document.querySelectorAll('input, textarea, select').forEach((el) => {
        if (inputs.length >= MAX_INPUTS) return;
        if (!isVisible(el)) return;
        const type = el.type || (el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select' : 'text');
        if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'file'].includes(type)) return;
        let selector = '';
        if (el.id) selector = '#' + CSS.escape(el.id);
        else if (el.name) selector = el.tagName.toLowerCase() + '[name="' + String(el.name).replace(/"/g, '\\"') + '"]';
        else if (el.placeholder) selector = el.tagName.toLowerCase() + '[placeholder="' + String(el.placeholder).replace(/"/g, '\\"') + '"]';
        inputs.push({
            type,
            placeholder: String(el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100),
            selector,
            value: String(el.value || '').slice(0, 100),
        });
    });

    return { title: document.title, texts, buttons, links, inputs };
}"""


def _clean_result_url(engine: str, href: str) -> str:
    """Nettoie les URL de résultats (ex. lien de redirection Google)."""
    if "google." in href and "/url?" in href:
        m = re.search(r"[?&]q=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    return href


def _is_engine_junk(engine: str, href: str) -> bool:
    """Filtre les liens 'outils' des moteurs de recherche (préférences, aide...)."""
    host = (urllib.parse.urlparse(href).netloc or "").lower()
    path = urllib.parse.urlparse(href).path
    if engine == "google":
        return "google." in host and "/search" not in path and "/url" not in path
    if engine == "bing":
        return "bing." in host and "/search" not in path
    if engine == "duckduckgo":
        return "duckduckgo." in host
    return False


# ─────────────────────────── Session navigateur ───────────────────────────
class BrowserSession:
    """Une session = un onglet isolé (contexte Chromium) dans le navigateur partagé."""

    def __init__(self, session_id: str, context, page):
        self.id = session_id
        self.context = context
        self.page = page
        self.created_at = time.time()
        self.last_activity = time.time()
        self.lock = asyncio.Lock()  # sérialise les actions sur CETTE session

    def touch(self):
        self.last_activity = time.time()

    async def close(self):
        try:
            await self.context.close()
        except Exception:
            pass

    async def snapshot(self, with_screenshot: bool = False) -> dict:
        """Ce qu'on 'voit' : URL, titre, textes, boutons, liens, champs (+ screenshot)."""
        data = await self.page.evaluate(SNAPSHOT_JS)
        snap = {
            "url": self.page.url,
            "title": data["title"],
            "texts": data["texts"],
            "buttons": data["buttons"],
            "links": data["links"],
            "inputs": data["inputs"],
            "taken_at": time.time(),
        }
        if with_screenshot:
            import base64
            png = await self.page.screenshot(type="png", full_page=False)
            snap["screenshot"] = "data:image/png;base64," + base64.b64encode(png).decode()
        return snap

    async def screenshot(self, full_page: bool = False) -> bytes:
        return await self.page.screenshot(type="png", full_page=full_page)

    async def _goto(self, url: str):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await self.page.wait_for_timeout(600)
        await self._try_dismiss_cookie_banners()

    async def _try_dismiss_cookie_banners(self):
        """Ferme les bandeaux cookies les plus courants (best effort)."""
        patterns = [
            "accept all", "tout accepter", "accepter tout", "j'accepte",
            "agree", "accept", "accepter", "ok", "continue",
        ]
        for pat in patterns:
            try:
                btn = self.page.get_by_role("button", name=re.compile(pat, re.I)).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=1500)
                    await self.page.wait_for_timeout(700)
                    break
            except Exception:
                continue

    async def navigate(self, url: str):
        url = url.strip()
        if not url:
            raise ActionError("L'URL est vide.")
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        await self._goto(url)

    async def search(self, query: str, engine: str = "google"):
        query = (query or "").strip()
        if not query:
            raise ActionError("La recherche est vide.")
        if engine not in SEARCH_URLS:
            raise ActionError(f"Moteur inconnu : {engine} (disponibles : {', '.join(SEARCH_URLS)})")
        url = SEARCH_URLS[engine].format(q=urllib.parse.quote(query))
        await self._goto(url)

    async def click(self, selector: str = None, text: str = None):
        if selector:
            loc = self.page.locator(selector).first
        elif text:
            loc = self.page.get_by_text(text, exact=False).first
        else:
            raise ActionError("Il faut fournir 'selector' ou 'text'.")
        try:
            await loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        await loc.click(timeout=5000)
        await self.page.wait_for_timeout(600)

    async def type_text(self, selector: str, text: str, submit: bool = False, clear: bool = False):
        if not selector:
            raise ActionError("Il faut fournir 'selector' (voir la liste des champs du snapshot).")
        loc = self.page.locator(selector).first
        await loc.scroll_into_view_if_needed(timeout=3000)
        if clear:
            await loc.fill(text)
        else:
            await loc.click(timeout=3000)
            await loc.press_sequentially(text, delay=12)
        if submit:
            await loc.press("Enter")
        await self.page.wait_for_timeout(500)

    async def press(self, key: str):
        await self.page.keyboard.press(key)
        await self.page.wait_for_timeout(400)

    async def scroll(self, direction: str = "down", amount: int = 500):
        amount = max(-5000, min(5000, int(amount)))
        if direction == "up":
            amount = -abs(amount)
        elif direction == "down":
            amount = abs(amount)
        elif direction == "top":
            await self.page.evaluate("window.scrollTo(0, 0)")
            return
        elif direction == "bottom":
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return
        else:
            raise ActionError("direction doit être 'up', 'down', 'top' ou 'bottom'.")
        await self.page.mouse.wheel(0, amount)
        await self.page.wait_for_timeout(300)

    async def go_back(self):
        await self.page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await self.page.wait_for_timeout(500)

    async def go_forward(self):
        await self.page.go_forward(wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await self.page.wait_for_timeout(500)

    async def reload(self):
        await self.page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await self.page.wait_for_timeout(500)


# ─────────────────────────── Gestionnaire de navigateur ───────────────────────────
class BrowserManager:
    """Un seul Chromium partagé, une session = un contexte isolé."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._launch_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self.sessions: dict[str, BrowserSession] = {}

    async def _ensure_browser(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._launch_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._pw is None:
                self._pw = await async_playwright().start()
            try:
                self._browser = await self._pw.chromium.launch(
                    headless=HEADLESS,
                    args=CHROMIUM_ARGS,
                )
            except Exception as e:
                raise ActionError(
                    "Impossible de démarrer Chromium. Vérifie qu'il est installé : "
                    "`playwright install chromium` (ou rebuild l'image Docker). "
                    f"Détail : {e}"
                ) from e
            print("🌐 Navigateur Chromium démarré" + (" (headless)" if HEADLESS else ""))
            return self._browser

    async def create_session(self) -> BrowserSession:
        async with self._lock:
            if len(self.sessions) >= MAX_SESSIONS:
                raise SessionLimitError(
                    f"Nombre maximum de sessions atteint ({MAX_SESSIONS}). "
                    "Ferme des sessions inutilisées ou augmente MAX_SESSIONS."
                )
            browser = await self._ensure_browser()
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="fr-FR",
                timezone_id="Europe/Paris",
                user_agent=USER_AGENT,
            )
            page = await context.new_page()
            session = BrowserSession(uuid.uuid4().hex[:10], context, page)
            self.sessions[session.id] = session
            print(f"🆕 Session ouverte : {session.id} ({len(self.sessions)} active(s))")
            return session

    def get(self, session_id: str) -> BrowserSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(
                f"Session '{session_id}' introuvable (fermée ou expirée). "
                "Crée une nouvelle session via POST /api/session."
            )
        return session

    async def close_session(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session is not None:
            await session.close()
            print(f"🗑️  Session fermée : {session_id}")

    async def cleanup_idle(self):
        """Ferme les sessions inactives depuis trop longtemps."""
        now = time.time()
        for sid, session in list(self.sessions.items()):
            if session.lock.locked():
                continue  # session en train de travailler
            if now - session.last_activity > SESSION_IDLE_TIMEOUT:
                print(f"⏳ Session inactive fermée : {sid}")
                await self.close_session(sid)

    async def close_all(self):
        for sid in list(self.sessions.keys()):
            await self.close_session(sid)
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass


# ─────────────────────────── Actions génériques ───────────────────────────
async def perform_action(session: BrowserSession, action: str, params: dict) -> dict:
    """Exécute une action sur une session et renvoie le snapshot après coup."""
    async with session.lock:
        session.touch()
        try:
            if action == "navigate":
                await session.navigate(params.get("url", ""))
            elif action == "search":
                await session.search(params.get("query", ""), params.get("engine", "google"))
            elif action == "click":
                await session.click(params.get("selector"), params.get("text"))
            elif action == "type":
                await session.type_text(
                    params.get("selector", ""),
                    params.get("text", ""),
                    submit=bool(params.get("submit", False)),
                    clear=bool(params.get("clear", False)),
                )
            elif action == "press":
                await session.press(params.get("key", ""))
            elif action == "scroll":
                await session.scroll(params.get("direction", "down"), int(params.get("amount", 500)))
            elif action == "back":
                await session.go_back()
            elif action == "forward":
                await session.go_forward()
            elif action == "reload":
                await session.reload()
            else:
                raise ActionError(
                    f"Action inconnue : '{action}'. Actions : "
                    "navigate, search, click, type, press, scroll, back, forward, reload."
                )
        except PlaywrightTimeoutError as e:
            raise ActionError(f"Timeout pendant l'action '{action}' : {e}") from e
        except BrowserError:
            raise
        except Exception as e:
            raise ActionError(f"Erreur pendant l'action '{action}' : {e}") from e

        return await session.snapshot(with_screenshot=bool(params.get("screenshot", False)))
