FROM node:24-alpine AS ui-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/study-tutor/.cache/huggingface

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin study-tutor && \
    mkdir -p /home/study-tutor/.cache/huggingface && \
    chown -R study-tutor:study-tutor /home/study-tutor/.cache

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY --chown=study-tutor:study-tutor . .
COPY --from=ui-build --chown=study-tutor:study-tutor /frontend/dist ./frontend/dist

USER study-tutor
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8501"]
