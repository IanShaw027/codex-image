# CLI reference (`scripts/codex_image.py`)

This skill is an explicit local CLI workflow. Use the bundled script directly instead of creating ad hoc runners.

## Commands

- `generate`: create a new image through `/v1/images/generations`
- `edit`: edit one or more existing local images through `/v1/images/edits`
- `generate-batch`: run many generation jobs from a JSONL file

## Quick start

Set a stable path to the skill:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_IMAGE="$CODEX_HOME/skills/codex-image/scripts/codex_image.py"
```

Generate:

```bash
python3 "$CODEX_IMAGE" generate \
  --model gpt-image-2 \
  --size 3840x2160 \
  "Draw a Doraemon-inspired large language model infographic, image only, no text"
```

Edit:

```bash
python3 "$CODEX_IMAGE" edit \
  --image ./input-a.png \
  --image ./input-b.png \
  "Change only the background to a bright blue futuristic scene; keep the subject unchanged"
```

Batch:

```bash
python3 "$CODEX_IMAGE" generate-batch \
  --input ./prompts.jsonl \
  --out-dir ./output/batch
```

## Wrappers

macOS and Linux:

```bash
"$CODEX_HOME/skills/codex-image/scripts/generate.sh" "Draw a clean futuristic AI wallpaper"
"$CODEX_HOME/skills/codex-image/scripts/edit.sh" --image ./input.png "Change only the background"
"$CODEX_HOME/skills/codex-image/scripts/generate-batch.sh" --input ./prompts.jsonl --out-dir ./output/batch
```

Windows:

```bat
%USERPROFILE%\.codex\skills\codex-image\scripts\generate.cmd "Draw a clean futuristic AI wallpaper"
%USERPROFILE%\.codex\skills\codex-image\scripts\edit.cmd --image input.png "Change only the background"
%USERPROFILE%\.codex\skills\codex-image\scripts\generate-batch.cmd --input prompts.jsonl --out-dir output\batch
```

## Core options

- `--model <images-model>`
- `--size <auto|WIDTHxHEIGHT|WIDTH:HEIGHT>`
- `--quality <low|medium|high|auto>`
- `--background <auto|opaque|transparent>`
- `--format <png|jpeg|webp>`
- `--compression <0-100>`
- `--moderation <auto|low>`
- `--n <1-10>`
- `--out <exact-output-file>`
- `--out-dir <directory>`
- `--name <readable-prefix>` for `generate`
- `--prompt-file <path>`
- `--dry-run`
- `--force`
- `--image <path>` repeated for `edit`
- `--mask <mask.png>` for `edit`
- `--input-fidelity <low|high>` for `edit`

## Size handling

- Valid direct sizes are sent as-is.
- Ratio input such as `16:9`, `9:16`, or `6:16` is converted to the largest valid direct size under the OpenAI image constraints.
- Invalid explicit sizes such as `1920x1080` are normalized to the nearest valid direct-request size before the request is sent.
- Request the final delivery size directly. Do not crop or upscale locally just to hit the target resolution.

Examples:

- `16:9` -> `3840x2160`
- `9:16` -> `2160x3840`
- `6:16` -> `1440x3840`
- `1920x1080` -> normalized to a valid nearby size before sending

## Output handling

- Default output base is `${CODEX_HOME:-~/.codex}/generated_images/`.
- Inside Codex, the default subdirectory is derived from `CODEX_THREAD_ID` or `CODEX_SESSION_ID`.
- Outside Codex, the default subdirectory is `manual/`.
- `--out` writes exactly where you point it.
- `--out-dir` is the simplest choice for multi-image results and batch runs.
- `--name` keeps the default directory and generates `name-randomsuffix.ext`.
- when `--n > 1`, numbered sibling files are created.

## Batch input

`generate-batch` reads one JSONL job per line.

String line:

```json
"Draw a clean futuristic AI wallpaper"
```

Object line:

```json
{"prompt":"Draw a clean futuristic AI wallpaper","size":"16:9","n":2,"quality":"high"}
```

Supported per-job overrides:

- `prompt`
- `model`
- `size`
- `quality`
- `background`
- `format`
- `compression`
- `moderation`
- `n`
- `name`
- `out`

## Logging

The script writes concise logs to stderr:

- request start with model, size, quality, format, background, and output path
- normalization notes when size input is adjusted
- HTTP status and byte count
- final saved path

## Authentication and runtime config

See `references/codex-network.md` for auth, base URL, and config resolution.

This script has no extra Python package dependency. For related workflows that need the OpenAI SDK or other packages, install them into `${CODEX_HOME:-$HOME/.codex}/.venv`.
