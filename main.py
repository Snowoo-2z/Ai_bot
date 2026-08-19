from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
import asyncio
import time
import uuid

from bot_logic import send_prompt_to_ai, TooManyRequestsError

SECRET_KEY = os.getenv("MY_SECRET_KEY", "change-moi")

# Ré-essai automatique après un "trop de demandes" (en minutes / nombre de relances max)
AUTO_RETRY_MINUTES = int(os.getenv("AUTO_RETRY_MINUTES", "3"))
MAX_AUTO_RETRIES = int(os.getenv("MAX_AUTO_RETRIES", "1"))
MAX_FINISHED_KEPT = int(os.getenv("MAX_FINISHED_KEPT", "200"))

app = FastAPI()

# Permet à ton frontend (même hébergé ailleurs) d'appeler cette API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre à ton domaine en prod si besoin
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────── File d'attente ───────────────────────────
queue: asyncio.Queue = asyncio.Queue()
jobs: dict = {}        # job_id -> job (état complet)
order: list = []       # ordre FIFO des job_id (pour calculer la place)


class PromptRequest(BaseModel):
    prompt: str
    system_prompt: str = ""


def _position(job_id: str):
    """Place dans la file : 1 = en cours de traitement, 2 = suivant, etc. (None si terminé)."""
    pending = [jid for jid in order if jobs[jid]["status"] in ("queued", "processing")]
    try:
        return pending.index(job_id) + 1
    except ValueError:
        return None


def _prune_jobs():
    """Garde en mémoire uniquement les N derniers jobs terminés (évite une fuite mémoire)."""
    finished = [jid for jid in order if jobs[jid]["status"] in ("done", "error")]
    if len(finished) <= MAX_FINISHED_KEPT:
        return
    drop = set(finished[: len(finished) - MAX_FINISHED_KEPT])
    for jid in drop:
        jobs.pop(jid, None)
    order[:] = [jid for jid in order if jid not in drop]


async def _enqueue(prompt: str, system_prompt: str, retry_of: str = None, retry_count: int = 0) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "status": "queued",
        "position": None,
        "result": None,
        "error": None,
        "retry_of": retry_of,
        "retry_count": retry_count,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    jobs[job_id] = job
    order.append(job_id)
    await queue.put(job_id)
    job["position"] = _position(job_id)
    return job_id


def _schedule_auto_retry(job: dict):
    """Reprogramme le prompt quelques minutes plus tard (limité par MAX_AUTO_RETRIES)."""
    if job.get("retry_count", 0) >= MAX_AUTO_RETRIES:
        return

    async def _retry_later():
        await asyncio.sleep(AUTO_RETRY_MINUTES * 60)
        await _enqueue(
            job["prompt"],
            job["system_prompt"],
            retry_of=job["id"],
            retry_count=job.get("retry_count", 0) + 1,
        )

    asyncio.create_task(_retry_later())


async def _worker():
    """Traite les jobs un par un (FIFO)."""
    while True:
        job_id = await queue.get()
        job = jobs.get(job_id)
        if job is None:
            queue.task_done()
            continue

        job["status"] = "processing"
        job["position"] = _position(job_id)
        job["started_at"] = time.time()
        try:
            job["result"] = await send_prompt_to_ai(job["prompt"], job["system_prompt"])
            job["status"] = "done"
        except TooManyRequestsError as e:
            job["status"] = "error"
            job["error"] = str(e)
            _schedule_auto_retry(job)
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"Erreur: {e}"
        finally:
            job["finished_at"] = time.time()
            queue.task_done()
            _prune_jobs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(_worker())
    yield
    worker.cancel()


app.router.lifespan_context = lifespan


# ─────────────────────────── Endpoints ───────────────────────────
@app.post("/chat")
async def chat(request: PromptRequest, x_api_key: str = Header(None)):
    if x_api_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide")
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Le prompt est vide")

    job_id = await _enqueue(request.prompt, request.system_prompt)
    job = jobs[job_id]
    return {
        "success": True,
        "queued": True,
        "job_id": job_id,
        "status": job["status"],
        "position": job["position"],
    }


@app.get("/status/{job_id}")
async def status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "position": _position(job_id),
        "result": job.get("result"),
        "error": job.get("error"),
        "retry_of": job.get("retry_of"),
    }


@app.get("/queue")
async def queue_status():
    pending = [jid for jid in order if jobs[jid]["status"] in ("queued", "processing")]
    return {
        "pending": len(pending),
        "total_tracked": len(order),
        "items": [
            {
                "job_id": jid,
                "status": jobs[jid]["status"],
                "position": _position(jid),
            }
            for jid in pending
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def read_index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
