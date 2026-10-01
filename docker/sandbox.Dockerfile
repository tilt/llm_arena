# Sandbox image for model-written Python (chart_codegen, shop_codeact, humaneval, mbpp).
# Built by `make sandbox-image`; `arena run/ui --sandbox auto` uses it when Docker is running.
# Containers run with --network none, a memory/CPU/process limit, all capabilities dropped.
# python:3.12.14-slim (multi-platform index published by the Docker Official Image)
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN pip install --no-cache-dir "matplotlib==3.11.2" "pandas==3.0.6" "numpy==2.5.3"
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
