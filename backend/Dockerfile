# ---- Stage 1: Builder ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN uv pip install --system --no-cache --prerelease=allow -r requirements.txt

# Vendor the TikTok recorder into the image so it is always present,
# independent of the host filesystem / git state.
#
# Pinned to a specific commit SHA (rather than "main") for reproducible
# builds. This SHA is the commit tagged as the official "7.7.1" release,
# which contains the fix for a TikTok-side regression where the
# `webcast/room/check_alive` endpoint started reporting every room as
# `alive: true`, making is_room_alive() false-positive and start recordings
# for users who were not actually live (upstream issue #454). The 7.7.0
# release's first attempt at this fix was confirmed still broken by
# multiple reporters; 7.7.1 (this pin) was confirmed fixed. It also carries
# the "restricted LIVE" fallback (page-scraping when TikTok's webcast API
# returns status 4003110) — see recorder_service.get_live_url()'s `username`
# param, which is now threaded through so that fallback can actually engage.
# https://github.com/Michele0303/tiktok-live-recorder/releases/tag/7.7.1
ARG TIKTOK_RECORDER_REF=17ef2abfe7759944546a2545fe1a5cc1779ed388
RUN git init /app/tiktok-live-recorder && \
    cd /app/tiktok-live-recorder && \
    git remote add origin https://github.com/Michele0303/tiktok-live-recorder.git && \
    git fetch --depth 1 origin "${TIKTOK_RECORDER_REF}" && \
    git checkout FETCH_HEAD

COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY app/ ./app/

# ---- Stage 2: Runtime ----
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# glibc malloc gives every thread its own arena and seldom returns freed memory
# to the OS. This backend runs many threads (monitor, recording tasks, chat
# listeners, executors), so cap the arenas and trim free memory eagerly.
ENV MALLOC_ARENA_MAX=2
ENV MALLOC_TRIM_THRESHOLD_=131072

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /app /app

RUN mkdir -p /app/recordings /app/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
