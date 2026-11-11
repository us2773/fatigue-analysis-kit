FROM python:3.11-slim

WORKDIR /app
COPY fatigued-face-space/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY fatigued-face-space/pyproject.toml fatigued-face-space/README.md ./
COPY fatigued-face-space/src/ ./src/
COPY fatigued-face-space/conf/base/ ./conf/base/
RUN pip install --no-cache-dir --no-deps .
