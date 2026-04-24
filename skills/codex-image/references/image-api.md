# Transport quick reference

This file documents the upstream parameter surface exposed by `scripts/codex_image.py`.

## Endpoints

### Default generate transport

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

### Default edit transport

Endpoint:

- `POST /v1/images/edits`

Payload shape:

- multipart `form-data`
- text fields such as `model`, `prompt`, `n`, `size`, `quality`, `background`, `moderation`, `output_format`, `output_compression`, `input_fidelity`
- one or more uploaded `image` parts
- optional uploaded `mask`

### Explicit responses transport

Endpoint:

- `POST /v1/responses`

Payload shape used by this skill:

```json
{
  "model": "gpt-image-2",
  "previous_response_id": "resp_123",
  "input": [
    {
      "role": "user",
      "content": [
        { "type": "input_text", "text": "Make it more realistic" },
        { "type": "input_image", "image_url": "data:image/png;base64,..." }
      ]
    },
    { "type": "image_generation_call", "id": "ig_123" }
  ],
  "tools": [
    {
      "type": "image_generation",
      "action": "edit",
      "size": "1024x1024",
      "quality": "medium",
      "background": "auto",
      "moderation": "auto",
      "n": 1
    }
  ]
}
```

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
- `transport` for `generate` and `edit`
- `previous_response_id` for explicit Responses API follow-up state
- `response_image_id` for explicit Responses API image continuation state

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

For explicit Responses API mode:

- reads `output[].result` from `type == "image_generation_call"`
- decodes base64 and writes the file directly to disk
- records the top-level `response_id` plus `image_generation_call` ids for follow-up reuse
- current implementation keeps Responses support narrow on purpose and still defaults to the Images API
