# ─────────────────────────────────────────────────────────────────────────────
# Lumiq — Multi-stage Dockerfile
#
# Stage 1 (builder): Install Python deps into a virtualenv
# Stage 2 (runtime): Minimal runtime image — only copies the venv and app code
#
# Build:
#   docker build -t lumiq:latest .
#
# Run (standalone Flask + SocketIO):
#   docker run -p 5000:5000 --env-file .env lumiq:latest
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System deps for psycopg2 (libpq), matplotlib, and wordcloud
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libfreetype6-dev \
        libpng-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only requirements first — maximises Docker layer caching
COPY requirements.txt .

# Create isolated virtualenv and install deps
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK corpora (baked into image so workers don't fetch at runtime)
RUN python -c "\
import nltk; \
nltk.download('stopwords', quiet=True); \
nltk.download('wordnet',   quiet=True); \
nltk.download('omw-1.4',   quiet=True)"


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Only the runtime libs needed by compiled packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libfreetype6 \
        libpng16-16 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd -m -u 1001 lumiq

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
# Copy NLTK data downloaded in builder
COPY --from=builder /root/nltk_data /home/lumiq/nltk_data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NLTK_DATA="/home/lumiq/nltk_data"

# Copy application source
COPY --chown=lumiq:lumiq . .

# Create runtime directories
RUN mkdir -p uploads static/outputs logs data \
 && chown -R lumiq:lumiq uploads static/outputs logs data

USER lumiq

# Health check — verifies Flask is serving HTTP
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

EXPOSE 5000

# Default: start Flask + SocketIO via gevent
CMD ["python", "-c", \
     "from app import socketio, app; socketio.run(app, host='0.0.0.0', port=5000, use_reloader=False)"]
