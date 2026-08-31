FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FIXTURES=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY datasets ./datasets
COPY experiments ./experiments
COPY apps ./apps

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "eve_miro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
