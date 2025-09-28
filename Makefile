.PHONY: up-embedded down-embedded logs-embedded test-embedded \
        up-minimal down-minimal logs-minimal test-minimal \
        local-provider local-provider-down local-test

# -------- Embedded (single container: markitdown + embedded bgutil) --------

up-embedded:
	cd docker/embedded && docker compose up --build -d

down-embedded:
	cd docker/embedded && docker compose down --remove-orphans

logs-embedded:
	cd docker/embedded && docker compose logs --tail=120

test-embedded:
	cd docker/embedded && \
	  docker compose exec markitdown sh -lc "curl -sf http://127.0.0.1:4416/ping | head -c 200 && echo" && \
	  docker compose exec markitdown sh -lc "uv run main.py --test https://example.com | head -n 30"

# -------- Minimal (split containers: markitdown + bgutil-provider) --------

up-minimal:
	cd docker/minimal && docker compose up --build -d

down-minimal:
	cd docker/minimal && docker compose down --remove-orphans

logs-minimal:
	cd docker/minimal && docker compose logs --tail=120

test-minimal:
	cd docker/minimal && \
	  docker compose exec bgutil-provider sh -lc "curl -sf http://localhost:4416/ping | head -c 200 && echo" && \
	  docker compose exec markitdown sh -lc "printenv | grep -E '^YTDLP_BGUTIL_POT_PROVIDER_URL=' || true; uv run main.py --test https://example.com | head -n 30"

# -------- Local (no container for markitdown) --------

local-provider:
	@docker ps --format '{{.Names}}' | grep -q '^bgutil-provider$$' || \
	  docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider

local-provider-down:
	-@docker rm -f bgutil-provider 2>/dev/null || true

local-test: local-provider
	export YTDLP_BGUTIL_POT_PROVIDER_URL=http://127.0.0.1:4416; \
	  uv run main.py --test https://example.com | head -n 30

