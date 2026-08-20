"""Tests sans navigateur : fonctions pures, dispatch des actions, endpoints HTTP."""
import asyncio
import os
import unittest

os.environ.setdefault("API_KEY", "test-cle")

from fastapi.testclient import TestClient  # noqa: E402

import browser_api  # noqa: E402
import main  # noqa: E402


# ── Fonctions pures ──────────────────────────────────────────────────────
class TestPureFunctions(unittest.TestCase):
    def test_extract_query_fr(self):
        self.assertEqual(main._extract_query("cherche les horaires de la mairie"), "les horaires de la mairie")
        self.assertEqual(main._extract_query("Recherche : meteo rochefort"), "meteo rochefort")
        self.assertEqual(main._extract_query("trouve un plombier à Soubise"), "un plombier à Soubise")
        self.assertEqual(main._extract_query("Trouver—horaires trains"), "horaires trains")

    def test_extract_query_en(self):
        self.assertEqual(main._extract_query("search for paris weather"), "paris weather")
        self.assertEqual(main._extract_query("look up python docs"), "python docs")

    def test_extract_query_fallback(self):
        self.assertEqual(main._extract_query("météo Bordeaux"), "météo Bordeaux")

    def test_clean_result_url(self):
        self.assertEqual(
            browser_api._clean_result_url("google", "https://www.google.com/url?q=https%3A%2F%2Fexemple.fr%2Fpage&sa=U"),
            "https://exemple.fr/page",
        )
        self.assertEqual(
            browser_api._clean_result_url("google", "https://exemple.fr/page"),
            "https://exemple.fr/page",
        )

    def test_is_engine_junk(self):
        self.assertFalse(browser_api._is_engine_junk("google", "https://www.google.com/search?q=test"))
        self.assertTrue(browser_api._is_engine_junk("google", "https://www.google.com/preferences"))
        self.assertFalse(browser_api._is_engine_junk("google", "https://exemple.fr/article"))
        self.assertTrue(browser_api._is_engine_junk("duckduckgo", "https://duckduckgo.com/?q=test"))
        self.assertFalse(browser_api._is_engine_junk("duckduckgo", "https://exemple.fr/article"))


# ── Dispatch des actions (sessions factices) ─────────────────────────────
class FakeSession:
    def __init__(self):
        self.calls = []
        self.lock = asyncio.Lock()

    def touch(self):
        pass

    async def snapshot(self, with_screenshot=False):
        return {"url": "https://exemple.fr", "title": "T", "texts": [], "buttons": [], "links": [], "inputs": [], "screenshot": None}

    async def navigate(self, url):
        self.calls.append(("navigate", url))

    async def search(self, query, engine):
        self.calls.append(("search", query, engine))

    async def click(self, selector, text):
        self.calls.append(("click", selector, text))

    async def type_text(self, selector, text, submit=False, clear=False):
        self.calls.append(("type", selector, text, submit, clear))

    async def image_search(self, query, engine):
        self.calls.append(("image_search", query, engine))

    async def upload(self, selector, url, data_base64, filename):
        self.calls.append(("upload", selector, url, data_base64, filename))


class TestPerformAction(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_dispatch(self):
        s = FakeSession()
        snap = self.run_async(browser_api.perform_action(s, "search", {"query": "test", "engine": "bing"}))
        self.assertEqual(s.calls, [("search", "test", "bing")])
        self.assertEqual(snap["url"], "https://exemple.fr")

    def test_unknown_action(self):
        s = FakeSession()
        with self.assertRaises(browser_api.ActionError):
            self.run_async(browser_api.perform_action(s, "explose", {}))

    def test_screenshot_flag(self):
        s = FakeSession()
        snap = self.run_async(browser_api.perform_action(s, "navigate", {"url": "https://x.fr", "screenshot": True}))
        self.assertEqual(snap["screenshot"], None)  # pas de navigateur → pas de PNG, pas d'erreur

    def test_image_search_dispatch(self):
        s = FakeSession()
        self.run_async(browser_api.perform_action(s, "image_search", {"query": "chats", "engine": "bing"}))
        self.assertEqual(s.calls, [("image_search", "chats", "bing")])

    def test_upload_dispatch(self):
        s = FakeSession()
        self.run_async(browser_api.perform_action(s, "upload", {"selector": "input[type=file]", "url": "https://x.fr/i.png"}))
        self.assertEqual(s.calls, [("upload", "input[type=file]", "https://x.fr/i.png", None, None)])

    def test_upload_without_source(self):
        s = FakeSession()
        with self.assertRaises(browser_api.ActionError):
            self.run_async(browser_api.perform_action(s, "upload", {"selector": "input[type=file]"}))

    def test_guess_ext(self):
        self.assertEqual(browser_api._guess_ext("https://x.fr/photo.JPG?w=100"), ".jpg")
        self.assertEqual(browser_api._guess_ext("https://x.fr/a.png"), ".png")
        self.assertEqual(browser_api._guess_ext("https://x.fr/a", "image/webp"), ".webp")
        self.assertEqual(browser_api._guess_ext("https://x.fr/a"), ".png")


# ── Endpoints HTTP ───────────────────────────────────────────────────────
class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Navigateur IA à distance", r.text)

    def test_unauthorized(self):
        for path, method in [("/api/session", "POST"), ("/api/sessions", "GET"), ("/api/task", "POST")]:
            kwargs = {"json": {}} if method == "POST" else {}
            r = getattr(self.client, method.lower())(path, **kwargs)
            self.assertEqual(r.status_code, 401, path)

    def test_session_not_found(self):
        r = self.client.get("/api/session/inconnue", headers={"x-api-key": "test-cle"})
        self.assertEqual(r.status_code, 404)

    def test_validation_error(self):
        r = self.client.post(
            "/api/session/inconnue/navigate",
            json={"url": 42},
            headers={"x-api-key": "test-cle"},
        )
        self.assertEqual(r.status_code, 422)

    def test_task_empty(self):
        r = self.client.post("/api/task", json={"instruction": "   "}, headers={"x-api-key": "test-cle"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
