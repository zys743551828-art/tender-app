# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm
ARG LO_VERSION=4:7.4.7-1+deb12u14
RUN apt-get update \
 && apt-get install --no-install-recommends -y "libreoffice-writer-nogui=${LO_VERSION}" fonts-noto-cjk=1:20220127+repack1-1 fonts-liberation=1:1.07.4-11 fontconfig \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --only-binary=:all: pypdfium2==5.13.0 \
 && mkdir -p /word-input /word-output /app /work \
 && chown 10001:10001 /word-input \
 && chown 65534:65534 /word-output \
 && chmod 0755 /word-input /word-output
WORKDIR /app
COPY inspection.py landlock.py child.py renderer.py service.py manifest.py validator.py ./
RUN python manifest.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp LANG=C.UTF-8
USER 65534:65534
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s CMD ["python", "/app/service.py", "--health"]
CMD ["python", "/app/service.py"]
