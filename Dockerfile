FROM python:3.11.15-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/cowork \
    HERMES_HOME=/data/hermes \
    HERMES_PYTHON=/usr/local/bin/python \
    COWORK_DATABASE_PATH=/data/cowork.db

WORKDIR /app

RUN groupadd --gid 1000 cowork \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/cowork cowork \
    && install -d -o 1000 -g 1000 -m 0700 /data

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    "hermes-agent[mcp]==0.19.0" .

USER 1000:1000

EXPOSE 8080

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
