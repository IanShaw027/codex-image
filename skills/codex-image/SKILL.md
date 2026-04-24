---
name: codex-image
description: Use when generating or editing raster images and the built-in image_gen tool is not exposed in the current Codex session, when Codex is running in API key mode, or when the user explicitly asks for codex-image, saved PNG/JPEG/WebP output, Images API, custom OPENAI_BASE_URL, exact output path, exact size, aspect ratio, or local image CLI workflow.
---

# Codex Image Skill

Generates or edits raster images through a local CLI against an OpenAI-compatible Images API endpoint.

## Top-level mode and rules

This skill has exactly one top-level mode:

- **Explicit local CLI mode:** `scripts/codex_image.py` and its wrappers.

Endpoints inside this mode:

- `POST /v1/images/generations`
- `POST /v1/images/edits`

Subcommands:

- `generate`
- `edit`
- `generate-batch`

Rules:

- Use the built-in/system `imagegen` skill first only when the current session actually exposes the built-in `image_gen` tool and the user did not ask for saved-file/API/CLI output.
- Use this skill as the default fallback for normal raster image generation or editing when the built-in `image_gen` tool is absent, hidden, unavailable, or fails before producing an image. Do not fall back to hand-drawn SVG, Pillow sketches, screenshots, or one-off scripts unless the user explicitly requests a code-native drawing.
- Use this skill when Codex is in API key mode, when the user explicitly asks for `codex-image`, or when the task depends on saved files, exact output paths, exact sizes, aspect ratios, PNG/JPEG/WebP output, custom `OPENAI_BASE_URL`, or an OpenAI-compatible Images API endpoint.
- Use the bundled `scripts/codex_image.py` workflow. Do not create one-off SDK runners.
- Do not describe this skill as built-in image support. It is a local saved-file workflow.
- This skill is Images API only. It does not implement `Responses + image_generation`.
- In API key mode, `OPENAI_BASE_URL` or an equivalent provider `base_url` must be configured.

Save-path policy:

- Default output base is `${CODEX_HOME:-~/.codex}/generated_images/`.
- Inside Codex, the final directory uses `CODEX_THREAD_ID` or `CODEX_SESSION_ID`.
- Outside Codex, the final directory is `${CODEX_HOME:-~/.codex}/generated_images/manual/`.
- Do not claim built-in-style `<session_id>/<call_id>` output for standalone script runs. Only the session-like directory is emulated.
- If the user names a destination, write there with `--out`.
- If the image is meant for a project, move or write the selected final image into the workspace before finishing.

Shared prompt guidance lives in:

- `references/prompting.md`
- `references/sample-prompts.md`

CLI/runtime docs:

- `references/cli.md`
- `references/image-api.md`
- `references/codex-network.md`

## When to use

- Generate a new raster image through a local script
- Edit one or more local image files through `/v1/images/edits`
- Generate many prompts from a JSONL batch file
- Use a custom `OPENAI_BASE_URL` or provider configured in Codex
- Request a direct final output size, including valid 4K sizes such as `3840x2160`
- Use aspect-ratio-only requests like `16:9`, `9:16`, or `6:16`

## When not to use

- The built-in/system `imagegen` tool path is available and the user wants the normal built-in experience
- The user wants vector, SVG, HTML/CSS, or other code-native graphics instead of a raster asset
- The task is extending an existing repo-native icon or illustration system
- The user needs built-in inline image rendering instead of saved files

## Decision tree

Think about two separate questions:

1. Is the task a new image or an edit?
2. Is the final output preview-only or project-bound?

Intent:

- If the user wants to modify an existing image while preserving parts of it, use `edit`.
- If the user provides any input images that the model must see, use `edit` with repeated `--image` arguments, even when the desired result is a new poster or product mockup rather than a localized edit.
- If the user only describes references in text and provides no image files, use `generate`.
- If no image is supplied, use `generate`.

Output choice:

- For preview-only work, leave the file under the default generated-images path unless the user asked for another destination.
- For project-bound work, save or move the selected final artifact into the workspace and report the exact path.

## Workflow

1. Decide intent: `generate`, `edit`, or `generate-batch`.
2. Collect prompt, constraints, exact text, and any input image path.
3. Normalize the size request:
   - keep valid direct sizes unchanged
   - convert ratio input like `16:9` to the largest valid direct size under OpenAI constraints only when no delivery tier is provided
   - convert ratio plus delivery tier inputs such as `9:16 1k`, `9:16@1k`, or `1k@9:16` into a direct API size before sending; never pass tier syntax to the Images API
   - pass explicit `WIDTHxHEIGHT` user sizes through unchanged, including non-standard sizes such as `1000x1800`
   - keep the prompt aligned with the intended final delivery size by stating the final canvas dimensions in the prompt
   - after saving, verify the returned pixel dimensions; if the size differs but the aspect ratio is close, resize locally to that requested size
   - if the returned aspect ratio differs materially from the requested aspect ratio, do not stretch automatically; ask the user whether to retry generation, crop to cover, pad to contain, or force stretch
4. Choose output path:
   - `--out` for an exact path
   - `--out-dir` for multi-image output or batch output
   - `--name` for a readable prefix with automatic random suffix
   - default generated-images directory otherwise
5. Run the bundled CLI or wrapper.
6. Inspect the result and validate subject, style, composition, text accuracy, and invariants.
7. Report the final saved path.

## Prompt augmentation

Reformat the user prompt into a structured, production-oriented spec. Make the request clearer without inventing unnecessary story details.

Specificity policy:

- If the user prompt is already detailed, normalize it.
- If the prompt is generic, add only the detail that materially improves the result.

Allowed augmentation:

- composition or framing cues
- polish-level hints
- intended-use hints
- practical layout guidance

Do not add:

- extra characters or objects not implied by the request
- brand elements or slogans not implied by the request
- arbitrary left/right placement without context

## Use-case taxonomy

Generate:

- `photorealistic-natural`
- `product-mockup`
- `ui-mockup`
- `infographic-diagram`
- `logo-brand`
- `illustration-story`
- `stylized-concept`
- `historical-scene`

Edit:

- `text-localization`
- `identity-preserve`
- `precise-object-edit`
- `lighting-weather`
- `background-extraction`
- `style-transfer`
- `compositing`
- `sketch-to-render`

## Shared prompt schema

```text
Use case: <taxonomy slug>
Asset type: <where the asset will be used>
Primary request: <user's main prompt>
Input images: <Image 1: role> (optional)
Scene/backdrop: <environment>
Subject: <main subject>
Style/medium: <photo/illustration/3D/etc>
Composition/framing: <wide/close/top-down; placement>
Lighting/mood: <lighting + mood>
Color palette: <palette notes>
Materials/textures: <surface details>
Text (verbatim): "<exact text>"
Constraints: <must keep/must avoid>
Avoid: <negative constraints>
```

Notes:

- `Asset type` and `Input images` are prompt scaffolding, not CLI flags.
- `Scene/backdrop` is visual guidance. It is not the same thing as the API `background` parameter.
- API controls such as `quality`, `background`, `output_format`, `output_compression`, `mask`, and `input_fidelity` are execution settings, not prompt lines.

## Prompting best practices

- Structure prompt as scene/backdrop -> subject -> details -> constraints.
- Quote exact text and require verbatim rendering when text matters.
- Repeat invariants for edits.
- Use direct final sizes when the user asks for an exact delivery size.
- When the user asks for `1k`, `2k`, or `4k` together with a ratio, pass a ratio-tier size expression to the CLI, for example `--size '9:16@1k'`, so the CLI resolves the API `size` and also adds the resolved canvas size to the prompt.
- When the user asks for an explicit non-standard size, send that exact `WIDTHxHEIGHT` value to the API and keep it as the final output target. If the returned image dimensions differ, verify and resize the saved file locally.
- If the returned image has a materially different aspect ratio from the requested final size, stop instead of distorting it. For creative image requests, prefer asking the user whether to let the model retry with stronger size wording or choose a post-processing strategy.
- Do not crop, pad, or upscale locally just to reach the requested final size.
- For more examples, use `references/prompting.md` and `references/sample-prompts.md`.

## Images API notes

- `generate` uses `/v1/images/generations`.
- `edit` uses `/v1/images/edits`.
- `generate-batch` also uses `/v1/images/generations`, one request per batch job.
- `--model` selects the Images API model.
- `--n` works for `generate` and `edit`.
- `--mask` and `--input-fidelity` are edit-only controls.

## Output and safety rules

- Keep edits non-destructive by default.
- Use a new output path unless the user explicitly asks to overwrite.
- Print and report the final saved path.
- This skill must not keep image bytes in a long-lived service process; the CLI writes the decoded image directly to disk and exits.
