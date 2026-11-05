FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
WORKDIR /app
# Debian slim images may not ship the IANA timezone database. The scheduler
# uses ZoneInfo("Africa/Cairo"), so install tzdata explicitly in the runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
# Keep every runtime adapter/module and its JSON registry in the image. In particular,
# qudron_worker imports continuity_store at startup; an explicit legacy file list
# silently omitted the new continuity and agent-fabric modules.
COPY *.py *.json ./
RUN mkdir -p /app/data /app/reports /app/logs
EXPOSE 8765
CMD ["python", "-u", "qudron_worker.py"]
