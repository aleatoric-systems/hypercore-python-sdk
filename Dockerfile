FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md CHANGELOG.md PROJECT_STATE.md ./
COPY hypercore_sdk ./hypercore_sdk
COPY examples ./examples

FROM base AS runtime

RUN python -m pip install --upgrade pip \
    && python -m pip install .

ENTRYPOINT ["hypercore-sdk"]
CMD ["--help"]

FROM base AS dev

COPY tests ./tests

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[dev]"

CMD ["pytest", "-q"]
