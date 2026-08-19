# Base Debian (bookworm) + Python 3.13 — compatible Playwright
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) Dépendances Python (versions épinglées dans requirements.txt)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Chromium + ses dépendances système.
#    Dans un build Docker on est root, donc --with-deps fonctionne
#    (c'est ce qui échouait sur l'environnement natif Render).
RUN playwright install --with-deps chromium

# 3) Code de l'application
COPY . .

# Render injecte $PORT automatiquement (10000 par défaut)
EXPOSE 10000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
