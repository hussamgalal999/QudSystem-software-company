FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
WORKDIR /app
# Debian slim images may not ship the IANA timezone database. The scheduler
# uses ZoneInfo("Africa/Cairo"), so install tzdata explicitly in the runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY qudron_worker.py telegram_gateway.py swarm_engine.py payment_guard.py github_inventory.py metricool_client.py vision_adapter.py deepseek_web.py capability_registry.py schedule.json agent_registry.json service_workflows.json ./
RUN mkdir -p /app/data /app/reports /app/logs
EXPOSE 8765
CMD ["python", "-u", "qudron_worker.py"]
