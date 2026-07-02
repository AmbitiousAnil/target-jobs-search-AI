FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY pyproject.toml README.md config.example.json ./
COPY autopilot_jobhunt ./autopilot_jobhunt
COPY job_hunt ./job_hunt
COPY skills ./skills

RUN pip install --no-cache-dir .
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "adk web --host 0.0.0.0 --port ${PORT:-8080} ."]
