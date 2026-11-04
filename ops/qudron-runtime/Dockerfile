FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY qudron_worker.py schedule.json ./
RUN mkdir -p /app/data /app/reports /app/logs
EXPOSE 8765
CMD ["python", "-u", "qudron_worker.py"]
