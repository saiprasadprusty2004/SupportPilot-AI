FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANGGRAPH_STRICT_MSGPACK=true HF_HOME=/app/data/models OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
WORKDIR /app/backend
RUN groupadd --gid 10001 pilot && useradd --uid 10001 --gid pilot --create-home pilot
COPY backend/pyproject.toml ./
COPY backend/requirements.lock ./
COPY backend/app ./app
RUN pip install --no-cache-dir 'torch>=2.6,<3' --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.lock '.[embeddings]'
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY samples /app/samples
RUN mkdir -p /app/data/uploads && chown -R pilot:pilot /app
USER pilot
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
