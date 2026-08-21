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
# Proxy optionnel pour les sessions (ex: IP résidentielle).
# Format : http://user:pass@host:port ou host:port
BROWSER_PROXY = os.getenv("BROWSER_PROXY", "")

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}

SEARCH_IMAGE_URLS = {
    "google": "https://www.google.com/search?q={q}&tbm=isch",
    "bing": "https://www.bing.com/images/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}&iax=images&ia=images",
}

# Filtres "usage rights" des moteurs (BEST EFFORT — basés sur ce que les
# sites déclarent, pas une garantie légale. Voir README.)
_LICENSE_TBS = {"free": "sur:f", "commercial": "sur:fc"}  # Google Images
_LICENSE_BING = {
    "free": "filterui:license-share",
    "commercial": "filterui:license-sharecommercial",
}  # Bing Images

# Sources d'images garanties libres (licence renvoyée pour chaque image)
FREE_IMAGE_SOURCES = ("openverse", "commons")

# Extension de fichier déduite d'une URL ou d'un content-type
_CTYPE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
}


def _guess_ext(url: str = "", content_type: str = "") -> str:
    """Devine l'extension d'une image à partir de son URL ou de son content-type."""
    m = re.search(r"\.(png|jpe?g|gif|webp|avif|bmp|svg)$", (url or "").split("?")[0].lower())
    if m:
        ext = m.group(1)
        return ".jpg" if ext == "jpeg" else "." + ext
    for ctype, ext in _CTYPE_EXT.items():
        if ctype in (content_type or "").lower():
            return ext
    return ".png"

# ─────────────── Recherche d'images libres de droit ───────────────
# Openverse (Creative Commons) et Wikimedia Commons renvoient la LICENCE
# exacte de chaque image — contrairement aux moteurs classiques, on sait ce
# qu'on a le droit de faire (afficher, modifier, usage commercial, attribution).


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def _fetch_json(url: str, timeout: int = 25) -> dict:
    """GET JSON simple (stdlib) — exécuté hors de l'event loop via to_thread."""
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RemoteBrowserAPI/1.0 (https://github.com/Snowoo-2z/Ai_bot)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return _json.loads(resp.read().decode("utf-8"))


def _parse_openverse(data: dict) -> list:
    """Parse la réponse de l'API Openverse → images avec licence."""
    images = []
    for r in (data.get("results") or []):
        images.append({
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "thumbnail": r.get("thumbnail") or "",
            "license": r.get("license") or "inconnue",
            "license_url": r.get("license_url") or "",
            "creator": r.get("creator") or "",
            "source": r.get("source") or "openverse",
        })
    return images


def _parse_commons(data: dict, usage: str = "any") -> list:
    """Parse la réponse de l'API Wikimedia Commons → images avec licence.

    usage == "commercial" : exclut les licences avec clause NC (non commercial).
    """
    images = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        ext = info.get("extmetadata", {}) or {}
        lic = ((ext.get("LicenseShortName") or {}).get("value") or "").strip()
        if usage == "commercial" and re.search(r"\bnc\b|noncommercial", lic, re.IGNORECASE):
            continue
        images.append({
            "title": page.get("title", ""),
            "url": info.get("url", ""),
            "thumbnail": info.get("thumburl", ""),
            "license": lic or "inconnue",
            "license_url": ((ext.get("LicenseUrl") or {}).get("value") or "").strip(),
            "creator": _strip_html((ext.get("Artist") or {}).get("value", "")),
            "source": "wikimedia_commons",
        })
    return images


async def free_image_search(query: str, source: str = "auto", usage: str = "any", limit: int = 10) -> dict:
    """Recherche d'images librement réutilisables, avec la licence de chacune.

    source : "openverse" (Creative Commons) | "commons" (Wikimedia Commons) | "auto"
    usage  : "any" | "commercial" (exclut les licences non commerciales)
    """
    query = (query or "").strip()
    if not query:
        raise ActionError("La recherche d'images libres est vide.")
    if usage not in ("any", "free", "commercial"):
        raise ActionError("usage doit être 'any', 'free' ou 'commercial'.")
    limit = max(1, min(int(limit), 50))
    if source == "auto":
        source = "openverse"
    if source not in FREE_IMAGE_SOURCES:
        raise ActionError(f"source inconnue : {source} (disponibles : openverse, commons, auto)")

    try:
        if source == "openverse":
            lic_type = "commercial" if usage == "commercial" else "all"
            url = (
                "https://api.openverse.org/v1/images/?q=" + urllib.parse.quote(query)
                + f"&page_size={limit}&license_type={lic_type}"
            )
            data = await asyncio.to_thread(_fetch_json, url)
            images = _parse_openverse(data)
        else:
            url = (
                "https://commons.wikimedia.org/w/api.php?action=query&format=json"
                f"&generator=search&gsrsearch={urllib.parse.quote(query)}&gsrnamespace=6"
                f"&gsrlimit={limit}&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=800"
            )
            data = await asyncio.to_thread(_fetch_json, url)
            images = _parse_commons(data, usage)
    except ActionError:
        raise
    except Exception as e:
        raise ActionError(f"Recherche d'images libres impossible ({source}) : {e}") from e

    return {"source": source, "usage": usage, "images": images}


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
# boutons, liens, champs de saisie et images.
SNAPSHOT_JS = r"""() => {
    const MAX_TEXTS = 40, MAX_LINKS = 60, MAX_BUTTONS = 60, MAX_INPUTS = 30, MAX_IMAGES = 60;
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
        const tag = el.tagName;
        const type = el.type || (tag === 'TEXTAREA' ? 'textarea' : tag === 'SELECT' ? 'select' : 'text');
        if (['hidden', 'submit', 'button', 'checkbox', 'radio'].includes(type)) return;
        // les inputs fichier sont souvent masqués visuellement mais restent utilisables
        if (type !== 'file' && !isVisible(el)) return;
        let selector = '';
        if (el.id) selector = '#' + CSS.escape(el.id);
        else if (el.name) selector = el.tagName.toLowerCase() + '[name="' + String(el.name).replace(/"/g, '\\"') + '"]';
        else if (el.placeholder) selector = el.tagName.toLowerCase() + '[placeholder="' + String(el.placeholder).replace(/"/g, '\\"') + '"]';
        inputs.push({
            type,
            placeholder: String(el.placeholder || el.getAttribute('aria-label') || el.name || (type === 'file' ? 'fichier' : '')).slice(0, 100),
            selector,
            value: String(el.value || '').slice(0, 100),
        });
    });

    const images = [];
    const seenImages = new Set();
    const pushImg = (url, thumb, alt, w, h) => {
        if (!url || images.length >= MAX_IMAGES) return;
        if (url.startsWith('data:') || url.length > 4000) return;
        if (seenImages.has(url)) return;
        seenImages.add(url);
        images.push({ url, thumb: thumb || url, alt: alt || '', width: w || 0, height: h || 0 });
    };
    // Bing Images : <a class="iusc" data-m='{"murl":"...","turl":"...","t":"..."}'>
    document.querySelectorAll('a[data-m]').forEach((a) => {
        try {
            const d = JSON.parse(a.getAttribute('data-m'));
            if (d && d.murl) pushImg(d.murl, d.turl, d.t || '', d.mw, d.mh);
        } catch (e) {}
    });
    // Google Images : img[data-iurl] = URL directe de l'image, img[data-src] = lazy loading
    document.querySelectorAll('img[data-iurl]').forEach((img) => {
        pushImg(img.getAttribute('data-iurl'), img.currentSrc || img.src, img.alt, img.naturalWidth, img.naturalHeight);
    });
    document.querySelectorAll('img[data-src]').forEach((img) => {
        const r = img.getBoundingClientRect();
        if (r.width < 60 || r.height < 60) return;
        pushImg(img.getAttribute('data-src'), img.currentSrc || img.src, img.alt, img.naturalWidth, img.naturalHeight);
    });
    // Générique : images visibles assez grandes (logos, icônes exclus)
    document.querySelectorAll('img').forEach((img) => {
        const r = img.getBoundingClientRect();
        if (r.width < 80 || r.height < 80) return;
        pushImg(img.currentSrc || img.src, img.src, img.alt, img.naturalWidth, img.naturalHeight);
    });

    return { title: document.title, texts, buttons, links, inputs, images };
}"""


def _clean_result_url(engine: str, href: str) -> str:
    """Nettoie les URL de résultats (ex. lien de redirection Google)."""
    if "google." in href and "/url?" in href:
        m = re.search(r"[?&]q=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    return href


def _parse_proxy(proxy_str: str):
    """Transforme 'http://user:pass@host:port' (ou 'host:port') en config Playwright."""
    s = (proxy_str or "").strip()
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    parts = urllib.parse.urlsplit(s)
    server = parts.scheme + "://" + parts.hostname
    if parts.port:
        server += ":" + str(parts.port)
    proxy = {"server": server}
    if parts.username:
        proxy["username"] = urllib.parse.unquote(parts.username)
    if parts.password:
        proxy["password"] = urllib.parse.unquote(parts.password)
    return proxy


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


def _image_search_url(query: str, engine: str, license_filter: str = "any") -> str:
    """URL de recherche d'images, avec filtre de licence si demandé.

    license_filter : "any" | "free" | "commercial" (best effort, voir README).
    """
    if engine not in SEARCH_IMAGE_URLS:
        raise ActionError(f"Moteur inconnu : {engine} (disponibles : {', '.join(SEARCH_IMAGE_URLS)})")
    if license_filter not in ("any", "free", "commercial"):
        raise ActionError("license doit être 'any', 'free' ou 'commercial'.")
    url = SEARCH_IMAGE_URLS[engine].format(q=urllib.parse.quote(query))
    if license_filter == "any":
        return url
    if engine == "google":
        return url + "&tbs=" + _LICENSE_TBS[license_filter]
    if engine == "bing":
        return url + "&qft=+" + _LICENSE_BING[license_filter]
    raise ActionError(
        "DuckDuckGo n'a pas de filtre de licence. Utilise plutôt l'endpoint "
        "/api/freeimages (Openverse / Wikimedia Commons) pour des images libres."
    )


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

    async def image_search(self, query: str, engine: str = "google", license_filter: str = "any"):
        """Recherche d'images (Google Images / Bing Images / DuckDuckGo Images).

        license_filter : "any" | "free" | "commercial" — filtre "usage rights"
        des moteurs (best effort, pas une garantie légale — voir README).
        Le snapshot renvoyé contient la liste `images` : {url, thumb, alt, width, height}.
        """
        query = (query or "").strip()
        if not query:
            raise ActionError("La recherche d'images est vide.")
        url = _image_search_url(query, engine, license_filter)
        await self._goto(url)
        # laisse les vignettes se charger (lazy loading des moteurs d'images)
        await self.page.wait_for_timeout(2500)
        await self._human_scroll_peek()

    async def _human_scroll_peek(self):
        """Petit défilement pour déclencher le lazy loading des images."""
        try:
            await self.page.mouse.wheel(0, 500)
            await self.page.wait_for_timeout(1200)
            await self.page.mouse.wheel(0, 500)
            await self.page.wait_for_timeout(800)
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

    async def upload(self, selector: str, url: str = None, data_base64: str = None, filename: str = None):
        """Envoie une image (URL ou base64) dans un champ fichier de la page."""
        if not selector:
            raise ActionError("Il faut fournir 'selector' (un input[type=file] du snapshot).")
        if not url and not data_base64:
            raise ActionError("Il faut fournir 'url' ou 'data_base64'.")

        import base64 as _b64
        import binascii

        body = b""
        ext = ""
        if url:
            resp = await self.context.request.get(url.strip(), timeout=NAV_TIMEOUT)
            if not resp.ok:
                raise ActionError(f"Téléchargement de l'image échoué : HTTP {resp.status}")
            body = await resp.body()
            ext = _guess_ext(url, resp.headers.get("content-type", ""))
        else:
            raw = data_base64.split(",", 1)[-1] if "," in data_base64 else data_base64
            try:
                body = _b64.b64decode(raw)
            except (binascii.Error, ValueError) as e:
                raise ActionError(f"data_base64 invalide : {e}") from e
            ext = _guess_ext(data_base64.split(",", 1)[0], "")

        name = (filename or "").strip()
        if name:
            import posixpath
            name = posixpath.basename(name)
            if not re.search(r"\.\w+$", name):
                name += ext
        else:
            name = "upload" + ext

        tmp_path = os.path.join("/tmp", f"upload_{uuid.uuid4().hex[:8]}_{name}")
        with open(tmp_path, "wb") as f:
            f.write(body)
        try:
            loc = self.page.locator(selector).first
            await loc.set_input_files(tmp_path, timeout=8000)
        except PlaywrightTimeoutError as e:
            raise ActionError(f"Champ fichier introuvable/inaccessible ({selector}) : {e}") from e
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        await self.page.wait_for_timeout(600)

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

    async def wait_for(self, selector: str = None, text: str = None, timeout_ms: int = 15000, sleep_ms: int = 0):
        """Attend qu'un élément soit visible, ou fait une simple pause.

        Indispensable pour les pages JavaScript : naviguer → attendre un texte
        → re-snapshot. Sans 'selector' ni 'text', attend sleep_ms millisecondes.
        """
        if sleep_ms:
            await self.page.wait_for_timeout(max(0, int(sleep_ms)))
            return
        if selector:
            loc = self.page.locator(selector).first
        elif text:
            loc = self.page.get_by_text(text, exact=False).first
        else:
            raise ActionError("Il faut fournir 'selector' ou 'text' (ou 'sleep_ms').")
        try:
            await loc.wait_for(state="visible", timeout=max(1000, int(timeout_ms)))
        except PlaywrightTimeoutError as e:
            raise ActionError(
                f"Élément introuvable après {timeout_ms} ms : {selector or text}"
            ) from e

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
                    proxy=_parse_proxy(BROWSER_PROXY),
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
            elif action == "image_search":
                await session.image_search(
                    params.get("query", ""),
                    params.get("engine", "google"),
                    params.get("license", "any"),
                )
            elif action == "upload":
                if not params.get("selector"):
                    raise ActionError("Il faut fournir 'selector' (un input[type=file] du snapshot).")
                if not params.get("url") and not params.get("data_base64"):
                    raise ActionError("Il faut fournir 'url' ou 'data_base64'.")
                await session.upload(
                    params.get("selector", ""),
                    params.get("url"),
                    params.get("data_base64"),
                    params.get("filename"),
                )
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
            elif action == "wait":
                await session.wait_for(
                    params.get("selector"),
                    params.get("text"),
                    int(params.get("timeout_ms", 15000)),
                    int(params.get("sleep_ms", 0)),
                )
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
                    "navigate, search, image_search, upload, click, type, press, wait, "
                    "scroll, back, forward, reload."
                )
        except PlaywrightTimeoutError as e:
            raise ActionError(f"Timeout pendant l'action '{action}' : {e}") from e
        except BrowserError:
            raise
        except Exception as e:
            raise ActionError(f"Erreur pendant l'action '{action}' : {e}") from e

        return await session.snapshot(with_screenshot=bool(params.get("screenshot", False)))
