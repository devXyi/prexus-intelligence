# Meteorium engine image — builds the Rust core into a wheel, then ships only the runtime.
# Build context: data-engine/        docker build -t meteorium-engine data-engine
# (Not built in the authoring sandbox — Docker was unavailable; each step was verified by hand:
#  `maturin build --release`, `pip install` of the wheel, `uvicorn layer6.api:app` under pytest.)
FROM python:3.12-slim AS rust-build
ENV CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup PATH=/opt/cargo/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.85.1 \
 && pip install --no-cache-dir "maturin>=1.5,<2"
WORKDIR /src
COPY rust/ ./rust/
RUN cd rust && maturin build --release -o /wheels

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 METEORIUM_BASE=/var/lib/meteorium PORT=8001
RUN useradd --system --uid 10001 --home /app prexus && mkdir -p /var/lib/meteorium && chown prexus /var/lib/meteorium
WORKDIR /app
COPY python/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=rust-build /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
COPY python/ ./
USER prexus
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8001')+'/health',timeout=2)"
# ENGINE_SECRET (or ENGINE_SECRET_FILE) is mandatory: the app refuses to boot without it.
CMD ["sh", "-c", "exec uvicorn layer6.api:app --host 0.0.0.0 --port ${PORT:-8001} --no-server-header"]
