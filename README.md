# codex-image

`codex-image` is a Codex skill for image generation and editing through the OpenAI Images API when Codex is connected in API key mode and the built-in image tool path is unavailable or not being used.

It keeps the Codex-specific config/output experience that the system `imagegen` skill does not provide, while intentionally narrowing the transport to `/v1/images/generations` and `/v1/images/edits`.

The published skill lives at [`skills/codex-image`](./skills/codex-image).

## What it supports

- `generate`: create a new image through `/v1/images/generations`
- `edit`: edit one or more local images through `/v1/images/edits`
- `generate-batch`: run many generation jobs from a JSONL file
- Config and auth discovery from `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `$CODEX_HOME/auth.json`, and `$CODEX_HOME/config.toml`
- Direct valid-size requests, including 4K outputs such as `3840x2160`
- Ratio-style input such as `16:9`, `9:16`, and `6:16`, normalized into valid OpenAI image sizes
- Multi-image edit, optional edit mask, and `input_fidelity`
- Multi-image output with `--n`
- Cross-platform scripts for macOS, Linux, and Windows

## Positioning

- Use the built-in/system `imagegen` skill first when Codex can access the built-in image tool.
- Use `codex-image` when Codex is in API key mode and the built-in image tool is unavailable, or when the user explicitly wants the local script path with Codex config/output conventions.
- This skill is Images API only. It does not implement `Responses + image_generation`.
- This skill returns saved files on disk. It does not provide inline built-in image output.

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
- This skill no longer uses a separate Responses model layer
- In API key mode, `OPENAI_BASE_URL` or an equivalent provider `base_url` is required

Dependency note:

- `codex-image` itself uses Python standard library only
- when a related workflow needs Python deps such as the OpenAI SDK, install them into `${CODEX_HOME:-$HOME/.codex}/.venv`

## Usage

Generate a 4K image directly:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" generate \
  --model gpt-image-2 \
  --size 3840x2160 \
  "Draw a Doraemon-inspired large language model infographic, image only, no text"
```

Generate from an aspect ratio:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" generate \
  --size 16:9 \
  "Draw a clean futuristic AI wallpaper"
```

Edit:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" edit \
  --model gpt-image-2 \
  --image ./input.png \
  "Keep the subject and change the background to a bright blue futuristic scene"
```

Edit with a mask:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" edit \
  --image ./input.png \
  --mask ./mask.png \
  --input-fidelity high \
  "Replace only the masked area with a futuristic blue glow"
```

Edit with multiple input images:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" edit \
  --image ./ref-a.png \
  --image ./ref-b.png \
  "Blend both references into one polished product image"
```

Generate multiple variants from one prompt:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" generate \
  --size 16:9 \
  --n 3 \
  --out-dir ./output/variants \
  "Draw a clean futuristic AI wallpaper"
```

Batch generate from JSONL:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex_image.py" generate-batch \
  --input ./prompts.jsonl \
  --out-dir ./output/batch
```

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
└── skills/
    └── codex-image/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── assets/
        ├── references/
        └── scripts/
```

## Skill docs

- Main skill entry: [`skills/codex-image/SKILL.md`](./skills/codex-image/SKILL.md)
- CLI reference: [`skills/codex-image/references/cli.md`](./skills/codex-image/references/cli.md)
- Route parameter reference: [`skills/codex-image/references/image-api.md`](./skills/codex-image/references/image-api.md)
- Prompt guidance: [`skills/codex-image/references/prompting.md`](./skills/codex-image/references/prompting.md)
- Sample prompts: [`skills/codex-image/references/sample-prompts.md`](./skills/codex-image/references/sample-prompts.md)
- Runtime/auth notes: [`skills/codex-image/references/codex-network.md`](./skills/codex-image/references/codex-network.md)
