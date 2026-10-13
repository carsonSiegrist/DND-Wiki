FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid 10001 wiki \
    && useradd --uid 10001 --gid wiki --create-home --home-dir /home/wiki wiki

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=wiki:wiki . .
RUN chmod 0755 /app/deploy/entrypoint.sh

USER wiki

EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=1", "--threads=4", "--timeout=120", "--worker-tmp-dir=/tmp", "--access-logfile=-", "--error-logfile=-", "app:app"]
