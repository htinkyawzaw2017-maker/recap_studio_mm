# ── Recap Studio MM — production image ──────────────────────────────────────
# Runs the FastAPI + ffmpeg pipeline. Works on AWS ECS/Fargate, EC2, Render,
# Fly.io and any other Docker host. Bind is always 0.0.0.0:$PORT.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    RECAP_DATA_DIR=/data \
    PORT=8000

# ffmpeg/ffprobe + Myanmar capable fonts (bundled fonts are also shipped in
# assets/fonts, the system fonts are a second safety net for libass).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-noto-core \
      fonts-sil-padauk \
      tini \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# writable runtime data (mount an EBS/EFS volume here on AWS for persistence)
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data/workspace /data/output /app/workspace /app/output \
 && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 30"]
