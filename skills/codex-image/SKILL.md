---
name: codex-image
description: Use when generating or editing raster images and the built-in image_gen tool is not exposed in the current Codex session, when Codex is running in API key mode, or when the user explicitly asks for codex-image, saved PNG/JPEG/WebP output, Images API, custom OPENAI_BASE_URL, exact output path, exact size, aspect ratio, or local image CLI workflow.
---

# Codex Image Skill

Local saved-file raster image workflow backed by `scripts/codex_image.py`, shell launchers, and an OpenAI-compatible Images API.

## Core rules

- Use built-in/system `imagegen` first only when the current session actually exposes `image_gen`, the user did not ask for saved-file, API, or CLI behavior, and the built-in path has not already failed before producing an image.
- Use this skill as the fallback when built-in `image_gen` is absent, hidden, unavailable, already ruled out by the user, or failed before producing an image.
- This skill is CLI-only and Images-API-only. Do not describe it as built-in image support.
- Use the installed launcher path directly, not a repo-relative path: on POSIX `bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image"`; on Windows use `%CODEX_HOME%\skills\codex-image\scripts\codex-image.cmd` or `%USERPROFILE%\.codex\skills\codex-image\scripts\codex-image.cmd`.
- Once this skill is selected, usually run the installed launcher first. Preflight config, auth, or `--help` only when the launcher is missing or its failure still leaves a real decision to make.
- Do not fall back to SVG, Pillow sketches, screenshots, or one-off scripts unless the user explicitly wants code-native graphics.
- `OPENAI_BASE_URL` or provider `base_url` must exist in API-key mode.

## When to use

- Generate a new raster image and save it to disk
- Edit one or more real input images through `/v1/images/edits`
- Use exact output paths, exact sizes, aspect ratios, PNG/JPEG/WebP, or custom provider endpoints
- Use this path in API-key mode, with custom `OPENAI_BASE_URL`, or for direct Images API workflows even if built-in `image_gen` is exposed
- Batch-generate many prompts through `generate-batch`

## When not to use

- The built-in/system `imagegen` path is available and the user wants the normal built-in experience
- The task is better solved as SVG, HTML/CSS, canvas, or another code-native asset
- The task is extending an existing repo-native icon or illustration system

## Intent rules

- If the model must see any real image input, treat the task as `edit`.
- If the user only describes references in text and provides no image files, treat the task as `generate`.
- Prefer `--prompt` over a long trailing positional prompt when shell quoting would be awkward.
- Attachment placeholders and image-set selectors only work inside a Codex thread with `CODEX_THREAD_ID` or `CODEX_SESSION_ID`.
- In that Codex-thread mode, `[Image #N]` resolves against the most recent attachment-bearing user turn. It is the current turn only when the current turn actually carries attachments.
- Previous attachment-bearing turns can be referenced as `[Turn -K Image #N]`.
- Stable thread-wide attachment numbering can be referenced as `[Thread Image #N]`.
- The previous saved result for the thread can be referenced as `[Last Output]` or `[Last Output #N]`.
- After a follow-up that adds only one new attachment, that new file is `[Image #1]`. Older images do not remain addressable as `[Image #2]` or `[Image #3]`; switch to `[Turn -1 Image #N]`, `[Thread Image #N]`, or explicit `--image-set`.
- In that Codex-thread mode, the active image set is the previous `edit` call's resolved input image list for the thread, not prior generated outputs.
- Use `--image-set last-output` when the user wants to continue refining the previously generated result image itself.
- Attachment placeholders resolve only from rollout-recorded paths for that turn; they do not fall back to the current shell working directory.
- Use `--image-set` to select `active`, `last-output`, `latest-turn`, `turn:-K`, or `thread:1,2,5` explicitly.
- `edit` does not implicitly inherit prior thread state. Reuse requires explicit `--image-set active` or explicit image references.
- Harmless placeholder variants such as `[Image#1]` and `[image # 1]` are normalized automatically.
- If `generate` is called with `--image`, the CLI emits a warning and reroutes it to `edit`.

## Output rules

- Default output base is `${CODEX_HOME:-~/.codex}/generated_images/`.
- Inside Codex, the default subdirectory uses `CODEX_THREAD_ID` or `CODEX_SESSION_ID`.
- Outside Codex, the default subdirectory is `manual/`.
- Use `--out` for an exact final path.
- Use `--out-dir` for batch or multi-output jobs.
- Use `--name` for a readable prefix with an automatic random suffix.
- For project-bound assets, save or move the final image into the workspace before finishing.
- Keep edits non-destructive by default unless the user explicitly asked to overwrite.

## Workflow

1. Decide `generate`, `edit`, or `generate-batch`.
2. Collect prompt, exact text, constraints, output target, and any input images.
3. In a Codex thread with `CODEX_THREAD_ID` or `CODEX_SESSION_ID`, use `[Image #N]` for the most recent attachment-bearing turn, `[Turn -K Image #N]` for earlier attachment-bearing turns, `[Thread Image #N]` for stable thread-wide references, `[Last Output]` for the previous saved result image, or `--image-set active` / `--image-set last-output` / `--image-set latest-turn` for explicit reuse.
   A follow-up that adds one new image should usually look like `[Turn -1 Image #1]`, `[Turn -1 Image #2]`, and `[Image #1]` rather than `[Image #1]`, `[Image #2]`, `[Image #3]`.
   A follow-up that says "use the last result as the base and refine it" should usually include `[Last Output]` or `--image-set last-output`, then describe that image as the base result to refine in the prompt.
4. Normalize the size request:
   - keep explicit `WIDTHxHEIGHT` unchanged
   - convert ratio forms such as `16:9` or `9:16@1k` into direct API sizes
   - preserve the requested final delivery size as the post-save target
5. Run the bundled launcher.
6. Validate subject, composition, text, and invariants.
7. Report the final saved path.

## Size and post-processing policy

- Pass explicit non-standard sizes such as `1000x1800` to the API unchanged.
- If the returned image has the same aspect ratio but different pixels, resize locally to the requested final size.
- If the returned aspect ratio differs materially, stop instead of stretching automatically.

## Prompt guidance

- Structure prompts as backdrop -> subject -> details -> constraints.
- Quote exact text when text matters.
- Repeat invariants for edits.
- Add only useful detail; do not invent extra objects, brands, or layout constraints.

For prompt schema, taxonomy, examples, and CLI detail, use:

- `references/prompting.md`
- `references/sample-prompts.md`
- `references/cli.md`
- `references/image-api.md`
- `references/codex-network.md`
