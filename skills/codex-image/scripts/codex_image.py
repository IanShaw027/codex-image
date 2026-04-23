#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import re
import sys
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, NoReturn
from urllib import error, request

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("python 3.11+ is required") from exc


DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_FORMAT = "png"
DEFAULT_TIMEOUT = 600
DEFAULT_BACKGROUND = "auto"
DEFAULT_MODERATION = "auto"
DEFAULT_BATCH_CONCURRENCY = 4
DEFAULT_BATCH_MAX_JOBS = 500
IMAGE_SIZE_STEP = 16
IMAGE_MAX_EDGE = 3840
IMAGE_MIN_PIXELS = 655_360
IMAGE_MAX_PIXELS = 8_294_400
IMAGE_MAX_RATIO = 3.0
IMAGE_MAX_N = 10
IMAGE_MAX_EDIT_IMAGES = 16
SIZE_DIMENSION_PATTERN = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")
SIZE_RATIO_PATTERN = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


def log(message: str) -> None:
    print(f"[codex-image] {message}", file=sys.stderr)


def fail(message: str, *, status: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(status)


def sanitize_path_segment(value: str) -> str:
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "_"
        for ch in value
    )
    return sanitized or "generated_image"


def slugify(value: str) -> str:
    return sanitize_path_segment(value.strip().lower())[:80]


def default_output_dir() -> str:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    thread_id = (
        os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CODEX_SESSION_ID")
        or "manual"
    )
    return str(codex_home / "generated_images" / sanitize_path_segment(thread_id))


def validate_image_size(width: int, height: int) -> str | None:
    if width <= 0 or height <= 0:
        return "width and height must be positive"
    if width % IMAGE_SIZE_STEP != 0 or height % IMAGE_SIZE_STEP != 0:
        return f"width and height must both be divisible by {IMAGE_SIZE_STEP}"
    if width > IMAGE_MAX_EDGE or height > IMAGE_MAX_EDGE:
        return f"maximum edge length is {IMAGE_MAX_EDGE}px"

    pixels = width * height
    if pixels < IMAGE_MIN_PIXELS:
        return f"total pixels must be at least {IMAGE_MIN_PIXELS}"
    if pixels > IMAGE_MAX_PIXELS:
        return f"total pixels must be at most {IMAGE_MAX_PIXELS}"

    long_edge = max(width, height)
    short_edge = min(width, height)
    if long_edge / short_edge > IMAGE_MAX_RATIO:
        return f"long edge to short edge ratio must not exceed {IMAGE_MAX_RATIO}:1"
    return None


def iter_ratio_candidates(width_ratio: int, height_ratio: int) -> list[tuple[int, int]]:
    ratio = Fraction(width_ratio, height_ratio).limit_denominator(256)
    numerator = ratio.numerator
    denominator = ratio.denominator

    if max(numerator, denominator) / min(numerator, denominator) > IMAGE_MAX_RATIO:
        return []

    step_multiplier = math.lcm(
        IMAGE_SIZE_STEP // math.gcd(numerator, IMAGE_SIZE_STEP),
        IMAGE_SIZE_STEP // math.gcd(denominator, IMAGE_SIZE_STEP),
    )
    base_width = numerator * step_multiplier
    base_height = denominator * step_multiplier

    max_scale = min(IMAGE_MAX_EDGE // base_width, IMAGE_MAX_EDGE // base_height)
    candidates: list[tuple[int, int]] = []
    for scale in range(1, max_scale + 1):
        width = base_width * scale
        height = base_height * scale
        if validate_image_size(width, height) is None:
            candidates.append((width, height))
    return candidates


def choose_candidate(
    candidates: list[tuple[int, int]],
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> tuple[int, int]:
    if not candidates:
        fail(
            "no valid image size candidate found under OpenAI constraints "
            f"(edge <= {IMAGE_MAX_EDGE}, divisible by {IMAGE_SIZE_STEP}, "
            f"pixels {IMAGE_MIN_PIXELS}-{IMAGE_MAX_PIXELS}, ratio <= {IMAGE_MAX_RATIO}:1)"
        )

    if target_width is None or target_height is None:
        return max(candidates, key=lambda item: (item[0] * item[1], max(item), min(item)))

    target_pixels = target_width * target_height
    return min(
        candidates,
        key=lambda item: (
            (item[0] - target_width) ** 2 + (item[1] - target_height) ** 2,
            item[0] > target_width or item[1] > target_height or item[0] * item[1] > target_pixels,
            abs(item[0] * item[1] - target_pixels),
            item[0] * item[1],
        ),
    )


def normalize_image_size(spec: str) -> tuple[str, str | None]:
    raw_spec = spec.strip()
    if raw_spec.lower() == "auto":
        return "auto", None

    dim_match = SIZE_DIMENSION_PATTERN.match(raw_spec)
    if dim_match:
        width = int(dim_match.group(1))
        height = int(dim_match.group(2))
        if validate_image_size(width, height) is None:
            return f"{width}x{height}", None

        ratio = Fraction(width, height).limit_denominator(256)
        candidates = iter_ratio_candidates(ratio.numerator, ratio.denominator)
        normalized_width, normalized_height = choose_candidate(
            candidates,
            target_width=width,
            target_height=height,
        )
        normalized = f"{normalized_width}x{normalized_height}"
        return normalized, f"normalized image size {raw_spec} -> {normalized}"

    ratio_match = SIZE_RATIO_PATTERN.match(raw_spec)
    if ratio_match:
        width_ratio = int(ratio_match.group(1))
        height_ratio = int(ratio_match.group(2))
        if width_ratio <= 0 or height_ratio <= 0:
            fail(f"invalid image ratio: {raw_spec}")

        normalized_width, normalized_height = choose_candidate(
            iter_ratio_candidates(width_ratio, height_ratio)
        )
        normalized = f"{normalized_width}x{normalized_height}"
        return normalized, f"normalized image size {raw_spec} -> {normalized}"

    fail(
        "invalid image size. Use auto, WIDTHxHEIGHT, or WIDTH:HEIGHT "
        "(examples: 3840x2160, 1792x1024, 9:16)"
    )


def validate_background(background: str) -> None:
    if background not in {"auto", "opaque", "transparent"}:
        fail("background must be one of auto, opaque, or transparent")


def validate_quality(quality: str) -> None:
    if quality not in {"low", "medium", "high", "auto"}:
        fail("quality must be one of low, medium, high, or auto")


def validate_format(fmt: str) -> str:
    normalized = fmt.lower()
    if normalized == "jpg":
        normalized = "jpeg"
    if normalized not in {"png", "jpeg", "webp"}:
        fail("format must be one of png, jpeg, webp")
    return normalized


def validate_compression(value: int | None) -> None:
    if value is None:
        return
    if value < 0 or value > 100:
        fail("compression must be between 0 and 100")


def validate_input_fidelity(value: str | None) -> None:
    if value is None:
        return
    if value not in {"low", "high"}:
        fail("input-fidelity must be one of low or high")


def validate_moderation(value: str | None) -> None:
    if value is None:
        return
    if value not in {"auto", "low"}:
        fail("moderation must be one of auto or low")


def validate_transparency(background: str, fmt: str) -> None:
    if background == "transparent" and fmt not in {"png", "webp"}:
        fail("transparent background requires png or webp output")


def validate_n(value: int) -> None:
    if value < 1 or value > IMAGE_MAX_N:
        fail(f"n must be between 1 and {IMAGE_MAX_N}")


def validate_batch_concurrency(value: int) -> None:
    if value < 1 or value > 25:
        fail("batch concurrency must be between 1 and 25")


def load_codex_config() -> tuple[dict[str, Any], Path]:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    config_path = Path(os.environ.get("CODEX_CONFIG", codex_home / "config.toml")).expanduser()
    if not config_path.exists():
        return {}, config_path
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8")), config_path
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"failed to read Codex config {config_path}: {exc}")


def load_codex_auth_api_key() -> str | None:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    auth_path = Path(os.environ.get("CODEX_AUTH_FILE", codex_home / "auth.json")).expanduser()
    if not auth_path.exists():
        return None
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"failed to read Codex auth file {auth_path}: {exc}")

    api_key = payload.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None


def resolve_provider(config: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    provider_id = os.environ.get("CODEX_IMAGE_MODEL_PROVIDER")
    if not provider_id:
        provider_id = config.get("model_provider")
    if not provider_id:
        return None, {}

    providers = config.get("model_providers", {})
    provider = providers.get(provider_id)
    if isinstance(provider, dict):
        return str(provider_id), provider

    lowered = str(provider_id).lower()
    for key, value in providers.items():
        if str(key).lower() == lowered and isinstance(value, dict):
            return str(key), value
    return str(provider_id), {}


def resolve_default_model(config: dict[str, Any]) -> str:
    env_model = os.environ.get("CODEX_IMAGE_MODEL")
    if env_model:
        return env_model
    config_model = config.get("model")
    if isinstance(config_model, str) and config_model.strip().startswith("gpt-image-"):
        return config_model.strip()
    return DEFAULT_MODEL


def ensure_base_url(base_url: str | None, *, config_path: Path, provider_id: str | None) -> str:
    if isinstance(base_url, str) and base_url.strip():
        return base_url.rstrip("/")

    provider_note = f" for provider {provider_id}" if provider_id else ""
    fail(
        "OPENAI_BASE_URL is required in API key mode. "
        f"Set OPENAI_BASE_URL or configure a provider base_url{provider_note} in {config_path}."
    )


def resolve_runtime() -> dict[str, Any]:
    config, config_path = load_codex_config()
    provider_id, provider = resolve_provider(config)

    provider_env_key = provider.get("env_key") if isinstance(provider.get("env_key"), str) else None

    api_key = (
        (os.environ.get(provider_env_key) if provider_env_key else None)
        or os.environ.get("OPENAI_API_KEY")
        or load_codex_auth_api_key()
    )

    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or (provider.get("base_url") if isinstance(provider.get("base_url"), str) else None)
    )

    if not base_url and provider_id and provider_id.lower() == "openai":
        candidate = config.get("openai_base_url")
        if isinstance(candidate, str) and candidate.strip():
            base_url = candidate

    output_dir = os.environ.get("CODEX_IMAGE_OUTPUT_DIR")
    if not output_dir:
        output_dir = default_output_dir()

    return {
        "api_key": api_key,
        "base_url": ensure_base_url(base_url, config_path=config_path, provider_id=provider_id),
        "model": resolve_default_model(config),
        "size": os.environ.get("CODEX_IMAGE_SIZE", DEFAULT_SIZE),
        "quality": os.environ.get("CODEX_IMAGE_QUALITY", DEFAULT_QUALITY),
        "format": validate_format(os.environ.get("CODEX_IMAGE_FORMAT", DEFAULT_FORMAT)),
        "compression": os.environ.get("CODEX_IMAGE_COMPRESSION"),
        "background": os.environ.get("CODEX_IMAGE_BACKGROUND", DEFAULT_BACKGROUND),
        "moderation": os.environ.get("CODEX_IMAGE_MODERATION", DEFAULT_MODERATION),
        "timeout": int(os.environ.get("CODEX_IMAGE_TIMEOUT", str(DEFAULT_TIMEOUT))),
        "output_dir": output_dir,
        "config_path": str(config_path),
        "provider_id": provider_id,
        "provider_env_key": provider_env_key,
    }


def read_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt and prompt_file:
        fail("use either prompt or --prompt-file, not both")
    if prompt_file:
        path = Path(prompt_file).expanduser()
        if not path.is_file():
            fail(f"prompt file not found: {path}")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            fail(f"prompt file is empty: {path}")
        return value
    if prompt is None:
        fail("prompt is required")
    value = prompt.strip()
    if not value:
        fail("prompt is required")
    return value


def random_suffix(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_output_paths(
    *,
    out_path: str | None,
    out_dir: str | None,
    name_spec: str,
    fmt: str,
    output_dir: str,
    count: int,
) -> list[Path]:
    validate_n(count)
    ext = f".{fmt}"

    if out_dir:
        base_dir = Path(out_dir).expanduser()
        base_dir.mkdir(parents=True, exist_ok=True)
        group = f"{sanitize_path_segment(name_spec)}-{random_suffix()}"
        if count == 1:
            return [base_dir / f"{group}{ext}"]
        return [base_dir / f"{group}-{idx}{ext}" for idx in range(1, count + 1)]

    if out_path:
        path = Path(out_path).expanduser()
        if path.suffix == "":
            path = path.with_suffix(ext)
        if count == 1:
            return [ensure_parent(path)]
        return [
            ensure_parent(path.with_name(f"{path.stem}-{idx}{path.suffix}"))
            for idx in range(1, count + 1)
        ]

    base_dir = Path(output_dir).expanduser()
    base_dir.mkdir(parents=True, exist_ok=True)
    group = f"{sanitize_path_segment(name_spec)}-{random_suffix()}"
    if count == 1:
        return [base_dir / f"{group}{ext}"]
    return [base_dir / f"{group}-{idx}{ext}" for idx in range(1, count + 1)]


def decode_and_save_many(images_b64: list[str], out_paths: list[Path], *, force: bool) -> list[Path]:
    if not images_b64:
        fail("image generation result missing in images payload")
    if len(images_b64) < len(out_paths):
        fail(
            f"image generation result count {len(images_b64)} does not match expected outputs {len(out_paths)}"
        )
    written: list[Path] = []
    for idx, out_path in enumerate(out_paths):
        out_path = ensure_parent(out_path)
        if out_path.exists() and not force:
            fail(f"output already exists: {out_path} (use --force to overwrite)")
        out_path.write_bytes(base64.b64decode(images_b64[idx]))
        written.append(out_path)
    return written


def build_api_url(base_url: str, endpoint: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}{endpoint}"
    return f"{normalized}/v1{endpoint}"


def build_headers(api_key: str, content_type: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type,
        "Accept": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }


def post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    log(f"POST {url}")
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers=build_headers(api_key, "application/json"),
        method="POST",
    )
    return execute_request(req, timeout)


def encode_multipart(
    fields: dict[str, Any],
    files: list[tuple[str, Path]],
) -> tuple[bytes, str]:
    boundary = f"----codex-image-{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in fields.items():
        if value is None:
            continue
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, path in files:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


def post_multipart(
    url: str,
    api_key: str,
    fields: dict[str, Any],
    files: list[tuple[str, Path]],
    timeout: int,
) -> dict[str, Any]:
    log(f"POST {url}")
    body, boundary = encode_multipart(fields, files)
    req = request.Request(
        url,
        data=body,
        headers=build_headers(api_key, f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    return execute_request(req, timeout)


def execute_request(req: request.Request, timeout: int) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            log(f"response status={resp.status} bytes={len(raw)}")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                preview = text[:1000]
                fail(f"request failed: expected JSON response from {req.full_url}\n{preview}")
    except error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        request_id = exc.headers.get("x-request-id")
        rid = f", request_id={request_id}" if request_id else ""
        fail(f"request failed: status={exc.code}{rid}\n{body_text}")
    except error.URLError as exc:
        fail(f"request failed: {exc}")


def extract_images_from_images_payload(data: dict[str, Any]) -> list[str]:
    items = data.get("data") or []
    if not items:
        fail(
            "image generation result missing in images payload:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )
    results: list[str] = []
    for item in items:
        for key in ("b64_json", "result"):
            value = item.get(key)
            if value:
                results.append(str(value))
                break
    if not results:
        fail(
            "image generation result missing in images payload:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )
    return results


def effective_model(args_model: str | None, runtime: dict[str, Any]) -> str:
    return args_model or runtime["model"]


def common_runtime_values(
    args: argparse.Namespace,
    runtime: dict[str, Any],
) -> tuple[str, str, str, int | None, str, str, str | None]:
    size, size_note = normalize_image_size(args.size or runtime["size"])
    quality = args.quality or runtime["quality"]
    fmt = validate_format(args.format or runtime["format"])
    compression_raw = args.compression if args.compression is not None else runtime["compression"]
    compression = int(compression_raw) if compression_raw is not None else None
    background = args.background or runtime["background"]
    moderation = args.moderation or runtime["moderation"]
    validate_quality(quality)
    validate_background(background)
    validate_moderation(moderation)
    validate_compression(compression)
    validate_transparency(background, fmt)
    return size, quality, fmt, compression, background, moderation, size_note


def ensure_api_key(runtime: dict[str, Any]) -> str:
    api_key = runtime["api_key"]
    if api_key:
        return str(api_key)
    env_hint = runtime["provider_env_key"] or "OPENAI_API_KEY"
    fail(
        "API key is required. Set OPENAI_API_KEY"
        f" (or provider env key {env_hint})"
    )


def maybe_print_preview(preview: dict[str, Any], *, dry_run: bool) -> bool:
    if not dry_run:
        return False
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    return True


def resolve_edit_inputs(args: argparse.Namespace) -> tuple[list[Path], str]:
    raw_values: list[str] = []
    positional = list(getattr(args, "positional", []) or [])

    if getattr(args, "image", None):
        raw_values.extend(args.image)
        if len(positional) > 1:
            fail("when --image is used, provide prompt as one trailing argument or use --prompt-file")
        prompt_arg = positional[0] if positional else None
    else:
        if not positional:
            fail("at least one input image is required")
        if len(positional) > 2:
            fail("edit expects INPUT_IMAGE PROMPT when --image is not used")
        raw_values.append(positional[0])
        prompt_arg = positional[1] if len(positional) == 2 else None

    if not raw_values:
        fail("at least one input image is required")

    paths: list[Path] = []
    for raw in raw_values:
        path = Path(raw).expanduser()
        if not path.is_file():
            fail(f"input image not found: {path}")
        paths.append(path)
    if len(paths) > IMAGE_MAX_EDIT_IMAGES:
        fail(f"at most {IMAGE_MAX_EDIT_IMAGES} input images are supported for edit")
    return paths, read_prompt(prompt_arg, args.prompt_file)


def normalize_job(job: Any, idx: int) -> dict[str, Any]:
    if isinstance(job, str):
        prompt = job.strip()
        if not prompt:
            fail(f"empty prompt in batch job {idx}")
        return {"prompt": prompt}
    if isinstance(job, dict):
        prompt = str(job.get("prompt", "")).strip()
        if not prompt:
            fail(f"missing prompt in batch job {idx}")
        return dict(job)
    fail(f"invalid batch job {idx}: expected string or object")


def read_jobs_jsonl(path: str) -> list[dict[str, Any]]:
    input_path = Path(path).expanduser()
    if not input_path.is_file():
        fail(f"batch input not found: {input_path}")

    jobs: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item: Any
            if line.startswith("{"):
                item = json.loads(line)
            else:
                item = line
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON in batch job line {line_no}: {exc}")
        jobs.append(normalize_job(item, line_no))

    if not jobs:
        fail("no batch jobs found")
    if len(jobs) > DEFAULT_BATCH_MAX_JOBS:
        fail(f"too many batch jobs: {len(jobs)} (max {DEFAULT_BATCH_MAX_JOBS})")
    return jobs


def preview_output_strings(paths: Iterable[Path]) -> list[str]:
    return [str(path) for path in paths]


def build_generate_payload(
    *,
    model: str,
    prompt: str,
    n: int,
    size: str,
    quality: str,
    background: str,
    moderation: str,
    fmt: str,
    compression: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "quality": quality,
        "response_format": "b64_json",
        "background": background,
        "moderation": moderation,
    }
    if fmt != "png":
        payload["output_format"] = fmt
    if compression is not None:
        payload["output_compression"] = compression
    return payload


def cmd_generate(args: argparse.Namespace) -> int:
    runtime = resolve_runtime()
    api_key = ensure_api_key(runtime)
    prompt = read_prompt(args.prompt, args.prompt_file)
    model = effective_model(args.model, runtime)
    size, quality, fmt, compression, background, moderation, size_note = common_runtime_values(args, runtime)
    n = args.n
    validate_n(n)

    stamp = args.name or "generated"
    out_paths = resolve_output_paths(
        out_path=args.out,
        out_dir=args.out_dir,
        name_spec=stamp,
        fmt=fmt,
        output_dir=runtime["output_dir"],
        count=n,
    )

    log(
        "generate start "
        f"base_url={runtime['base_url']} model={model} "
        f"size={size} quality={quality} format={fmt} background={background} "
        f"moderation={moderation} n={n} outputs={len(out_paths)}"
    )
    if size_note:
        log(size_note)

    payload = build_generate_payload(
        model=model,
        prompt=prompt,
        n=n,
        size=size,
        quality=quality,
        background=background,
        moderation=moderation,
        fmt=fmt,
        compression=compression,
    )
    if maybe_print_preview(
        {
            "endpoint": "/v1/images/generations",
            "outputs": preview_output_strings(out_paths),
            **payload,
        },
        dry_run=args.dry_run,
    ):
        return 0

    data = post_json(
        build_api_url(runtime["base_url"], "/images/generations"),
        api_key,
        payload,
        runtime["timeout"],
    )
    written = decode_and_save_many(extract_images_from_images_payload(data), out_paths, force=args.force)
    for path in written:
        log(f"generate saved {path}")
        print(str(path))
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    runtime = resolve_runtime()
    api_key = ensure_api_key(runtime)
    input_paths, prompt = resolve_edit_inputs(args)

    mask_path = Path(args.mask).expanduser() if args.mask else None
    if mask_path and not mask_path.is_file():
        fail(f"mask image not found: {mask_path}")

    model = effective_model(args.model, runtime)
    size, quality, fmt, compression, background, moderation, size_note = common_runtime_values(args, runtime)
    validate_input_fidelity(args.input_fidelity)
    n = args.n
    validate_n(n)

    stamp = args.name or f"{input_paths[0].stem}-edited"
    out_paths = resolve_output_paths(
        out_path=args.out,
        out_dir=args.out_dir,
        name_spec=stamp,
        fmt=fmt,
        output_dir=runtime["output_dir"],
        count=n,
    )

    log(
        "edit start "
        f"base_url={runtime['base_url']} model={model} "
        f"size={size} quality={quality} format={fmt} background={background} "
        f"moderation={moderation} n={n} input_images={len(input_paths)} outputs={len(out_paths)}"
    )
    if mask_path:
        log(f"edit mask={mask_path}")
    if size_note:
        log(size_note)

    fields: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "quality": quality,
        "background": background,
        "moderation": moderation,
        "response_format": "b64_json",
        "output_format": fmt,
    }
    if compression is not None:
        fields["output_compression"] = compression
    if args.input_fidelity is not None:
        fields["input_fidelity"] = args.input_fidelity

    files: list[tuple[str, Path]] = [("image", path) for path in input_paths]
    if mask_path:
        files.append(("mask", mask_path))

    preview = dict(fields)
    preview["image"] = [str(path) for path in input_paths]
    if mask_path:
        preview["mask"] = str(mask_path)
    if maybe_print_preview(
        {
            "endpoint": "/v1/images/edits",
            "outputs": preview_output_strings(out_paths),
            **preview,
        },
        dry_run=args.dry_run,
    ):
        return 0

    data = post_multipart(
        build_api_url(runtime["base_url"], "/images/edits"),
        api_key,
        fields,
        files,
        runtime["timeout"],
    )
    written = decode_and_save_many(extract_images_from_images_payload(data), out_paths, force=args.force)
    for path in written:
        log(f"edit saved {path}")
        print(str(path))
    return 0


def run_batch_job(
    *,
    runtime: dict[str, Any],
    api_key: str,
    job: dict[str, Any],
    index: int,
    output_dir: str,
    defaults: dict[str, Any],
    timeout: int,
    force: bool,
    dry_run: bool,
) -> list[str] | str:
    prompt = read_prompt(str(job.get("prompt", "")), None)
    model = str(job.get("model") or defaults["model"])
    size, size_note = normalize_image_size(str(job.get("size") or defaults["size"]))
    quality = str(job.get("quality") or defaults["quality"])
    fmt = validate_format(str(job.get("format") or defaults["format"]))
    compression_value = job.get("compression", defaults["compression"])
    compression = int(compression_value) if compression_value is not None else None
    background = str(job.get("background") or defaults["background"])
    moderation = str(job.get("moderation") or defaults["moderation"])
    n = int(job.get("n") or defaults["n"])

    validate_quality(quality)
    validate_background(background)
    validate_moderation(moderation)
    validate_compression(compression)
    validate_transparency(background, fmt)
    validate_n(n)

    name_spec = str(job.get("name") or f"{index:03d}-{slugify(prompt)}")
    out_paths = resolve_output_paths(
        out_path=job.get("out"),
        out_dir=None,
        name_spec=name_spec,
        fmt=fmt,
        output_dir=output_dir,
        count=n,
    )

    payload = build_generate_payload(
        model=model,
        prompt=prompt,
        n=n,
        size=size,
        quality=quality,
        background=background,
        moderation=moderation,
        fmt=fmt,
        compression=compression,
    )
    preview = {
        "endpoint": "/v1/images/generations",
        "job": index,
        "outputs": preview_output_strings(out_paths),
        **payload,
    }
    if size_note:
        preview["size_note"] = size_note

    if dry_run:
        return json.dumps(preview, ensure_ascii=False, indent=2)

    log(
        "generate-batch job start "
        f"job={index} model={model} size={size} quality={quality} format={fmt} n={n}"
    )
    if size_note:
        log(size_note)
    data = post_json(
        build_api_url(runtime["base_url"], "/images/generations"),
        api_key,
        payload,
        timeout,
    )
    written = decode_and_save_many(extract_images_from_images_payload(data), out_paths, force=force)
    return [str(path) for path in written]


def cmd_generate_batch(args: argparse.Namespace) -> int:
    runtime = resolve_runtime()
    api_key = ensure_api_key(runtime)
    jobs = read_jobs_jsonl(args.input)
    validate_batch_concurrency(args.concurrency)

    defaults = {
        "model": effective_model(args.model, runtime),
        "size": args.size or runtime["size"],
        "quality": args.quality or runtime["quality"],
        "format": args.format or runtime["format"],
        "compression": args.compression if args.compression is not None else runtime["compression"],
        "background": args.background or runtime["background"],
        "moderation": args.moderation or runtime["moderation"],
        "n": args.n,
    }
    validate_n(int(defaults["n"]))
    output_dir = Path(args.out_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for index, job in enumerate(jobs, start=1):
            print(
                run_batch_job(
                    runtime=runtime,
                    api_key=api_key,
                    job=job,
                    index=index,
                    output_dir=str(output_dir),
                    defaults=defaults,
                    timeout=runtime["timeout"],
                    force=args.force,
                    dry_run=True,
                )
            )
        return 0

    pending: dict[Any, int] = {}
    outputs_by_index: dict[int, list[str]] = {}
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for index, job in enumerate(jobs, start=1):
            future = executor.submit(
                run_batch_job,
                runtime=runtime,
                api_key=api_key,
                job=job,
                index=index,
                output_dir=str(output_dir),
                defaults=defaults,
                timeout=runtime["timeout"],
                force=args.force,
                dry_run=False,
            )
            pending[future] = index

        while pending:
            done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                try:
                    outputs = future.result()
                    if isinstance(outputs, list):
                        outputs_by_index[index] = outputs
                        log(f"generate-batch job completed job={index} outputs={len(outputs)}")
                    else:
                        failures.append(f"job {index}: unexpected result")
                except Exception as exc:
                    message = f"job {index} failed: {exc}"
                    failures.append(message)
                    log(message)
                    if args.fail_fast:
                        for pending_future in pending:
                            pending_future.cancel()
                        pending.clear()
                        break

    for index in sorted(outputs_by_index):
        for path in outputs_by_index[index]:
            print(path)

    if failures:
        for message in failures:
            print(message, file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or edit images through an OpenAI-compatible Images API endpoint."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="output file path; for n>1, numbered siblings are created")
    common.add_argument("--out-dir", help="output directory; useful for multi-image results")
    common.add_argument("--name", help="output name prefix when --out is omitted")
    common.add_argument("--model", help="images API model, default from env or Codex config")
    common.add_argument("--size", help="image size or ratio, e.g. 1024x1024, 3840x2160, 16:9, 9:16, or auto")
    common.add_argument("--quality", help="image quality, e.g. low, medium, high, or auto")
    common.add_argument("--background", choices=("auto", "opaque", "transparent"), help="image background behavior")
    common.add_argument("--format", choices=("png", "jpeg", "webp"), help="output format")
    common.add_argument("--compression", type=int, help="output compression for jpeg/webp")
    common.add_argument("--moderation", choices=("auto", "low"), help="image moderation level")
    common.add_argument("--n", type=int, default=1, help="number of images to generate, 1-10")
    common.add_argument("--prompt-file", help="read prompt text from a file")
    common.add_argument("--force", action="store_true", help="overwrite existing output files")
    common.add_argument("--dry-run", action="store_true", help="print the request payload without calling the API")

    gen = sub.add_parser("generate", parents=[common], help="generate a new image")
    gen.add_argument("prompt", nargs="?", help="generation prompt")
    gen.set_defaults(func=cmd_generate)

    edit = sub.add_parser("edit", parents=[common], help="edit one or more existing images")
    edit.add_argument("--image", action="append", help="input image path; repeat to provide multiple images")
    edit.add_argument("--mask", help="optional PNG mask image path")
    edit.add_argument("--input-fidelity", choices=("low", "high"), help="input fidelity hint for images edit")
    edit.add_argument("positional", nargs="*", help="legacy INPUT_IMAGE PROMPT or prompt when --image is used")
    edit.set_defaults(func=cmd_edit)

    batch = sub.add_parser("generate-batch", parents=[common], help="generate many prompts from a JSONL file")
    batch.add_argument("--input", required=True, help="JSONL file containing one prompt or job object per line")
    batch.add_argument("--concurrency", type=int, default=DEFAULT_BATCH_CONCURRENCY, help="number of concurrent requests")
    batch.add_argument("--fail-fast", action="store_true", help="stop after the first failed job")
    batch.set_defaults(func=cmd_generate_batch)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
