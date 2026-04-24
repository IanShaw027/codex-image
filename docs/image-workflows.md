# Image Workflows: built-in `imagegen` vs `codex-image`

This document explains how Codex's built-in image workflow differs from the
local `codex-image` skill, what standard upstream interfaces are involved, and
which path fits which job.

It is intentionally implementation-aware. The goal is not just "how to call the
skill", but "why these two paths behave differently".

## Executive summary

- built-in `imagegen` is the native runtime image path
- `codex-image` is a local saved-file workflow built around an installed skill,
  shell launchers, and explicit upstream HTTP calls
- built-in `imagegen` is better for native current-turn image context and the
  fastest normal multi-turn image conversation
- `codex-image` is better for exact output paths, exact delivery sizes, local
  files, batch jobs, API-key mode, custom `OPENAI_BASE_URL`, and explicit image
  references such as `[Last Output]`

The two paths overlap, but they are not the same abstraction level.

## The two architectures

### 1. Built-in `imagegen`

This is the native runtime path.

High-level flow:

1. The current turn is assembled inside Codex runtime.
2. User images are converted into structured model input items.
3. The runtime calls the upstream Responses API image-generation tool.
4. The upstream service returns an `image_generation_call`.
5. Codex saves the resulting image artifact locally.

Important consequences:

- current-turn images are available as part of the runtime request itself
- continuation can use `previous_response_id`
- the path is short, so the user experience is usually faster
- this is the closest thing to "native session image context"

### 2. `codex-image`

This is a local skill workflow.

High-level flow:

1. The model decides to route into the installed skill.
2. Codex runs the launcher:
   - POSIX: `bash "${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image"`
   - Windows: `%CODEX_HOME%\skills\codex-image\scripts\codex-image.cmd`
3. The launcher starts `codex_image.py`.
4. The script resolves local files, output paths, prompt shape, and thread image
   references.
5. The script calls an upstream HTTP endpoint directly.
6. The script writes the final artifact to disk and updates local thread state.

Important consequences:

- the script does not receive native runtime image handles
- it must reconstruct image inputs from:
  - explicit file paths
  - placeholder references
  - thread rollout state
  - saved output state
- it can preserve local workflow guarantees that built-in `imagegen` does not
  try to provide

## The standard upstream interfaces

`codex-image` currently uses two upstream interface families.

### Images API

Default transport for normal `generate` and `edit`.

Endpoints:

- `POST /v1/images/generations`
- `POST /v1/images/edits`

Use this when:

- the task is a one-shot generation
- the task is a one-shot edit with explicit image inputs
- you need mask or `input_fidelity`
- you want the shortest direct HTTP path from the local skill

Supported output controls in this workflow include:

- `model`
- `size`
- `quality`
- `background`
- `moderation`
- `n`
- `output_format`
- `output_compression`
- `mask`
- `input_fidelity`

### Responses API + `image_generation`

Explicit transport, not the default path.

Endpoint:

- `POST /v1/responses`

Use this when:

- you explicitly need prior response state
- you have a `previous_response_id`
- you want to continue from a specific `image_generation_call` id

Current `codex-image` support is intentionally narrow:

- enabled only with `--transport responses`
- currently png-only
- no mask uploads
- no `input_fidelity`
- no output compression
- mainly for explicit multi-turn continuation state

## Concrete request shapes and application scenarios

The easiest way to choose correctly is to map the user request to a concrete
HTTP shape.

### A. One-shot text-to-image

Use:

- `POST /v1/images/generations`

Best for:

- "给我出一张海报"
- "做一个 16:9 UI 风格稿"
- "快速生成一张图看看"

Why:

- shortest direct request
- no prior image state required
- best default path for simple one-shot generation in `codex-image`

### B. One-shot text-to-image with output controls

Use:

- `POST /v1/images/generations`

Typical controls:

- `size`
- `quality`
- `output_format`
- `output_compression`
- `background`

Best for:

- exact delivery size work
- "保存成 jpeg/webp"
- "同一 prompt，但要求更快/更轻"

Why:

- this is where `codex-image` is often stronger than built-in `imagegen`
- local saved-file control is first-class here

### C. One-shot image edit

Use:

- `POST /v1/images/edits`

Best for:

- "基于这张图改一下"
- "只换背景，不动主体"
- "把图 1 和图 2 合成一张"

Why:

- explicit image inputs
- explicit local files
- no need to pretend this is a conversation-native continuation

### D. Multi-reference edit / synthesis

Use:

- `POST /v1/images/edits`

Typical shape:

- repeated `image` fields
- one prompt describing the roles of the inputs

Best for:

- person + product
- character + scene
- face/reference + base composition
- "图 1 的人放到图 2 的场景里"

Why:

- this is one of `codex-image`'s most useful explicit-control scenarios
- local file paths and saved outputs matter more than native session feel

### E. Masked local edit

Use:

- `POST /v1/images/edits`

Best for:

- "只改这一块"
- inpainting
- area-specific replacement

Why:

- current `codex-image` default Images API path supports mask and
  `input_fidelity`
- the explicit Responses transport currently does not

### F. Explicit multi-turn continuation with prior response state

Use:

- `POST /v1/responses`
- `previous_response_id`
- optionally `image_generation_call.id`

Best for:

- "继续上一张，改得更真实一点"
- "沿用刚才那张结果，再做一版"
- explicit response-chain continuity

Why:

- this is the closest `codex-image` gets to upstream multi-turn image state
- but it is explicit and narrower than built-in `imagegen`

### G. Native current-turn image-context conversation

Prefer:

- built-in `imagegen`

Best for:

- "我刚贴了张图，直接改"
- "继续上一轮那张，别问我路径"
- fastest casual follow-up editing

Why:

- runtime-native current-turn image context
- shorter path
- usually better user experience for ordinary conversation-style editing

### H. Batch generation

Use:

- local `generate-batch`
- internally still built around generation-style HTTP requests

Best for:

- theme boards
- campaign variants
- JSONL prompt sets
- exact output directory fan-out

Why:

- built-in `imagegen` does not provide this local batch-file workflow
- this is a clear `codex-image` advantage

## How built-in `imagegen` actually keeps session context

The important point is that built-in `imagegen` is not "using thread id magic"
by itself.

It effectively combines two mechanisms:

1. Current-turn image input is sent explicitly in the request.
   - local images become `input_image`
   - local files are turned into `data:image/...;base64,...`
2. Later turns can continue by using `previous_response_id`.

So the native experience comes from:

- runtime-owned current-turn inputs
- upstream response-chain continuity

This is why built-in `imagegen` feels more naturally conversation-bound than a
local skill.

## How `codex-image` handles image inputs

`codex-image` supports more explicit local workflow shapes than built-in
`imagegen`, but it gets them in a different way.

### Direct local files

The simplest case:

- `--image ./input.png`
- `--image /absolute/path/image.png`

### Thread placeholders

In a Codex thread, the skill can resolve:

- `[Image #N]`
- `[Turn -K Image #N]`
- `[Thread Image #N]`
- `[Last Output]`
- `--image-set active`
- `--image-set last-output`
- `--image-set latest-turn`
- `--image-set turn:-K`
- `--image-set thread:1,2,5`

### What the placeholders really mean

These are explicit local thread references, not native runtime context.

- `[Image #N]`
  means the most recent attachment-bearing user turn
- `[Turn -K Image #N]`
  means a prior attachment-bearing turn
- `[Thread Image #N]`
  means stable thread-wide attachment order
- `[Last Output]`
  means the previous saved result image for this thread

That is useful, but it is not the same thing as built-in `imagegen`'s
"whatever the current turn is holding right now" semantics.

### Inline pasted images

The skill now handles rollout-stored inline images such as:

- `data:image/png;base64,...`

These are cached into the thread output directory and then reused through the
same placeholder system.

### Remote image URLs

The skill also supports rollout-stored remote image URLs such as:

- `https://example.com/reference.png`

Those URLs are fetched and cached into the thread output directory before they
enter the placeholder resolution flow.

## Why the skill cannot fully behave like built-in `imagegen`

This is the main boundary to understand.

The built-in path is a runtime tool. `codex-image` is an external skill + local
CLI.

That means:

- built-in `imagegen` receives current-turn image context directly from runtime
- `codex-image` receives strings and files, not runtime-owned image handles

So even after heavy improvement, `codex-image` is still a reconstruction-based
workflow:

- local file path
- rollout replay
- thread state
- saved output state

It can get close to the user experience, but it cannot become identical without
the runtime explicitly exposing current-turn image handles to the skill.

## Scenario matrix

### Use built-in `imagegen`

Prefer built-in `imagegen` when the user wants:

- native current-turn image context
- the fastest simple image generation
- the fastest normal image follow-up conversation
- natural multi-turn editing without explicit local file control
- standard inline image generation/editing behavior

Typical examples:

- "根据我刚上传的图改一下"
- "继续上一张，肤色自然一点"
- "给我快速出 1 张看看"
- "我刚上传了两张图，继续自然地往下改"

### Use `codex-image`

Prefer `codex-image` when the user wants:

- saved files on disk
- exact `--out`
- exact `--out-dir`
- exact delivery size
- API-key mode
- custom `OPENAI_BASE_URL`
- explicit multi-image references
- batch generation from JSONL
- explicit reuse like `[Last Output]`

Typical examples:

- "保存到这个路径"
- "用 API key 模式走自定义网关"
- "批量生成一组主题图"
- "上一张结果当 base，再加当前这张真人照当参考"
- "根据这组本地素材做多图合成并精确落盘"

## What built-in `imagegen` does better

- Native current-turn image context
- Shorter path, usually faster
- More natural conversation-style follow-up
- Less local orchestration overhead

## What `codex-image` does better

- Exact output file control
- Exact output directory control
- Repeatable local CLI workflow
- JSONL batch generation
- Explicit image reuse semantics
- Saved thread output state
- API-key mode and custom provider routing
- More auditable local file behavior

## Current `codex-image` strengths

Today this skill is especially strong at:

- one-shot local generation with exact paths
- one-shot local editing with multiple explicit inputs
- "use the last result again" flows via `[Last Output]`
- explicit thread-image carry-forward flows
- delivery-size-aware post-save resizing
- batch prompt execution

## Current `codex-image` limits

The skill still should not be sold as a full replacement for native built-in
`imagegen`.

Known structural limits:

- placeholder semantics are explicit local references, not native runtime
  current-turn handles
- current-turn continuity is approximated through thread state and rollout
  reconstruction
- `--transport responses` is intentionally narrower than the default Images API
  path
- built-in `imagegen` remains the better path for the normal native session
  image workflow

## Recommended decision rule

Use this rule in practice:

- If the user says "just continue this image conversation normally", prefer
  built-in `imagegen`.
- If the user says "save it here", "use this exact path", "run through my API
  key/base URL", "batch these jobs", or "use explicit thread image references",
  prefer `codex-image`.

## Practical routing cheat sheet

Use this compact rule in daily work:

- Native conversation image flow: built-in `imagegen`
- One-shot local generate: `codex-image generate`
- One-shot local edit or multi-image synth: `codex-image edit`
- Local mask/inpainting: `codex-image edit --mask ...`
- Explicit prior response continuation: `codex-image --transport responses`
- Batch prompt file: `codex-image generate-batch`

## Related repository files

- Main skill entry:
  [skills/codex-image/SKILL.md](../skills/codex-image/SKILL.md)
- CLI reference:
  [skills/codex-image/references/cli.md](../skills/codex-image/references/cli.md)
- Transport details:
  [skills/codex-image/references/image-api.md](../skills/codex-image/references/image-api.md)
- Root overview:
  [README.md](../README.md)
