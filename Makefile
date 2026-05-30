# YazSes development Makefile
#
# Common targets:
#   make dev        — build (debug) + restart daemon
#   make release    — build (release) + restart daemon
#   make start      — start daemon (build first if binary missing)
#   make stop       — stop daemon
#   make restart    — stop + start (no rebuild)
#   make logs       — follow daemon logs
#   make status     — query running daemon over IPC
#   make test       — run full test suite
#   make check      — cargo check (fast, no binary)
#   make clean      — cargo clean

# ── Feature flags ─────────────────────────────────────────────────────────────
# Override on the command line: make dev FEATURES=moonshine,ollama
FEATURES        ?= moonshine,ollama

# ── Runtime paths (must match crates/yazses-core/src/config.rs) ───────────────
XDG_RUNTIME_DIR ?= /run/user/$(shell id -u)
RUNTIME_DIR     := $(XDG_RUNTIME_DIR)/yazses
PID_FILE        := $(RUNTIME_DIR)/daemon.pid
SOCK_FILE       := $(RUNTIME_DIR)/daemon.sock
LOG_FILE        := /tmp/yazses-daemon.log

# ── Binary paths ──────────────────────────────────────────────────────────────
DEBUG_BIN   := target/debug/yazses-daemon
RELEASE_BIN := target/release/yazses-daemon

# ── Env vars forwarded to the daemon process ──────────────────────────────────
DAEMON_ENV := YAZSES_MOONSHINE_MODEL=tiny-en YAZSES_LLM_MODEL=qwen2.5:1.5b

.PHONY: all dev release start stop restart logs status test check overlay clean help

all: dev

# ── Build + restart ───────────────────────────────────────────────────────────

dev: check-stop
	@echo "▶  Building (debug, features=$(FEATURES))…"
	cargo build -p yazses-core --features $(FEATURES)
	@$(MAKE) --no-print-directory _start BIN=$(DEBUG_BIN)

release: check-stop
	@echo "▶  Building (release, features=$(FEATURES))…"
	cargo build --release -p yazses-core --features $(FEATURES)
	@$(MAKE) --no-print-directory _start BIN=$(RELEASE_BIN)

# ── Daemon lifecycle ──────────────────────────────────────────────────────────

start:
	@if [ ! -f $(DEBUG_BIN) ] && [ ! -f $(RELEASE_BIN) ]; then \
		echo "No binary found — run 'make dev' first."; exit 1; \
	fi
	@BIN=$$([ -f $(RELEASE_BIN) ] && echo $(RELEASE_BIN) || echo $(DEBUG_BIN)); \
	$(MAKE) --no-print-directory _start BIN=$$BIN

stop: check-stop

restart: stop start

# Internal: actually launch the daemon in the background.
_start:
	@mkdir -p $(RUNTIME_DIR)
	@echo "▶  Starting $(BIN)…"
	@$(DAEMON_ENV) $(BIN) >> $(LOG_FILE) 2>&1 &
	@sleep 0.4
	@if pgrep -x yazses-daemon > /dev/null; then \
		echo "✓  Daemon started (pid $$(cat $(PID_FILE) 2>/dev/null || pgrep -x yazses-daemon))"; \
	else \
		echo "✗  Daemon failed to start — check $(LOG_FILE)"; exit 1; \
	fi

# Internal: stop daemon if it's running, no-op otherwise.
check-stop:
	@if pgrep -x yazses-daemon > /dev/null; then \
		echo "▶  Stopping daemon…"; \
		kill $$(cat $(PID_FILE) 2>/dev/null || pgrep -x yazses-daemon) 2>/dev/null || true; \
		sleep 0.6; \
		echo "✓  Daemon stopped"; \
	fi

# ── Observability ─────────────────────────────────────────────────────────────

logs:
	@echo "  Tailing $(LOG_FILE) — Ctrl-C to quit"
	@tail -f $(LOG_FILE)

status:
	@if pgrep -x yazses-daemon > /dev/null; then \
		echo '{"method":"status","params":{},"id":1}' | socat - UNIX-CONNECT:$(SOCK_FILE) 2>/dev/null \
		|| echo "Daemon is running but IPC not ready yet"; \
	else \
		echo "Daemon is not running"; \
	fi

# ── Quality ───────────────────────────────────────────────────────────────────

test:
	@echo "▶  Running tests…"
	cargo test --workspace

check:
	@echo "▶  Checking (features=$(FEATURES))…"
	cargo check -p yazses-core --features $(FEATURES)

overlay:
	@echo "▶  Running voice-activity overlay (needs the Python overlay extra)…"
	uv run --extra overlay yazses overlay

clean:
	cargo clean
	@rm -f $(LOG_FILE)

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  YazSes dev Makefile"
	@echo ""
	@echo "  make dev        build debug + restart daemon"
	@echo "  make release    build release + restart daemon"
	@echo "  make start      start daemon (no rebuild)"
	@echo "  make stop       stop daemon"
	@echo "  make restart    stop + start (no rebuild)"
	@echo "  make logs       follow daemon log at $(LOG_FILE)"
	@echo "  make status     query daemon over IPC"
	@echo "  make test       run full test suite"
	@echo "  make check      fast compile check"
	@echo "  make overlay    run the voice-activity overlay (Python)"
	@echo "  make clean      cargo clean"
	@echo ""
	@echo "  Override features:  make dev FEATURES=moonshine,whisper,ollama"
	@echo ""
