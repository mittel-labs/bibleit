# Build from the repository root so the server can compile the sibling
# libbibleit dependency:
# docker build -f server/Dockerfile -t bibleit-server .
FROM erlang:27-alpine AS build

RUN apk add --no-cache build-base make rebar3

WORKDIR /app
COPY libbibleit ./libbibleit
COPY server ./server
COPY config ./config

RUN make -C server release

FROM erlang:27-alpine

RUN apk add --no-cache openssh-keygen \
    && addgroup -S bibleit && adduser -S -G bibleit bibleit \
    && mkdir -p /app /data \
    && chown -R bibleit:bibleit /app /data

WORKDIR /app
COPY --from=build --chown=bibleit:bibleit /app/server/_build/prod/rel/bibleit_server ./
COPY --from=build --chown=bibleit:bibleit /app/server/docs ./docs
COPY --chown=bibleit:bibleit server/docker-entrypoint.sh ./docker-entrypoint.sh

RUN chmod 0555 ./docker-entrypoint.sh

USER bibleit

ENV BIBLEIT_SERVER_PORT=7070 \
    BIBLEIT_SERVER_BIND_ADDRESS=0.0.0.0 \
    BIBLEIT_HTTP_PORT=8080 \
    BIBLEIT_HTTP_BIND_ADDRESS=0.0.0.0 \
    BIBLEIT_HTTP_SECURE_COOKIES=false \
    BIBLEIT_DATA_DIR=/data \
    BIBLEIT_PROXY_PROTOCOL=false \
    BIBLEIT_SSH_PORT=2222 \
    BIBLEIT_SSH_SYSTEM_DIR=/data/ssh

VOLUME ["/data"]
EXPOSE 7070 8080 2222

ENTRYPOINT ["/app/docker-entrypoint.sh"]
