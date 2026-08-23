FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY clip_bridge ./clip_bridge

# Install a wheel into site-packages, then remove the build-source copy.
# This prevents restrictive checkout/build-context modes (for example from
# umask 077) from shadowing the installed package when the runtime switches
# to the unprivileged clipper user.
RUN pip install --no-cache-dir . \
    && rm -rf /app/clip_bridge /app/pyproject.toml

RUN useradd --system --uid 10001 --create-home clipper \
    && mkdir -p /data \
    && chown -R clipper:clipper /data

USER clipper
WORKDIR /data

ENV PEERTUBE_CLIPPER_DATABASE=/data/peertube-clipper.sqlite3

EXPOSE 18100

CMD ["uvicorn", "clip_bridge.main:app", "--host", "0.0.0.0", "--port", "18100"]
