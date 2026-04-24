# codex-image

`codex-image` is a Codex skill for local saved-file image generation and editing.
It gives Codex installed launcher paths, exact output-file control, batch jobs,
explicit thread image references, and API-key-mode HTTP access for OpenAI-
compatible image endpoints.

It is not a replacement for the built-in/system `imagegen` runtime tool.
Instead, the two paths are intentionally split:

- built-in `imagegen` for native current-turn image context and the fastest
  normal image conversation flow
- `codex-image` for local files, exact output paths/sizes, API key mode, batch
  jobs, and explicit image reuse semantics

The published skill lives at [`skills/codex-image`](./skills/codex-image).

Suggested GitHub topics: `codex`, `codex-skill`, `image-generation`, `openai`, `openai-images-api`, `gpt-image-2`, `images-api`, `python-cli`.

## Why use codex-image

- It is purpose-built for Codex API key mode when the built-in image tool is unavailable or not being used.
- It reads Codex-friendly auth and provider settings from environment variables, `$CODEX_HOME/auth.json`, and `$CODEX_HOME/config.toml`.
- It writes generated or edited images to deterministic local files instead of relying on inline image output.
- It supports practical delivery sizes, ratio shortcuts, multi-image edits, masks, `input_fidelity`, and JSONL batch generation.
- It supports explicit thread-local reuse such as `[Last Output]`, `[Turn -K Image #N]`, and `--image-set ...`.

## What it supports

- `generate`: create a new image, defaulting to `POST /v1/images/generations`
- `edit`: edit or synthesize from one or more input images, defaulting to `POST /v1/images/edits`
- `generate-batch`: run many generation jobs from a JSONL file
- Explicit `POST /v1/responses` fallback via `--transport responses` for prior-response image state
- Config and auth discovery from `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `$CODEX_HOME/auth.json`, and `$CODEX_HOME/config.toml`
- Direct size requests, including explicit non-standard values such as `1000x1800`
- Ratio-style input such as `16:9`, `9:16`, and `6:16`, normalized into valid image sizes
- Ratio-tier input such as `9:16@1k`, `9:16@2k`, and `9:16@4k`, resolved before calling the API
- Multi-image reference/edit requests, optional edit mask, and `input_fidelity`
- Thread-aware explicit image reuse through placeholders and image sets
- Saved-output dimension verification with safe post-processing for close aspect-ratio mismatches
- Multi-image output with `--n`
- Cross-platform scripts for macOS, Linux, and Windows

## Positioning

- Use built-in/system `imagegen` first when the user wants the normal native
  image conversation path:
  - current-turn image context
  - fastest simple generate/edit
  - natural multi-turn continuation
- Use `codex-image` when the user wants:
  - local saved files
  - exact output path or output directory
  - API key mode
  - custom `OPENAI_BASE_URL`
  - batch jobs
  - explicit image reuse such as `[Last Output]`
- `codex-image` returns saved files on disk. It does not provide native built-in
  inline image output.
- `codex-image` can approximate thread-aware image reuse, but it is still a
  local skill workflow rather than a runtime-native image tool.

For the full architectural comparison, see
[docs/image-workflows.md](./docs/image-workflows.md).

That document now also includes:

- concrete request-shape-to-scenario mapping
- when to use built-in `imagegen`
- when to use `codex-image`
- why some flows are better in one path than the other

## Install

### Option 1: Official skill-installer with repo and path

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo IanShaw027/codex-image \
  --path skills/codex-image
```

### Option 2: Official skill-installer with GitHub URL

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --url https://github.com/IanShaw027/codex-image/tree/main/skills/codex-image
```

### Option 3: Manual install

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/IanShaw027/codex-image.git /tmp/codex-image
cp -R /tmp/codex-image/skills/codex-image "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart Codex after installation.

## Configuration

Preferred runtime sources:

1. `OPENAI_API_KEY`
2. `OPENAI_BASE_URL`
3. `${CODEX_HOME:-~/.codex}/auth.json`
4. `${CODEX_HOME:-~/.codex}/config.toml`

Optional environment variables:

- `CODEX_IMAGE_MODEL`
- `CODEX_IMAGE_SIZE`
- `CODEX_IMAGE_QUALITY`
- `CODEX_IMAGE_BACKGROUND`
- `CODEX_IMAGE_FORMAT`
- `CODEX_IMAGE_COMPRESSION`
- `CODEX_IMAGE_OUTPUT_DIR`
- `CODEX_IMAGE_TIMEOUT`
- `CODEX_IMAGE_MODEL_PROVIDER`

Model behavior:

- `CODEX_IMAGE_MODEL` is the Images API model, such as `gpt-image-2`
- The default transport is the Images API
- An explicit Responses transport is available when prior response image state
  is part of the task
- In API key mode, `OPENAI_BASE_URL` or an equivalent provider `base_url` is required

Dependency note:

- `codex-image` itself uses Python standard library only
- Python 3.11 or newer is required
- when a related workflow needs Python deps such as the OpenAI SDK, install them into `${CODEX_HOME:-$HOME/.codex}/.venv`

## Usage

Generate a 4K image directly:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate \
  --model gpt-image-2 \
  --size 3840x2160 \
  "Draw a Doraemon-inspired large language model infographic, image only, no text"
```

Generate from an aspect ratio:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate \
  --size 16:9 \
  "Draw a clean futuristic AI wallpaper"
```

Generate from a ratio tier:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate \
  --size '9:16@1k' \
  "Create a vertical mobile livestream screenshot mockup"
```

Generate with an explicit non-standard delivery size:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate \
  --size 1000x1800 \
  "Create a vertical promotional poster"
```

Edit:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" edit \
  --model gpt-image-2 \
  --image ./input.png \
  --prompt "Keep the subject and change the background to a bright blue futuristic scene"
```

Edit with a mask:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" edit \
  --image ./input.png \
  --mask ./mask.png \
  --input-fidelity high \
  "Replace only the masked area with a futuristic blue glow"
```

Create a new promotional image from multiple input references:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" edit \
  --image ./person.png \
  --image ./bag.png \
  --size 16:9 \
  "Input image 1 role: person reference. Input image 2 role: handbag product reference. Create a polished commercial promotional image showing the person from input image 1 holding the handbag from input image 2. No logos, no readable text, no watermark."
```

Use `edit`, not `generate`, whenever image files are provided for the model to see. Multiple input files are sent as repeated multipart `image` fields.
If `generate` is called with `--image`, the CLI warns and reroutes the request to `edit`.

Continue refining a prior response explicitly:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" edit \
  --transport responses \
  --previous-response-id resp_123 \
  --prompt "Keep the composition and make it more realistic"
```

Generate multiple variants from one prompt:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate \
  --size 16:9 \
  --n 3 \
  --out-dir ./output/variants \
  "Draw a clean futuristic AI wallpaper"
```

Batch generate from JSONL:

```bash
bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image" generate-batch \
  --input ./prompts.jsonl \
  --out-dir ./output/batch
```

The POSIX launcher auto-selects a usable Python 3.11+ interpreter from a small known list or `CODEX_IMAGE_PYTHON`; invoke it through `bash` so ZIP-based installs do not depend on the executable bit. On Windows, use `codex-image.cmd`, which accepts `%CODEX_HOME%\skills\codex-image\scripts\codex-image.cmd` or `%USERPROFILE%\.codex\skills\codex-image\scripts\codex-image.cmd`. Once Codex routes into this skill, usually run the launcher first and let the script report missing credentials or unsupported runtime details; reach for config/auth files or `--help` only when the launcher is missing or its failure still leaves the command shape unclear.

## Output paths

- Inside Codex, default output is `${CODEX_HOME:-~/.codex}/generated_images/<thread-or-session-id>/`
- Outside Codex, default output is `${CODEX_HOME:-~/.codex}/generated_images/manual/`
- `--out` writes to an exact file path
- `--out-dir` is the simplest choice for multi-image output and batch runs
- `--name` keeps the default output directory and adds a readable prefix plus a random suffix
- `--n > 1` writes numbered sibling files
- Unlike the built-in image tool, standalone CLI runs do not have a real `<call_id>` segment

## Repository layout

```text
codex-image/
├── README.md
├── LICENSE
├── tests/
└── skills/
    └── codex-image/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── assets/
        ├── references/
        └── scripts/
```

## Testing

Run the repo tests from the repository root:

```bash
/opt/homebrew/bin/python3.12 -m unittest discover -s ./tests -p 'test_*.py'
```

## Skill docs

- Main skill entry: [`skills/codex-image/SKILL.md`](./skills/codex-image/SKILL.md)
- Workflow comparison: [`docs/image-workflows.md`](./docs/image-workflows.md)
- CLI reference: [`skills/codex-image/references/cli.md`](./skills/codex-image/references/cli.md)
- Transport parameter reference: [`skills/codex-image/references/image-api.md`](./skills/codex-image/references/image-api.md)
- Prompt guidance: [`skills/codex-image/references/prompting.md`](./skills/codex-image/references/prompting.md)
- Sample prompts: [`skills/codex-image/references/sample-prompts.md`](./skills/codex-image/references/sample-prompts.md)
- Runtime/auth notes: [`skills/codex-image/references/codex-network.md`](./skills/codex-image/references/codex-network.md)
