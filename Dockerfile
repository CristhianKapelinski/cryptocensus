# CryptoCensus worker/coordinator/analyzer image.
# One image serves every role; the role is chosen by the CLI subcommand.
# Dependencies are installed from the committed uv.lock for a reproducible build;
# all third-party tools are pinned by version.
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

# Pinned uv (Astral) — fast, lockfile-driven dependency installation.
COPY --from=ghcr.io/astral-sh/uv:0.11.17@sha256:03bdc89bb9798628846e60c3a9ad19006c8c3c724ccd2985a33145c039a0577b /uv /uvx /bin/

ARG CRANE_VERSION=0.21.6
ARG SYFT_VERSION=1.44.0
ARG GITLEAKS_VERSION=8.30.1
ARG CBOM_LENS_VERSION=1.0.0
# SHA256 of each pinned release asset, verified before extraction.
ARG CRANE_SHA256=7ebbdcd05b652345c1f5105f8475e518534b90d66f3bdb50017be63f426ea435
ARG SYFT_SHA256=0e91737aee2b5baf1d255b959630194a302335d848ff97bb07921eb6205b5f5a
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG CBOM_LENS_SHA256=a53b184e7fb2759d483dd2535bdc38d11a0da691bebe470a2efc6d2225efbb14

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# crane: daemonless image pull + flatten.
RUN curl -fsSL -o /tmp/crane.tgz "https://github.com/google/go-containerregistry/releases/download/v${CRANE_VERSION}/go-containerregistry_Linux_x86_64.tar.gz" \
 && echo "${CRANE_SHA256}  /tmp/crane.tgz" | sha256sum -c - \
 && tar -xz -C /usr/local/bin -f /tmp/crane.tgz crane \
 && rm /tmp/crane.tgz

# syft: SBOM / crypto-library inventory (optional extractor).
RUN curl -fsSL -o /tmp/syft.tgz "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" \
 && echo "${SYFT_SHA256}  /tmp/syft.tgz" | sha256sum -c - \
 && tar -xz -C /usr/local/bin -f /tmp/syft.tgz syft \
 && rm /tmp/syft.tgz

# gitleaks: private-key/secret sweep.
RUN curl -fsSL -o /tmp/gitleaks.tgz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
 && echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tgz" | sha256sum -c - \
 && tar -xz -C /usr/local/bin -f /tmp/gitleaks.tgz gitleaks \
 && rm /tmp/gitleaks.tgz

# CBOM-Lens: independent CycloneDX-CBOM extractor (third-party divergence party).
RUN curl -fsSL -o /usr/local/bin/cbom-lens \
      "https://github.com/OmniTrustILM/cbom-lens/releases/download/${CBOM_LENS_VERSION}/cbom-lens-${CBOM_LENS_VERSION}-linux-amd64" \
 && echo "${CBOM_LENS_SHA256}  /usr/local/bin/cbom-lens" | sha256sum -c - \
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
