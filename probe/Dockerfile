ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm
FROM ${PYTHON_IMAGE}
ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN if [ -n "$APT_MIRROR" ]; then sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update && apt-get install -y --no-install-recommends iputils-ping mtr-tiny curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY probe/requirements.lock /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY common ./common
COPY probe ./probe
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
EXPOSE 8000
CMD ["uvicorn", "probe.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
