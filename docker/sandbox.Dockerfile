# Sandbox image for model-written Python (chart_codegen, shop_codeact, humaneval, mbpp).
# Built by `make sandbox-image`; `arena run/ui --sandbox auto` uses it when Docker is running.
# Containers run with --network none, a memory/CPU/process limit, all capabilities dropped.
FROM python:3.12-slim
RUN pip install --no-cache-dir "matplotlib==3.9.*" "pandas==2.2.*" "numpy==2.*"
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
