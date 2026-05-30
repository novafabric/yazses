# Contributing to YazSes

Thank you for your interest in contributing. YazSes has two parallel implementations — Rust (v1.0, default) and Python (v0.4.x) — so most contributions will target one or the other.

## Getting started

```sh
git clone https://github.com/novafabric/yazses
cd yazses
```

### Rust (v1.0)

```sh
cargo build                   # build all crates
cargo test --workspace        # run all tests (~94)
cargo clippy --workspace      # lints
```

Optional feature flags: `--features whisper`, `--features moonshine`, `--features llama-cpp`, `--features ollama`, `--features silero`.

### Python (v0.4.x)

```sh
uv sync
uv run pytest tests/ -v       # run all tests (~246)
uv run ruff check src tests   # lints
uv run mypy src               # type checking
```

## Before opening a pull request

- Run the test suite and confirm it passes.
- For new features, add tests.
- Keep PRs focused — one concern per PR.
- Describe the *why* in the PR body, not just the *what*.

## Reporting bugs

Open an issue at https://github.com/novafabric/yazses/issues and include:
- OS and version
- `yazses --version` output
- Steps to reproduce
- Relevant lines from `yazses logs`

## Platform support

If you are adding support for a new platform or injection backend, implement all relevant Protocol interfaces and add a test. See `crates/yazses-inputs/src/protocol.rs` (Rust) or `src/yazses/platform/base.py` (Python) for the interface contracts.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
