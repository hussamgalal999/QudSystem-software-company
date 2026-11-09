FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
WORKDIR /app
# Debian slim images may not ship the IANA timezone database. The scheduler
# uses ZoneInfo("Africa/Cairo"), so install tzdata explicitly in the runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
# Include runtime modules and only the JSON configuration required at startup.
# The connected-account GitHub repository inventory is intentionally excluded:
# its snapshot contains private repository names and belongs in the owner-scoped
# inventory store, not in a general runtime image.
COPY *.py ./
COPY schedule.json agent_registry.json service_workflows.json model_provider_catalog.json compute_provider_catalog.json ./
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/data /app/reports /app/logs
EXPOSE 8765
CMD ["python", "-u", "qudron_worker.py"]
