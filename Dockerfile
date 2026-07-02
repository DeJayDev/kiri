# Build:  docker build -t kiri .
# Run:    docker run -v ~/.kiri:/root/.kiri kiri
# Config resolves from ~/.kiri/config.toml inside the container, or pass
# everything as -e env vars (env overrides TOML).
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# The shell tool only sees what's in this image; add the CLIs you want Kiri to
# have here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--no-sync", "kiri"]
