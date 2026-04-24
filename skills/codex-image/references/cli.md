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

Use `edit` whenever image files are provided as references. The multipart Images API uses repeated `image` fields for multiple inputs; JSON-only examples may call this an `images` array, but multipart requests should not rename the field to `images`.

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
- `--size <auto|WIDTHxHEIGHT|WIDTH:HEIGHT|WIDTH:HEIGHT@1k|1k@WIDTH:HEIGHT>`
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
- Ratio plus tier input such as `9:16@1k`, `9:16 1k`, or `1k@9:16` is local CLI syntax, not Images API syntax. The CLI resolves it to a direct `WIDTHxHEIGHT` before sending the API request.
- Tier names use the short edge as the target baseline: `1k` means short edge around `1024`, `2k` around `2048`, and `4k` around `4096`, then the result is adjusted to the nearest valid API size under the configured constraints.
- For direct sizes, the CLI also appends a final-canvas constraint to the prompt so the model is asked to compose for the intended final delivery dimensions.
- Explicit `WIDTHxHEIGHT` sizes are passed to the API unchanged, including non-standard sizes such as `1000x1800`.
- Explicit non-standard sizes remain the final delivery target. If the API returns a different pixel size with a close aspect ratio, the saved output is verified and resized back to the requested dimensions locally.
- If the returned aspect ratio differs materially from the requested final size, the CLI fails instead of stretching. The next step should be a user/model decision: retry generation with stronger prompt constraints, crop to cover, pad to contain, or force stretch.
- Request the final delivery size directly. Do not crop or upscale locally just to hit the target resolution.

Examples:

- `16:9` -> `3840x2160`
- `9:16` -> `2160x3840`
- `6:16` -> `1440x3840`
- `9:16@1k` -> `1008x1792`
- `9:16@2k` -> `2016x3584`
- `9:16@4k` -> `2160x3840` due to the maximum-edge and maximum-pixel constraints
- `1000x1800` -> sent to the API as `1000x1800`; if the returned file differs, resize locally to `1000x1800`

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
