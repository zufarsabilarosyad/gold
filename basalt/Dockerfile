FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN python -m pip install \
    setuptools==70.1.0 \
    wheel==0.43.0 \
    pydantic==2.7.4 \
    pydantic-settings==2.3.4 \
    fastapi==0.111.1 \
    "uvicorn[standard]==0.30.1" \
    "SQLAlchemy[asyncio]==2.0.31" \
    aiosqlite==0.20.0 \
    click==8.1.7 \
    httpx==0.27.0 \
    croniter==2.0.5 \
    PyYAML==6.0.1 \
    python-dateutil==2.9.0.post0 \
    pytest==8.2.2 \
    pytest-asyncio==0.23.7 \
    pytest-cov==5.0.0 \
    pytest-json-report==1.5.0 \
    ruff==0.4.10 \
    mypy==1.10.1 \
    types-PyYAML==6.0.12.20240311 \
    types-python-dateutil==2.9.0.20240316
