FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY clip_bridge ./clip_bridge

RUN pip install --no-cache-dir .

RUN useradd --system --uid 10001 --create-home clipper \
    && mkdir -p /data \
    && chown -R clipper:clipper /data

USER clipper

ENV PEERTUBE_CLIPPER_DATABASE=/data/peertube-clipper.sqlite3

EXPOSE 18100

CMD ["uvicorn", "clip_bridge.main:app", "--host", "0.0.0.0", "--port", "18100"]
