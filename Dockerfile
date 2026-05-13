FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV BIBLEIT_SERVE_HOST=0.0.0.0
ENV BIBLEIT_SERVE_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential make \
    && rm -rf /var/lib/apt/lists/*

COPY libbibleit ./libbibleit
COPY python ./python

WORKDIR /app/python

RUN make install-local

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["run"]