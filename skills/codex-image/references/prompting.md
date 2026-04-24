# Prompting best practices

These prompting principles are shared across the generate and edit flows in this skill.

This file is about prompt structure and iteration. API controls such as `quality`, `background`, `output_format`, `output_compression`, `mask`, and `input_fidelity` are execution settings, not prompt content.

## Structure

- Use a consistent order: scene/backdrop -> subject -> key details -> constraints -> output intent.
- For complex requests, use short labeled lines instead of one long paragraph.
- Include intended use when it affects polish or composition, such as wallpaper, poster, hero image, sticker, infographic, or UI mockup.

## Specificity policy

- If the user prompt is already detailed, normalize it into a cleaner spec.
- If the prompt is generic, add only the detail that materially improves the result.
- Treat the examples in `sample-prompts.md` as complete recipes, not the default amount of augmentation to add every time.

## Allowed augmentation

- composition and framing cues
- intended-use or polish-level hints
- practical layout guidance
- reasonable scene concreteness that supports the stated request

Do not add:

- extra characters, props, or objects not implied by the request
- brand palettes, slogans, or story beats not implied by the request
- arbitrary left/right placement without surrounding layout context

## Constraints and invariants

- State what must not change.
- For edits, say `change only X; keep Y unchanged`.
- Repeat invariants on every iteration to reduce drift.

## Text in images

- Put literal text in quotes and require verbatim rendering when text matters.
- Specify typography and placement when needed.
- For image-only requests, explicitly say `no text`.

## Direct-size guidance

- Prefer direct final sizes whenever the user provides an exact delivery size.
- When the user provides only a ratio like `16:9`, `9:16`, or `6:16`, let the skill convert it to the largest valid direct-request size.
- When the user provides both a ratio and a tier such as `9:16 1k`, `16:9 2k`, or `4k 9:16`, use the CLI ratio-tier syntax such as `--size '9:16@1k'` rather than passing the plain ratio.
- Keep the prompt explicit about the final canvas dimensions. The CLI adds this automatically for resolved direct sizes; do not contradict it with text such as "4K" when requesting `1k`.
- For explicit non-standard sizes, pass the user-requested `WIDTHxHEIGHT` to the API and describe that same final size in the prompt.
- If the generated result comes back with a materially different aspect ratio, do not silently distort it. Ask whether to retry through the model with stricter canvas wording or apply a chosen post-processing strategy.
- Do not plan on cropping, padding, or local upscaling after generation.

## Input images

- If actual image files are provided for the model to see, use `edit`, not `generate`, even when creating a new poster or mockup.
- Do not assume every provided image is a base image to modify; some inputs may be role references, product references, style references, or masks.
- For multi-image edits, label each input role clearly, for example `Input image 1 role: person reference` and `Input image 2 role: product reference`.
- Restate what must stay fixed from each input image.

## Iteration

- Start with a clean base prompt.
- Change one thing at a time on follow-up iterations.
- Re-state the must-keep constraints every time.

## Suggested shared schema

```text
Use case: <taxonomy slug>
Asset type: <where the image will be used>
Primary request: <main request>
Input images: <Image 1: role> (optional)
Scene/backdrop: <setting>
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
