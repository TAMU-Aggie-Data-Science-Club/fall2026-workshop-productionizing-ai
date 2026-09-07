FROM python:3.11-slim

WORKDIR /app

# Cloud mode calls a managed LLM, but retrieval still needs the small local
# embedding model. Build that artifact once so a request never downloads model
# weights and the Cloud Run instance can start deterministically.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/huggingface \
    TRANSFORMERS_CACHE=/opt/huggingface/hub

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN NIMBUS_ALLOW_MODEL_DOWNLOAD=1 python data/build_index.py

# This image is the cloud artifact. The local Hugging Face generation models are
# intentionally not included, so a container started without Google settings
# should fail with a clear credentials error instead of trying the local path.
RUN addgroup --system nimbus \
    && adduser --system --ingroup nimbus nimbus \
    && chown -R nimbus:nimbus /app /opt/huggingface

USER nimbus

ENV NIMBUS_ALLOW_MODEL_DOWNLOAD=0 \
    NIMBUS_MODEL_BACKEND=google \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app:app --app-dir service --host 0.0.0.0 --port ${PORT:-8080}"]
