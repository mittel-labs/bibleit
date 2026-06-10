FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV BIBLEIT_LIVE_HOST=0.0.0.0
ENV BIBLEIT_LIVE_PORT=8000
ENV BIBLEIT_LIVE_URL=http://127.0.0.1:8000

RUN pip install aiohttp

WORKDIR /app

COPY python/src /app

EXPOSE 8000

CMD ["python", "-m", "bibleit.live"]
