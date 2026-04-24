# CLI reference (`codex-image` launcher -> `codex_image.py`)

Use the installed launcher directly:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_IMAGE="$CODEX_HOME/skills/codex-image/scripts/codex-image"
```

On POSIX, invoke the installed launcher through `bash "$CODEX_IMAGE"` so ZIP-based installs do not depend on the executable bit.
On Windows, use `%CODEX_HOME%\skills\codex-image\scripts\codex-image.cmd` or `%USERPROFILE%\.codex\skills\codex-image\scripts\codex-image.cmd`.

## Commands

- `generate`: `POST /v1/images/generations`
- `edit`: `POST /v1/images/edits`
- `generate-batch`: many generation jobs from JSONL

## Common shapes

```bash
bash "$CODEX_IMAGE" generate --size 3840x2160 "Prompt"
bash "$CODEX_IMAGE" generate --size 3840x2160 --prompt "Prompt when shell quoting is awkward"
bash "$CODEX_IMAGE" edit --image ./input.png "Change only X; keep Y unchanged"
bash "$CODEX_IMAGE" edit --image ./input.png --prompt "Change only X; keep Y unchanged"
bash "$CODEX_IMAGE" edit --image '[Image #1]' "Use the most recent attachment-bearing turn in this Codex thread"
bash "$CODEX_IMAGE" edit --image '[Turn -1 Image #1]' --image '[Thread Image #3]' "Mix prior-turn and thread-wide references"
bash "$CODEX_IMAGE" edit --image-set active "In a Codex thread, explicitly reuse the previous edit input list"
bash "$CODEX_IMAGE" edit --image-set last-output "In a Codex thread, continue refining the previous saved result image"
bash "$CODEX_IMAGE" edit --image-set active --image-set latest-turn "In a Codex thread, explicitly merge the previous input list with the latest attachment-bearing turn"
bash "$CODEX_IMAGE" edit --image '[Turn -1 Image #1]' --image '[Turn -1 Image #2]' --image '[Image #1]' "After a follow-up with one new attachment, carry forward the prior two images plus the new one"
bash "$CODEX_IMAGE" edit --image '[Last Output]' --image '[Image #1]' "Refine the last result image and use the current upload as a new realism/style reference"
bash "$CODEX_IMAGE" generate-batch --input ./prompts.jsonl --out-dir ./output/batch
```

## Key rules

- If the model must see any real image input, use `edit`.
- After this skill is selected, usually invoke the installed launcher first and let it own runtime, auth, and attachment validation. Reach for config/auth or `--help` only when the launcher is missing or its failure still needs interpretation.
- `generate --image` emits a warning and is rerouted to `edit`.
- `--image '[Image #N]'` resolves against the most recent attachment-bearing user turn, not necessarily the current turn or the most recent text-only user message.
- `--image '[Turn -K Image #N]'` resolves against the `K`th previous attachment-bearing user turn.
- `--image '[Thread Image #N]'` resolves against stable thread-wide attachment order.
- `--image '[Last Output]'` or `--image '[Last Output #N]'` resolves against the previous saved output image list for the thread.
- After a follow-up that adds only one new attachment, `[Image #1]` refers to that new attachment only. Do not treat older images as `[Image #2]` or `[Image #3]`; switch to `[Turn -1 Image #N]`, `[Thread Image #N]`, or `--image-set`.
- Placeholder and selector resolution use the rollout-recorded cwd for each attachment-bearing turn; they do not fall back to the current shell cwd.
- `edit` does not implicitly inherit prior thread state. Reuse requires explicit `--image-set` selectors or explicit `--image`.
- `--image-set` accepts `active`, `last-output`, `latest-turn`, `turn:-K`, and `thread:1,2,5`, and is also Codex-thread-only.
- `active` means the previous `edit` call's resolved input image list for the thread, not prior generated outputs and not every attachment seen in the thread.
- `last-output` means the previous saved result image list for the thread, not the previous input list.
- `--reset-image-set` is a compatibility flag and no longer changes selector behavior.
- Minor placeholder variants such as `[Image#1]` and `[image # 1]` are normalized automatically.
- For multipart edits, repeat the `image` field; do not rename it to `images`.

## Important options

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
- `--name <readable-prefix>`
- `--prompt-file <path>`
- `--prompt <text>` for `generate` and `edit`
- `--dry-run`
- `--force`
- `--image <path>` repeated for `edit`
- `--image-set <selector>` repeated for `edit`
- `--reset-image-set` for `edit`
- `--mask <mask.png>` for `edit`
- `--input-fidelity <low|high>` for `edit`

## Size behavior

- Explicit `WIDTHxHEIGHT` is sent unchanged, including non-standard sizes such as `1000x1800`.
- Ratio forms such as `16:9`, `9:16`, and `9:16@1k` are resolved locally to direct API sizes.
- The CLI appends final-canvas wording to the prompt for direct-size delivery.
- If the API returns the same aspect ratio with different pixels, the saved file is resized locally to the requested final size.
- If the returned aspect ratio differs materially, the CLI fails instead of stretching automatically.

Common resolved sizes:

- `16:9` -> `3840x2160`
- `9:16` -> `2160x3840`
- `6:16` -> `1440x3840`
- `9:16@1k` -> `1008x1792`
- `9:16@2k` -> `2016x3584`
- `9:16@4k` -> `2160x3840`

## Output behavior

- Default output base: `${CODEX_HOME:-~/.codex}/generated_images/`
- Inside Codex: thread subdirectory from `CODEX_THREAD_ID` or `CODEX_SESSION_ID`
- Outside Codex: `manual/`
- `--out` writes an exact path.
- `--out-dir` is best for batch or multi-output work.
- `--name` keeps the default directory and adds an automatic random suffix.
- When `--n > 1`, numbered sibling files are created.

## Batch input

- One JSONL job per line.
- String line: `"Prompt"`
- Object line: `{"prompt":"Prompt","size":"16:9","n":2}`

Per-job overrides:

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

## Related docs

- `references/prompting.md`
- `references/sample-prompts.md`
- `references/image-api.md`
- `references/codex-network.md`
