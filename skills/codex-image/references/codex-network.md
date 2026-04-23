# Runtime, auth, and base URL notes

This skill is designed for Codex API key mode and OpenAI-compatible Images API endpoints.

## Auth and config precedence

Runtime values are resolved in this order:

1. `OPENAI_API_KEY`
2. provider-specific env key from `${CODEX_HOME:-~/.codex}/config.toml`
3. `${CODEX_HOME:-~/.codex}/auth.json`

Base URL precedence:

1. `OPENAI_BASE_URL`
2. active `model_provider` `base_url` from `${CODEX_HOME:-~/.codex}/config.toml`
3. top-level `openai_base_url` when the active provider is `openai`
4. no implicit fallback

## Supported Codex config behavior

- reads `${CODEX_HOME:-~/.codex}/config.toml`
- reads `${CODEX_HOME:-~/.codex}/auth.json`
- resolves active `model_provider`
- resolves `[model_providers.<id>].base_url`
- resolves `[model_providers.<id>].env_key`
- accepts either `https://host` or `https://host/v1`

## Relevant environment variables

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `CODEX_IMAGE_MODEL_PROVIDER`
- `CODEX_IMAGE_MODEL`
- `CODEX_IMAGE_SIZE`
- `CODEX_IMAGE_QUALITY`
- `CODEX_IMAGE_BACKGROUND`
- `CODEX_IMAGE_FORMAT`
- `CODEX_IMAGE_COMPRESSION`
- `CODEX_IMAGE_OUTPUT_DIR`
- `CODEX_IMAGE_TIMEOUT`

## Model mapping

- `CODEX_IMAGE_MODEL` is the primary Images API model setting
- if `${CODEX_HOME:-~/.codex}/config.toml` has a non-image default `model`, the skill ignores it and falls back to `gpt-image-2`
- in API key mode, a resolved base URL is mandatory; the script fails fast when neither `OPENAI_BASE_URL` nor a configured provider `base_url` is available

## Python and portability

- requires Python 3.11 or newer because the script uses `tomllib`
- uses only Python standard library modules
- works on macOS, Linux, and Windows without a mandatory virtual environment
- for related workflows that need packages such as `openai`, install them into `${CODEX_HOME:-~/.codex}/.venv`

## Common failure boundaries

- missing API key
- unsupported or invalid image size
- upstream does not implement `/v1/images/generations` or `/v1/images/edits`
- upstream request failure or moderation rejection
- server returning non-JSON payloads
