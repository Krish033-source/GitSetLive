# NOTE: written for you but not built/tested in the environment where it was authored.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
RUN useradd -m -u 1000 app && mkdir /data && chown app:app /data
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Only needed for the "Our Servers" deploy engine (Node apps + public tunnel links).
# Build with:  docker build --build-arg WITH_OWN_SERVER=true -t gitsetlive-api .
# (the cloudflared binary below is for x86-64; use the arm64 build on ARM machines)
ARG WITH_OWN_SERVER=false
RUN if [ "$WITH_OWN_SERVER" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates \
      && curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      && chmod +x /usr/local/bin/cloudflared && rm -rf /var/lib/apt/lists/*; \
    fi

COPY . .
USER app
VOLUME /data
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','5000'))"
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-5000}"]
