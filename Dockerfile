# CryptoCensus worker/coordinator/analyzer image.
# One image serves every role; the role is chosen by the CLI subcommand.
# Dependencies are installed from the committed uv.lock for a reproducible build;
# all third-party tools are pinned by version.
FROM python:3.12-slim

# Pinned uv (Astral) — fast, lockfile-driven dependency installation.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /bin/

ARG CRANE_VERSION=0.21.6
ARG SYFT_VERSION=1.44.0
ARG GITLEAKS_VERSION=8.30.1
ARG CBOM_LENS_VERSION=1.0.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# crane: daemonless image pull + flatten.
RUN curl -fsSL "https://github.com/google/go-containerregistry/releases/download/v${CRANE_VERSION}/go-containerregistry_Linux_x86_64.tar.gz" \
      | tar -xz -C /usr/local/bin crane

# syft: SBOM / crypto-library inventory (optional extractor).
RUN curl -fsSL "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" \
      | tar -xz -C /usr/local/bin syft

# gitleaks: private-key/secret sweep.
RUN curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
      | tar -xz -C /usr/local/bin gitleaks

# CBOM-Lens: independent CycloneDX-CBOM extractor (third-party divergence party).
RUN curl -fsSL -o /usr/local/bin/cbom-lens \
      "https://github.com/OmniTrustILM/cbom-lens/releases/download/${CBOM_LENS_VERSION}/cbom-lens-${CBOM_LENS_VERSION}-linux-amd64" \
 && chmod +x /usr/local/bin/cbom-lens

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
# Install dependencies first (cached layer), then the project, both from the lockfile.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    CC_WORK_DIR=/tmp/cryptocensus \
    PYTHONUNBUFFERED=1
ENTRYPOINT ["cryptocensus"]
CMD ["--help"]
