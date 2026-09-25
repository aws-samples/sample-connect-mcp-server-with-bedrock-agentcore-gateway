# ARM64 (Graviton) — AgentCore Runtime will NOT start an x86 image.
# Build context is THIS directory (src/agentcore/runtime/demo_agent), never the repo root (keeps the asset hash small).
FROM public.ecr.aws/docker/library/python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The Claude Agent SDK spawns the `claude` CLI subprocess, so the image needs Node + that CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Route the model to Bedrock instead of the Anthropic API.
ENV CLAUDE_CODE_USE_BEDROCK=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/demo_agent/requirements.txt
RUN pip install --no-cache-dir -r /app/demo_agent/requirements.txt

# Copy the agent package (this build context) to /app/demo_agent so `python -m demo_agent.app` resolves.
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . /app/demo_agent/

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3)"]
USER appuser
CMD ["python", "-m", "demo_agent.app"]
