FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e ".[web,embeddings]"

ENV PROFSEARCH_DB_PATH=/data/profsearch.db

EXPOSE 8001

CMD ["profsearch", "web", "--host", "0.0.0.0", "--port", "8001", "--read-only"]
