FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home api
WORKDIR /app
COPY api/ ./api/
RUN pip install --no-cache-dir ./api
USER api
EXPOSE 8000
CMD ["uvicorn", "fatigue_analysis_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
