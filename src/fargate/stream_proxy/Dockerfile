# SSE proxy container (ARM64/Graviton, to match the rest of the stack).
#
# boto3 is pinned to a floor NEW enough for the AgentCore Payments data plane. A looser floor is a
# silent failure: an older botocore has no `list_payment_instruments`, and the call dies with
# `AttributeError: 'BedrockAgentCore' object has no attribute ...` at request time, not at build.
FROM public.ecr.aws/docker/library/python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

WORKDIR /app
RUN pip install --no-cache-dir \
    "boto3>=1.43.85" "fastapi>=0.115" "uvicorn[standard]>=0.34" "pyjwt[crypto]>=2.8" "httpx>=0.28" \
    && useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser main.py /app/main.py

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
USER appuser
# One worker: this task only shuttles bytes, and a single event loop keeps SSE ordering simple.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "300"]
