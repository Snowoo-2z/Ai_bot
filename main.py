from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import asyncio
from bot_logic import send_prompt_to_ai

app = FastAPI()

# Permet à ton frontend (même hébergé ailleurs) d'appeler cette API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre à ton domaine en prod si besoin
    allow_methods=["*"],
    allow_headers=["*"],
)

# Verrou global : un seul navigateur à la fois (comme tu le souhaites)
processing_lock = asyncio.Lock()

class PromptRequest(BaseModel):
    prompt: str
    system_prompt: str = ""

SECRET_KEY = os.getenv("MY_SECRET_KEY", "change-moi")

@app.post("/chat")
async def chat(request: PromptRequest, x_api_key: str = Header(None)):
    if x_api_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide")

    if processing_lock.locked():
        raise HTTPException(status_code=429, detail="Une requête est déjà en cours, réessaie dans quelques secondes.")

    async with processing_lock:
        try:
            response = await send_prompt_to_ai(request.prompt, request.system_prompt)
            return {"success": True, "response": response}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
