FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV BIBLEIT_LIVE_HOST=0.0.0.0
ENV BIBLEIT_LIVE_PORT=8000
ENV BIBLEIT_SERVE_COMMAND="cd /app/python && /app/python/.venv/bin/python -m bibleit"
ENV BIBLEIT_SERVE_PUBLIC_URL=http://127.0.0.1:8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential make \
    && rm -rf /var/lib/apt/lists/*

COPY libbibleit ./libbibleit
COPY python ./python

WORKDIR /app/python

RUN make install-local

EXPOSE 8000

ENTRYPOINT ["make"]
CMD ["live"]
