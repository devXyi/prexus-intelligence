# Raksha image. Build context: repository root.   docker build -f modules/raksha/Dockerfile -t raksha .
# (Not built in the authoring sandbox — Docker unavailable; the same `pip install` steps and the
#  uvicorn entrypoint are exercised by modules/raksha/tests.)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RAKSHA_DATA_DIR=/var/lib/raksha RAKSHA_ENV=production
RUN useradd --system --uid 10002 --home /app prexus && mkdir -p /var/lib/raksha && chown prexus /var/lib/raksha
WORKDIR /app
COPY packages/prexus_core /app/packages/prexus_core
COPY modules/raksha /app/modules/raksha
RUN pip install --no-cache-dir /app/packages/prexus_core /app/modules/raksha "uvicorn>=0.30"
USER prexus
EXPOSE 8002
CMD ["uvicorn", "--factory", "raksha.serve:app", "--host", "0.0.0.0", "--port", "8002", "--no-server-header"]
