# Images API quick reference

This file documents the parameter surface exposed by `scripts/codex_image.py`.

## Endpoints

### Generate

Endpoint:

- `POST /v1/images/generations`

Payload shape:

```json
{
  "model": "gpt-image-2",
  "prompt": "Generate an image of ...",
  "n": 2,
  "size": "3840x2160",
  "quality": "high",
  "background": "auto",
  "moderation": "auto",
  "response_format": "b64_json",
  "output_format": "png",
  "output_compression": 80
}
```

### Edit

Endpoint:

- `POST /v1/images/edits`

Payload shape:

- multipart `form-data`
- text fields such as `model`, `prompt`, `n`, `size`, `quality`, `background`, `moderation`, `output_format`, `output_compression`, `input_fidelity`
- one or more uploaded `image` parts
- optional uploaded `mask`

## Supported options in this skill

- `model`
- `prompt`
- `n`
- `size`
- `quality`
- `background`
- `moderation`
- `response_format` fixed to `b64_json`
- `output_format`
- `output_compression`
- `input_fidelity` for edits
- `mask` for edits

## Size constraints enforced by the skill

The Images API receives only direct `WIDTHxHEIGHT` sizes or `auto`. Ratio-tier strings such as `9:16@1k` are local CLI input only and must be normalized before the request is sent. Explicit user-provided `WIDTHxHEIGHT` values are sent unchanged; if the API returns a different pixel size with a close aspect ratio, the CLI resizes the saved file locally to the requested dimensions. Material aspect-ratio mismatches fail instead of being stretched automatically.

- maximum edge length: `3840`
- width and height must both be divisible by `16`
- total pixels: `655360` to `8294400`
- long edge to short edge ratio: at most `3:1`

## Format and compression

- `output_format`: `png`, `jpeg`, `webp`
- `output_compression`: `0-100`
- compression is meaningful for `jpeg` and `webp`

## Background

- `auto`
- `opaque`
- `transparent`

The API `background` parameter is an output transparency control. It is not the same thing as the visual scene backdrop described in the prompt.

## Model defaults in this skill

- Images API model default: `gpt-image-2`

## Output decoding

- reads `data[].b64_json`
- decodes base64 and writes the file directly to disk
- when `n > 1`, writes one file per returned item
