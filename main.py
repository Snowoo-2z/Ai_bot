"""API de contrôle d'un navigateur à distance.

Un autre site (ou une IA) appelle cette API avec des instructions
(navigation, recherche, clic, saisie...) ; l'API pilote un vrai navigateur
Chromium et renvoie ce que la page affiche : textes, boutons, liens,
champs de saisie et capture d'écran.
"""
import asyncio
import os
import re
import time

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from browser_api import (
    ActionError,
    BrowserManager,
    SessionLimitError,
    SessionNotFoundError,
    perform_action,
)

# Clé API requise par tous les appels (header x-api-key)
API_KEY = os.getenv("API_KEY", "") or os.getenv("MY_SECRET_KEY", "change-moi")

manager = BrowserManager()


# ─────────────────────────── Modèles de requête ───────────────────────────
class NavigateRequest(BaseModel):
    url: str


class SearchRequest(BaseModel):
    query: str
    engine: str = "google"


class ClickRequest(BaseModel):
    selector: str = None
    text: str = None


class TypeRequest(BaseModel):
    selector: str
    text: str
    submit: bool = False
    clear: bool = False


class PressRequest(BaseModel):
    key: str


class ScrollRequest(BaseModel):
    direction: str = "down"
    amount: int = 500


class GenericActionRequest(BaseModel):
    """Action générique : {action, ...paramètres} — accepte n'importe quel champ."""

    model_config = ConfigDict(extra="allow")
    action: str
    screenshot: bool = False


class TaskRequest(BaseModel):
    """Tâche autonome : {instruction, engine?} — fait la recherche et renvoie les résultats."""

    instruction: str
    engine: str = "google"


# ─────────────────────────── Auth & erreurs ───────────────────────────
def require_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide (header x-api-key).")


def _http_error(e: Exception) -> HTTPException:
    if isinstance(e, SessionNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, SessionLimitError):
        return HTTPException(status_code=429, detail=str(e))
    if isinstance(e, ActionError):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=500, detail=f"Erreur interne : {e}")


async def _run_action(session_id: str, action: str, params: dict) -> dict:
    try:
        session = manager.get(session_id)
        snapshot = await perform_action(session, action, params)
    except Exception as e:  # noqa: BLE001
        raise _http_error(e)
    return {
        "ok": True,
        "session_id": session_id,
        "action": action,
        "snapshot": snapshot,
    }


def _extract_query(instruction: str) -> str:
    """Extrait la requête de recherche d'une instruction en langage simple."""
    text = (instruction or "").strip()
    m = re.match(
        r"^(?:recherche\b|cherchez\b|cherche\b|trouvez\b|trouver\b|trouve\b"
        r"|look up\b|search for\b|find\b|look for\b)"
        r"\s*[:—-]?\s*(.*)$",
        text,
        re.IGNORECASE,
    )
    if m and m.group(1).strip():
        return m.group(1).strip()
    return text


async def _safe_title(session) -> str:
    try:
        return await session.page.title()
    except Exception:
        return ""


# ─────────────────────────── Cycle de vie ───────────────────────────
async def _cleanup_loop():
    while True:
        await asyncio.sleep(60)
        try:
            await manager.cleanup_idle()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup = asyncio.create_task(_cleanup_loop())
    yield
    cleanup.cancel()
    await manager.close_all()


app = FastAPI(title="Navigateur IA à distance", lifespan=lifespan)

# CORS ouvert : ton autre site peut appeler l'API depuis n'importe quel domaine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────── Endpoints sessions ───────────────────────────
@app.post("/api/session", dependencies=[Depends(require_key)])
async def create_session():
    try:
        session = await manager.create_session()
    except Exception as e:
        raise _http_error(e)
    snapshot = await session.snapshot()
    return {"ok": True, "session_id": session.id, "snapshot": snapshot}


@app.get("/api/sessions", dependencies=[Depends(require_key)])
async def list_sessions():
    now = time.time()
    items = []
    for sid, s in manager.sessions.items():
        items.append({
            "session_id": sid,
            "url": s.page.url,
            "title": await _safe_title(s),
            "created_at": s.created_at,
            "idle_seconds": int(now - s.last_activity),
        })
    return {"ok": True, "count": len(items), "sessions": items}


@app.get("/api/session/{session_id}", dependencies=[Depends(require_key)])
async def get_session(session_id: str):
    try:
        session = manager.get(session_id)
        snapshot = await session.snapshot(with_screenshot=True)
    except Exception as e:
        raise _http_error(e)
    return {"ok": True, "session_id": session_id, "snapshot": snapshot}


@app.get("/api/session/{session_id}/snapshot", dependencies=[Depends(require_key)])
async def get_snapshot(session_id: str):
    try:
        session = manager.get(session_id)
        snapshot = await session.snapshot(with_screenshot=True)
    except Exception as e:
        raise _http_error(e)
    return {"ok": True, "session_id": session_id, "snapshot": snapshot}


@app.get("/api/session/{session_id}/screenshot", dependencies=[Depends(require_key)])
async def get_screenshot(session_id: str, full: bool = False):
    try:
        session = manager.get(session_id)
        png = await session.screenshot(full_page=bool(full))
    except Exception as e:
        raise _http_error(e)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.delete("/api/session/{session_id}", dependencies=[Depends(require_key)])
async def delete_session(session_id: str):
    try:
        manager.get(session_id)
        await manager.close_session(session_id)
    except Exception as e:
        raise _http_error(e)
    return {"ok": True, "session_id": session_id, "closed": True}


# ─────────────────────────── Endpoints actions ───────────────────────────
@app.post("/api/session/{session_id}/navigate", dependencies=[Depends(require_key)])
async def navigate(session_id: str, req: NavigateRequest):
    return await _run_action(session_id, "navigate", req.model_dump())


@app.post("/api/session/{session_id}/search", dependencies=[Depends(require_key)])
async def search(session_id: str, req: SearchRequest):
    return await _run_action(session_id, "search", req.model_dump())


@app.post("/api/session/{session_id}/click", dependencies=[Depends(require_key)])
async def click(session_id: str, req: ClickRequest):
    return await _run_action(session_id, "click", req.model_dump())


@app.post("/api/session/{session_id}/type", dependencies=[Depends(require_key)])
async def type_text(session_id: str, req: TypeRequest):
    return await _run_action(session_id, "type", req.model_dump())


@app.post("/api/session/{session_id}/press", dependencies=[Depends(require_key)])
async def press(session_id: str, req: PressRequest):
    return await _run_action(session_id, "press", req.model_dump())


@app.post("/api/session/{session_id}/scroll", dependencies=[Depends(require_key)])
async def scroll(session_id: str, req: ScrollRequest):
    return await _run_action(session_id, "scroll", req.model_dump())


@app.post("/api/session/{session_id}/back", dependencies=[Depends(require_key)])
async def back(session_id: str):
    return await _run_action(session_id, "back", {})


@app.post("/api/session/{session_id}/forward", dependencies=[Depends(require_key)])
async def forward(session_id: str):
    return await _run_action(session_id, "forward", {})


@app.post("/api/session/{session_id}/reload", dependencies=[Depends(require_key)])
async def reload(session_id: str):
    return await _run_action(session_id, "reload", {})


@app.post("/api/session/{session_id}/action", dependencies=[Depends(require_key)])
async def generic_action(session_id: str, req: GenericActionRequest):
    params = dict(req.model_dump(exclude={"action", "screenshot"}))
    params = {k: v for k, v in params.items() if v is not None}
    if req.screenshot:
        params["screenshot"] = True
    return await _run_action(session_id, req.action, params)


# ─────────────────────────── Tâche autonome ───────────────────────────
@app.post("/api/task", dependencies=[Depends(require_key)])
async def run_task(req: TaskRequest):
    """Recherche autonome : {instruction} → fait la recherche et renvoie les
    résultats (titre + URL) plus le snapshot de la page de résultats."""
    query = _extract_query(req.instruction)
    if not query:
        raise HTTPException(status_code=400, detail="L'instruction est vide.")

    from browser_api import _clean_result_url, _is_engine_junk

    session = None
    try:
        session = await manager.create_session()
        await session.search(query, req.engine)
        snap = await session.snapshot()
        results = []
        for link in snap["links"]:
            if len(results) >= 10:
                break
            href = _clean_result_url(req.engine, link["href"])
            if _is_engine_junk(req.engine, href):
                continue
            results.append({"title": link["text"], "url": href})
        return {
            "ok": True,
            "instruction": req.instruction,
            "query": query,
            "engine": req.engine,
            "results": results,
            "snapshot": snap,
        }
    except Exception as e:
        raise _http_error(e)
    finally:
        if session is not None:
            await manager.close_session(session.id)


# ─────────────────────────── Divers ───────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(manager.sessions)}


@app.get("/")
async def read_index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
