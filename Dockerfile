FROM python:3.12-slim

WORKDIR /app

# stock-report-style Codex CLI bridge for report/wiki fallback generation.
# Authentication is supplied at runtime (mounted ~/.codex or CODEX_API_KEY);
# no credentials are baked into the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && npm install --global --no-fund --no-audit @openai/codex@0.151.0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY scripts/ scripts/

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
