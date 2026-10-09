ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
WORKDIR /app
COPY backend/requirements.lock /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend ./backend
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
EXPOSE 8080
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
