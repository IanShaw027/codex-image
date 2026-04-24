#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, NoReturn
from urllib import error, request
from urllib import parse as urlparse

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("python 3.11+ is required") from exc


DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_FORMAT = "png"
DEFAULT_TRANSPORT = "images"
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
ROLLOUT_MAX_BYTES = 8 * 1024 * 1024
THREAD_ATTACHMENT_MAX_TURNS = 256
THREAD_ATTACHMENT_MAX_IMAGES = 1024
OUTPUT_RESIZE_MAX_RATIO_DELTA = 0.05
SIZE_DIMENSION_PATTERN = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")
SIZE_RATIO_PATTERN = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
SIZE_TIER_PATTERN = re.compile(r"^\s*([1-9]\d*)\s*[kK]\s*$")
ATTACHMENT_PLACEHOLDER_PATTERN = re.compile(r"^\s*\[Image\s*#\s*(\d+)\]\s*$", re.IGNORECASE)
TURN_ATTACHMENT_PLACEHOLDER_PATTERN = re.compile(
    r"^\s*\[Turn\s*(-\d+)\s+Image\s*#\s*(\d+)\]\s*$",
    re.IGNORECASE,
)
THREAD_ATTACHMENT_PLACEHOLDER_PATTERN = re.compile(
    r"^\s*\[Thread\s+Image\s*#\s*(\d+)\]\s*$",
    re.IGNORECASE,
)
LAST_OUTPUT_PLACEHOLDER_PATTERN = re.compile(
    r"^\s*\[Last\s+Output(?:\s*#\s*(\d+)\s*)?\]\s*$",
    re.IGNORECASE,
)
DATA_URL_IMAGE_PATTERN = re.compile(
    r"^\s*data:([a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,(.+)\s*$",
    re.IGNORECASE | re.DOTALL,
)
SIZE_RATIO_TIER_PATTERN = re.compile(
    r"^\s*(?:(\d+\s*:\s*\d+)\s*(?:@|,|\s+)\s*([1-9]\d*\s*[kK])|"
    r"([1-9]\d*\s*[kK])\s*(?:@|,|\s+)\s*(\d+\s*:\s*\d+))\s*$"
)


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
    return str(thread_output_dir(thread_id))


def codex_home_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def thread_output_dir(thread_id: str) -> Path:
    return codex_home_dir() / "generated_images" / sanitize_path_segment(thread_id)


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


def parse_ratio(raw_ratio: str) -> tuple[int, int]:
    ratio_match = SIZE_RATIO_PATTERN.match(raw_ratio)
    if not ratio_match:
        fail(f"invalid image ratio: {raw_ratio}")

    width_ratio = int(ratio_match.group(1))
    height_ratio = int(ratio_match.group(2))
    if width_ratio <= 0 or height_ratio <= 0:
        fail(f"invalid image ratio: {raw_ratio}")
    return width_ratio, height_ratio


def parse_size_tier(raw_tier: str) -> int:
    tier_match = SIZE_TIER_PATTERN.match(raw_tier)
    if not tier_match:
        fail(f"invalid image size tier: {raw_tier}")
    return int(tier_match.group(1)) * 1024


def choose_ratio_tier_candidate(width_ratio: int, height_ratio: int, tier_edge: int) -> tuple[int, int]:
    candidates = iter_ratio_candidates(width_ratio, height_ratio)
    ratio = Fraction(width_ratio, height_ratio).limit_denominator(256)

    if ratio.numerator >= ratio.denominator:
        target_height = tier_edge
        target_width = round(tier_edge * ratio.numerator / ratio.denominator)
    else:
        target_width = tier_edge
        target_height = round(tier_edge * ratio.denominator / ratio.numerator)

    return choose_candidate(
        candidates,
        target_width=target_width,
        target_height=target_height,
    )


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

    tier_match = SIZE_TIER_PATTERN.match(raw_spec)
    if tier_match:
        tier_edge = parse_size_tier(raw_spec)
        normalized = f"{tier_edge}x{tier_edge}"
        if validate_image_size(tier_edge, tier_edge) is None:
            return normalized, f"normalized image size {raw_spec} -> {normalized}"
        fail(f"invalid image size tier: {raw_spec}")

    ratio_tier_match = SIZE_RATIO_TIER_PATTERN.match(raw_spec)
    if ratio_tier_match:
        raw_ratio = ratio_tier_match.group(1) or ratio_tier_match.group(4)
        raw_tier = ratio_tier_match.group(2) or ratio_tier_match.group(3)
        width_ratio, height_ratio = parse_ratio(raw_ratio)
        tier_edge = parse_size_tier(raw_tier)
        normalized_width, normalized_height = choose_ratio_tier_candidate(
            width_ratio,
            height_ratio,
            tier_edge,
        )
        normalized = f"{normalized_width}x{normalized_height}"
        return normalized, f"normalized image size {raw_spec} -> {normalized}"

    dim_match = SIZE_DIMENSION_PATTERN.match(raw_spec)
    if dim_match:
        width = int(dim_match.group(1))
        height = int(dim_match.group(2))
        return f"{width}x{height}", None

    ratio_match = SIZE_RATIO_PATTERN.match(raw_spec)
    if ratio_match:
        width_ratio, height_ratio = parse_ratio(raw_spec)

        normalized_width, normalized_height = choose_candidate(
            iter_ratio_candidates(width_ratio, height_ratio)
        )
        normalized = f"{normalized_width}x{normalized_height}"
        return normalized, f"normalized image size {raw_spec} -> {normalized}"

    fail(
        "invalid image size. Use auto, WIDTHxHEIGHT, or WIDTH:HEIGHT "
        "(examples: 3840x2160, 1792x1024, 9:16, 9:16@1k)"
    )


def requested_delivery_size(spec: str, api_size: str) -> str | None:
    raw_spec = spec.strip()
    if raw_spec.lower() == "auto" or api_size == "auto":
        return None

    dim_match = SIZE_DIMENSION_PATTERN.match(raw_spec)
    if dim_match:
        return f"{int(dim_match.group(1))}x{int(dim_match.group(2))}"

    return api_size


def prompt_size_constraint(size: str) -> str | None:
    dim_match = SIZE_DIMENSION_PATTERN.match(size)
    if not dim_match:
        return None

    width = int(dim_match.group(1))
    height = int(dim_match.group(2))
    if width == height:
        orientation = "square"
    elif width > height:
        orientation = "landscape"
    else:
        orientation = "portrait"

    return (
        "Final output constraint: compose for an exact "
        f"{width}x{height} pixel {orientation} canvas. "
        "The generated image should visually match that final canvas size and aspect ratio; "
        "do not imply a different resolution, crop, border, or padding."
    )


def augment_prompt_with_size(prompt: str, size: str) -> str:
    constraint = prompt_size_constraint(size)
    if constraint is None or constraint in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{constraint}"


def prompt_with_delivery_constraint(
    prompt: str,
    *,
    api_size: str,
    delivery_size: str | None,
) -> str:
    if delivery_size is None or delivery_size == api_size:
        return prompt
    return augment_prompt_with_size(prompt, delivery_size)


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
    config_path = Path(os.environ.get("CODEX_CONFIG", codex_home_dir() / "config.toml")).expanduser()
    if not config_path.exists():
        return {}, config_path
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8")), config_path
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"failed to read Codex config {config_path}: {exc}")


def load_codex_auth_api_key() -> str | None:
    auth_path = Path(os.environ.get("CODEX_AUTH_FILE", codex_home_dir() / "auth.json")).expanduser()
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
        "transport": os.environ.get("CODEX_IMAGE_TRANSPORT", DEFAULT_TRANSPORT),
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


def read_prompt(
    prompt: str | None,
    prompt_file: str | None,
    *,
    prompt_flag: str | None = None,
) -> str:
    supplied_prompt_count = sum(
        1 for item in (prompt, prompt_file, prompt_flag) if item
    )
    if supplied_prompt_count > 1:
        fail("use only one of positional prompt, --prompt, or --prompt-file")
    if prompt_file:
        path = Path(prompt_file).expanduser()
        if not path.is_file():
            fail(f"prompt file not found: {path}")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            fail(f"prompt file is empty: {path}")
        return value
    if prompt_flag is not None:
        value = prompt_flag.strip()
        if not value:
            fail("prompt is required")
        return value
    if prompt is None:
        fail("prompt is required")
    value = prompt.strip()
    if not value:
        fail("prompt is required")
    return value


def looks_like_pathish_prompt(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    has_path_separators = any(sep in candidate for sep in (os.sep, "/", "\\"))
    has_path_prefix = candidate.startswith(("~", "."))
    path = Path(candidate).expanduser()
    suffix = path.suffix.lower()
    has_path_suffix = suffix in {".txt", ".md", ".prompt"}
    should_probe_filesystem = (
        len(candidate) < 240
        and "\n" not in candidate
        and not candidate.endswith(".")
        and (
            has_path_separators
            or has_path_prefix
            or has_path_suffix
            or (" " not in candidate and "\t" not in candidate)
        )
    )
    if should_probe_filesystem:
        try:
            if path.is_file():
                return True
        except OSError:
            return False
    if has_path_separators:
        return True
    if has_path_prefix:
        return True
    return has_path_suffix


def normalize_legacy_cli_args(argv: list[str]) -> list[str]:
    if not argv:
        return argv

    command = argv[0]
    if command not in {"generate", "edit"}:
        return argv

    normalized: list[str] = [command]
    i = 1
    while i < len(argv):
        token = argv[i]

        if token.startswith("--prompt-file="):
            normalized.append(token)
            i += 1
            continue

        if token == "--prompt-file":
            normalized.append(token)
            if i + 1 < len(argv):
                normalized.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue

        if token.startswith("--prompt="):
            value = token.split("=", 1)[1]
            if looks_like_pathish_prompt(value):
                normalized.extend(["--prompt-file", value])
            else:
                normalized.append(token)
            i += 1
            continue

        if token == "--prompt":
            if i + 1 < len(argv) and looks_like_pathish_prompt(argv[i + 1]):
                normalized.extend(["--prompt-file", argv[i + 1]])
                i += 2
                continue
            normalized.append(token)
            if i + 1 < len(argv):
                normalized.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue

        if token.startswith("--prom") and "--prompt-file".startswith(token):
            normalized.append("--prompt-file")
            if "=" in token:
                normalized.append(token.split("=", 1)[1])
                i += 1
            elif i + 1 < len(argv):
                normalized.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue

        normalized.append(token)
        i += 1

    return normalized


def random_suffix(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def current_thread_id() -> str | None:
    thread_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
    if not thread_id:
        return None
    normalized = thread_id.strip()
    return normalized or None


def active_image_set_path(thread_id: str) -> Path:
    return thread_output_dir(thread_id) / "active_image_set.json"


def last_output_set_path(thread_id: str) -> Path:
    return thread_output_dir(thread_id) / "last_output_set.json"


def last_responses_state_path(thread_id: str) -> Path:
    return thread_output_dir(thread_id) / "last_responses_state.json"


def rollout_inline_image_dir(thread_id: str) -> Path:
    return thread_output_dir(thread_id) / "rollout_images"


def find_thread_rollout_path(thread_id: str) -> Path:
    sessions_dir = codex_home_dir() / "sessions"
    matches = sorted(sessions_dir.rglob(f"rollout-*-{thread_id}.jsonl"))
    if not matches:
        fail(f"could not find Codex session rollout for thread {thread_id}")
    return matches[-1]


def resolve_existing_path(
    raw: str,
    *,
    base_dir: Path | None = None,
    allow_cwd_fallback: bool = True,
    allow_raw_relative_path: bool = True,
) -> Path | None:
    path = Path(raw).expanduser()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        if base_dir is not None:
            candidates.append((base_dir / path).expanduser())
        if allow_cwd_fallback:
            candidates.append((Path.cwd() / path).expanduser())
        if allow_raw_relative_path:
            candidates.append(path)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_rollout_path(raw: str, *, rollout_cwd: Path | None) -> Path | None:
    return resolve_existing_path(
        raw,
        base_dir=rollout_cwd,
        allow_cwd_fallback=False,
        allow_raw_relative_path=False,
    )


def flatten_thread_attachments(
    attachment_turns: list[tuple[list[str], Path | None]],
) -> list[tuple[str, Path | None]]:
    flattened: list[tuple[str, Path | None]] = []
    for images, rollout_cwd in attachment_turns:
        for image in images:
            flattened.append((image, rollout_cwd))
            if len(flattened) > THREAD_ATTACHMENT_MAX_IMAGES:
                fail(
                    "thread attachment history is too large to index safely "
                    f"(max {THREAD_ATTACHMENT_MAX_IMAGES} attachment(s))"
                )
    return flattened


def cache_rollout_inline_image(thread_id: str, raw: str) -> str | None:
    match = DATA_URL_IMAGE_PATTERN.match(raw)
    if not match:
        return None
    mime = match.group(1).lower()
    if not mime.startswith("image/"):
        return None
    encoded = match.group(2).strip()
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception:
        return None

    suffix = mimetypes.guess_extension(mime) or ".img"
    if suffix == ".jpe":
        suffix = ".jpg"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    path = ensure_parent(rollout_inline_image_dir(thread_id) / f"{digest}{suffix}")
    if not path.is_file():
        path.write_bytes(decoded)
    return str(path.resolve())


def cache_rollout_remote_image(thread_id: str, raw: str) -> str | None:
    try:
        parsed = urlparse.urlparse(raw.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    try:
        with request.urlopen(raw, timeout=20) as response:
            content_type = response.headers.get_content_type().lower()
            if not content_type.startswith("image/"):
                return None
            decoded = response.read()
    except Exception:
        return None

    suffix = mimetypes.guess_extension(content_type) or Path(parsed.path).suffix or ".img"
    if suffix == ".jpe":
        suffix = ".jpg"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    path = ensure_parent(rollout_inline_image_dir(thread_id) / f"{digest}{suffix}")
    if not path.is_file():
        path.write_bytes(decoded)
    return str(path.resolve())


def resolve_rollout_image_reference(thread_id: str, raw: str) -> str | None:
    cached = cache_rollout_inline_image(thread_id, raw)
    if cached is not None:
        return cached
    cached = cache_rollout_remote_image(thread_id, raw)
    if cached is not None:
        return cached
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def read_thread_attachment_turns(thread_id: str) -> list[tuple[list[str], Path | None]]:
    rollout_path = find_thread_rollout_path(thread_id)
    try:
        if rollout_path.stat().st_size > ROLLOUT_MAX_BYTES:
            fail(
                "Codex session rollout is too large to scan safely for attachment placeholders "
                f"({rollout_path.stat().st_size} bytes > {ROLLOUT_MAX_BYTES} byte limit)"
            )
    except OSError as exc:
        fail(f"failed to inspect rollout file {rollout_path}: {exc}")

    default_rollout_cwd: Path | None = None
    current_turn_cwd: Path | None = None
    attachment_turns: list[tuple[list[str], Path | None]] = []

    for raw_line in rollout_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            fail(f"failed to parse rollout file {rollout_path}: {exc}")

        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        if entry.get("type") == "session_meta":
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                default_rollout_cwd = Path(cwd).expanduser()
                current_turn_cwd = default_rollout_cwd
            continue

        if entry.get("type") == "turn_context":
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                current_turn_cwd = Path(cwd).expanduser()
            else:
                current_turn_cwd = default_rollout_cwd
            continue

        if entry.get("type") != "event_msg" or payload.get("type") != "user_message":
            continue

        resolved_images: list[str] = []
        local_images = payload.get("local_images")
        if isinstance(local_images, list):
            resolved_images.extend(str(item) for item in local_images if isinstance(item, str) and item.strip())
        images = payload.get("images")
        if isinstance(images, list):
            resolved_images.extend(
                resolved
                for item in images
                if isinstance(item, str)
                for resolved in [resolve_rollout_image_reference(thread_id, item)]
                if resolved is not None
            )
        if resolved_images:
            attachment_turns.append((resolved_images, current_turn_cwd))
            if len(attachment_turns) > THREAD_ATTACHMENT_MAX_TURNS:
                fail(
                    "thread attachment history is too large to scan safely "
                    f"(max {THREAD_ATTACHMENT_MAX_TURNS} attachment-bearing turn(s))"
                )
    return attachment_turns


def load_thread_attachment_turns(thread_id: str) -> list[tuple[list[str], Path | None]]:
    attachment_turns = read_thread_attachment_turns(thread_id)

    if not attachment_turns:
        fail(
            "no image attachments were found in the Codex session rollout; "
            "use a real file path or attach the image in the current conversation first"
        )
    return attachment_turns


def latest_attachment_turn(thread_id: str) -> tuple[list[str], Path | None] | None:
    attachment_turns = read_thread_attachment_turns(thread_id)
    if not attachment_turns:
        return None
    return attachment_turns[-1]


def dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def load_active_image_set(thread_id: str) -> list[Path]:
    path = active_image_set_path(thread_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"failed to read active image set {path}: {exc}")

    raw_images = payload.get("images")
    if not isinstance(raw_images, list):
        return []

    resolved_paths: list[Path] = []
    for item in raw_images:
        if not isinstance(item, str):
            continue
        resolved = resolve_existing_path(item)
        if resolved is not None:
            resolved_paths.append(resolved)
    return dedupe_paths(resolved_paths)


def save_active_image_set(thread_id: str, images: list[Path]) -> None:
    path = active_image_set_path(thread_id)
    ensure_parent(path)
    payload = {
        "thread_id": thread_id,
        "images": [str(path_item.resolve()) for path_item in dedupe_paths(images)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_output_set(thread_id: str) -> list[Path]:
    path = last_output_set_path(thread_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"failed to read last output set {path}: {exc}")

    raw_images = payload.get("images")
    if not isinstance(raw_images, list):
        return []

    resolved_paths: list[Path] = []
    for item in raw_images:
        if not isinstance(item, str):
            continue
        resolved = resolve_existing_path(item)
        if resolved is not None:
            resolved_paths.append(resolved)
    return dedupe_paths(resolved_paths)


def save_last_output_set(thread_id: str, images: list[Path]) -> None:
    path = last_output_set_path(thread_id)
    ensure_parent(path)
    payload = {
        "thread_id": thread_id,
        "images": [str(path_item.resolve()) for path_item in dedupe_paths(images)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_last_responses_state(
    thread_id: str,
    *,
    response_id: str | None,
    image_generation_call_ids: list[str],
) -> None:
    path = last_responses_state_path(thread_id)
    ensure_parent(path)
    payload = {
        "thread_id": thread_id,
        "response_id": response_id,
        "image_generation_call_ids": image_generation_call_ids,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_image_set_selector(selector: str, thread_id: str) -> list[Path]:
    normalized = selector.strip()
    if normalized == "active":
        return load_active_image_set(thread_id)
    if normalized == "last-output":
        return load_last_output_set(thread_id)
    if normalized == "latest-turn":
        latest = latest_attachment_turn(thread_id)
        if latest is None:
            return []
        images, rollout_cwd = latest
        return [resolve_attachment_from_turn(str(index), images=images, rollout_cwd=rollout_cwd) for index in range(1, len(images) + 1)]
    if normalized.startswith("turn:"):
        offset_text = normalized.split(":", 1)[1].strip()
        try:
            offset = int(offset_text)
        except ValueError:
            fail(f"invalid image-set selector: {selector}")
        if offset >= 0:
            fail(f"turn image-set selectors must use a negative offset: {selector}")
        attachment_turns = load_thread_attachment_turns(thread_id)
        turn_index = len(attachment_turns) - 1 + offset
        if turn_index < 0 or turn_index >= len(attachment_turns):
            fail(
                f"image-set selector {selector} is out of range for this thread "
                f"({len(attachment_turns)} attachment-bearing turn(s))"
            )
        images, rollout_cwd = attachment_turns[turn_index]
        return [resolve_attachment_from_turn(str(index), images=images, rollout_cwd=rollout_cwd) for index in range(1, len(images) + 1)]
    if normalized.startswith("thread:"):
        indexes_text = normalized.split(":", 1)[1].strip()
        if not indexes_text:
            fail(f"invalid image-set selector: {selector}")
        attachment_turns = load_thread_attachment_turns(thread_id)
        flattened = flatten_thread_attachments(attachment_turns)
        selected_paths: list[Path] = []
        for chunk in indexes_text.split(","):
            chunk = chunk.strip()
            try:
                index = int(chunk) - 1
            except ValueError:
                fail(f"invalid image-set selector: {selector}")
            if index < 0 or index >= len(flattened):
                fail(
                    f"image-set selector {selector} is out of range for this thread "
                    f"({len(flattened)} attachment(s))"
                )
            image, rollout_cwd = flattened[index]
            resolved = resolve_rollout_path(image, rollout_cwd=rollout_cwd)
            if resolved is None:
                cwd_text = f" with rollout cwd {rollout_cwd}" if rollout_cwd is not None else ""
                fail(f"attached image path could not be resolved to a file: {image}{cwd_text}")
            selected_paths.append(resolved)
        return dedupe_paths(selected_paths)
    fail(f"unsupported image-set selector: {selector}")


def resolve_flattened_attachment(image: str, *, rollout_cwd: Path | None) -> Path:
    resolved = resolve_rollout_path(image, rollout_cwd=rollout_cwd)
    if resolved is None:
        cwd_text = f" with rollout cwd {rollout_cwd}" if rollout_cwd is not None else ""
        fail(f"attached image path could not be resolved to a file: {image}{cwd_text}")
    return resolved


def resolve_attachment_from_turn(
    raw: str,
    *,
    images: list[str],
    rollout_cwd: Path | None,
) -> Path:
    index = int(raw) - 1
    if index < 0 or index >= len(images):
        fail(
            f"attachment placeholder index {index + 1} is out of range for the selected turn "
            f"({len(images)} attachment(s))"
        )
    selected = images[index]
    return resolve_flattened_attachment(selected, rollout_cwd=rollout_cwd)


def resolve_dash_image_sequence(raw_values: list[str], thread_id: str) -> list[Path] | None:
    if not raw_values or not all(raw.strip() == "-" for raw in raw_values):
        return None
    attachment_turns = load_thread_attachment_turns(thread_id)
    latest_images, latest_rollout_cwd = attachment_turns[-1]
    if len(raw_values) <= len(latest_images):
        return [
            resolve_attachment_from_turn(str(index), images=latest_images, rollout_cwd=latest_rollout_cwd)
            for index in range(1, len(raw_values) + 1)
        ]
    flattened = flatten_thread_attachments(attachment_turns)
    if len(raw_values) <= len(flattened):
        return [
            resolve_flattened_attachment(image, rollout_cwd=rollout_cwd)
            for image, rollout_cwd in flattened[: len(raw_values)]
        ]
    return None


def resolve_sequential_current_placeholders(raw_values: list[str], thread_id: str) -> list[Path] | None:
    if not raw_values:
        return None
    indexes: list[int] = []
    for raw in raw_values:
        match = ATTACHMENT_PLACEHOLDER_PATTERN.match(raw)
        if not match:
            return None
        indexes.append(int(match.group(1)))
    if indexes != list(range(1, len(raw_values) + 1)):
        return None

    attachment_turns = load_thread_attachment_turns(thread_id)
    latest_images, _latest_rollout_cwd = attachment_turns[-1]
    if len(indexes) <= len(latest_images):
        return None

    flattened = flatten_thread_attachments(attachment_turns)
    if len(indexes) > len(flattened):
        return None
    return [
        resolve_flattened_attachment(image, rollout_cwd=rollout_cwd)
        for image, rollout_cwd in flattened[: len(indexes)]
    ]


def resolve_image_reference(raw: str) -> Path:
    thread_id = current_thread_id()
    attachment_match = ATTACHMENT_PLACEHOLDER_PATTERN.match(raw)
    turn_match = TURN_ATTACHMENT_PLACEHOLDER_PATTERN.match(raw)
    thread_match = THREAD_ATTACHMENT_PLACEHOLDER_PATTERN.match(raw)
    last_output_match = LAST_OUTPUT_PLACEHOLDER_PATTERN.match(raw)

    if attachment_match or turn_match or thread_match or last_output_match:
        if thread_id is None:
            fail("image attachment placeholders require CODEX_THREAD_ID or CODEX_SESSION_ID")
        if last_output_match:
            outputs = load_last_output_set(thread_id)
            index = int(last_output_match.group(1) or "1") - 1
            if index < 0 or index >= len(outputs):
                fail(
                    f"last output placeholder {raw.strip()} is out of range for this thread "
                    f"({len(outputs)} saved output(s))"
                )
            return outputs[index]

        attachment_turns = load_thread_attachment_turns(thread_id)

        if attachment_match:
            images, rollout_cwd = attachment_turns[-1]
            return resolve_attachment_from_turn(
                attachment_match.group(1),
                images=images,
                rollout_cwd=rollout_cwd,
            )

        if turn_match:
            turn_offset = int(turn_match.group(1))
            if turn_offset >= 0:
                fail(f"turn attachment placeholders must use a negative offset: {raw.strip()}")
            turn_index = len(attachment_turns) - 1 + turn_offset
            if turn_index < 0 or turn_index >= len(attachment_turns):
                fail(
                    f"turn attachment placeholder {raw.strip()} is out of range for this thread "
                    f"({len(attachment_turns)} attachment-bearing turn(s))"
                )
            images, rollout_cwd = attachment_turns[turn_index]
            return resolve_attachment_from_turn(
                turn_match.group(2),
                images=images,
                rollout_cwd=rollout_cwd,
            )

        flattened = flatten_thread_attachments(attachment_turns)

        index = int(thread_match.group(1)) - 1
        if index < 0 or index >= len(flattened):
            fail(
                f"thread attachment placeholder {raw.strip()} is out of range for this thread "
                f"({len(flattened)} attachment(s))"
            )
        selected, rollout_cwd = flattened[index]
        return resolve_flattened_attachment(selected, rollout_cwd=rollout_cwd)

    resolved = resolve_existing_path(raw)
    if resolved is None:
        fail(f"input image not found: {Path(raw).expanduser()}")
    return resolved


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


def parse_direct_size(size: str | None) -> tuple[int, int] | None:
    if not size:
        return None
    dim_match = SIZE_DIMENSION_PATTERN.match(size)
    if not dim_match:
        return None
    return int(dim_match.group(1)), int(dim_match.group(2))


def read_image_dimensions(path: Path) -> tuple[int, int] | None:
    if shutil.which("sips") is None:
        return None
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    width = None
    height = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("pixelWidth:"):
            width = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("pixelHeight:"):
            height = int(stripped.split(":", 1)[1].strip())
    if width is None or height is None:
        return None
    return width, height


def resize_image_to_size(path: Path, width: int, height: int) -> None:
    if shutil.which("sips") is None:
        fail(
            f"generated image {path} does not match requested size and local sips is unavailable "
            "for post-processing"
        )
    result = subprocess.run(
        ["sips", "-z", str(height), str(width), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"failed to resize generated image {path}: {result.stderr.strip() or result.stdout.strip()}")


def ensure_output_dimensions(path: Path, expected_size: str | None) -> None:
    expected = parse_direct_size(expected_size)
    if expected is None:
        return

    actual = read_image_dimensions(path)
    if actual is None:
        log(f"could not verify output dimensions for {path}")
        return
    if actual == expected:
        log(f"verified output size {path}: {actual[0]}x{actual[1]}")
        return

    expected_ratio = expected[0] / expected[1]
    actual_ratio = actual[0] / actual[1]
    ratio_delta = abs(actual_ratio - expected_ratio) / expected_ratio
    if ratio_delta > OUTPUT_RESIZE_MAX_RATIO_DELTA:
        fail(
            f"generated image aspect ratio differs too much for automatic resize: "
            f"expected {expected[0]}x{expected[1]} ({expected_ratio:.4f}), "
            f"got {actual[0]}x{actual[1]} ({actual_ratio:.4f}). "
            "Do not stretch automatically; ask the user whether to retry generation, crop to cover, "
            "pad to contain, or force stretch."
        )

    resize_image_to_size(path, expected[0], expected[1])
    resized = read_image_dimensions(path)
    if resized != expected:
        actual_text = "unknown" if resized is None else f"{resized[0]}x{resized[1]}"
        fail(f"post-resize output size mismatch for {path}: expected {expected_size}, got {actual_text}")
    log(
        f"resized output {path}: {actual[0]}x{actual[1]} -> "
        f"{expected[0]}x{expected[1]}"
    )


def decode_and_save_many(
    images_b64: list[str],
    out_paths: list[Path],
    *,
    force: bool,
    expected_size: str | None,
) -> list[Path]:
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
        ensure_output_dimensions(out_path, expected_size)
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


def encode_image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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


def extract_images_from_responses_payload(data: dict[str, Any]) -> list[str]:
    output = data.get("output") or []
    if not isinstance(output, list):
        fail(
            "image generation result missing in responses payload:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )
    results: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "image_generation_call":
            continue
        result = item.get("result")
        if isinstance(result, str) and result:
            results.append(result)
    if not results:
        fail(
            "image generation result missing in responses payload:\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )
    return results


def extract_responses_metadata(data: dict[str, Any]) -> tuple[str | None, list[str]]:
    response_id = data.get("id")
    normalized_response_id = response_id if isinstance(response_id, str) and response_id else None
    output = data.get("output") or []
    if not isinstance(output, list):
        return normalized_response_id, []
    image_generation_call_ids: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "image_generation_call":
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            image_generation_call_ids.append(item_id)
    return normalized_response_id, image_generation_call_ids


def effective_model(args_model: str | None, runtime: dict[str, Any]) -> str:
    return args_model or runtime["model"]


def effective_transport(args_transport: str | None, runtime: dict[str, Any]) -> str:
    transport = (args_transport or runtime["transport"]).strip().lower()
    if transport not in {"images", "responses"}:
        fail("transport must be one of images or responses")
    return transport


def validate_responses_transport_options(
    *,
    fmt: str,
    compression: int | None,
    mask_path: Path | None,
    input_fidelity: str | None,
) -> None:
    if fmt != "png":
        fail("responses transport currently supports png output only")
    if compression is not None:
        fail("responses transport currently does not support output compression")
    if mask_path is not None:
        fail("responses transport currently does not support mask uploads")
    if input_fidelity is not None:
        fail("responses transport currently does not support input-fidelity")


def build_responses_tool(
    *,
    action: str,
    size: str,
    quality: str,
    background: str,
    moderation: str,
    n: int,
) -> dict[str, Any]:
    return {
        "type": "image_generation",
        "action": action,
        "size": size,
        "quality": quality,
        "background": background,
        "moderation": moderation,
        "n": n,
    }


def build_responses_generate_payload(
    *,
    model: str,
    prompt: str,
    tool: dict[str, Any],
    previous_response_id: str | None,
    response_image_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "tools": [tool],
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    if response_image_id:
        payload["input"] = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
            {"type": "image_generation_call", "id": response_image_id},
        ]
    else:
        payload["input"] = prompt
    return payload


def build_responses_edit_payload(
    *,
    model: str,
    prompt: str,
    input_paths: list[Path],
    tool: dict[str, Any],
    previous_response_id: str | None,
    response_image_id: str | None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        {"type": "input_image", "image_url": encode_image_data_url(path)}
        for path in input_paths
    )
    payload: dict[str, Any] = {
        "model": model,
        "tools": [tool],
        "input": [{"role": "user", "content": content}],
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    if response_image_id:
        payload["input"].append({"type": "image_generation_call", "id": response_image_id})
    return payload


def common_runtime_values(
    args: argparse.Namespace,
    runtime: dict[str, Any],
) -> tuple[str, str | None, str, str, int | None, str, str, str | None]:
    requested_size = args.size or runtime["size"]
    size, size_note = normalize_image_size(requested_size)
    delivery_size = requested_delivery_size(requested_size, size)
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
    return size, delivery_size, quality, fmt, compression, background, moderation, size_note


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


def resolve_edit_inputs(
    args: argparse.Namespace,
    *,
    allow_empty_images: bool = False,
) -> tuple[list[Path], str]:
    raw_values: list[str] = []
    selector_values: list[str] = list(getattr(args, "image_set", []) or [])
    positional = list(getattr(args, "positional", []) or [])

    if getattr(args, "image", None):
        raw_values.extend(args.image)
        if len(positional) > 1:
            fail(
                "when --image is used, provide prompt as one trailing argument, "
                "use --prompt, or use --prompt-file"
            )
        prompt_arg = positional[0] if positional else None
    else:
        if len(positional) > 2:
            fail("edit expects INPUT_IMAGE PROMPT when --image is not used")
        if len(positional) == 2:
            raw_values.append(positional[0])
            prompt_arg = positional[1]
        else:
            if positional and (args.prompt_flag is not None or args.prompt_file is not None):
                raw_values.append(positional[0])
                prompt_arg = None
            else:
                prompt_arg = positional[0] if positional else None

    thread_id = current_thread_id()
    selected_paths: list[Path] = []

    for selector in selector_values:
        if thread_id is None:
            fail("image-set selectors require CODEX_THREAD_ID or CODEX_SESSION_ID")
        selected_paths.extend(resolve_image_set_selector(selector, thread_id))

    if raw_values and thread_id is not None:
        dash_paths = resolve_dash_image_sequence(raw_values, thread_id)
        if dash_paths is not None:
            selected_paths.extend(dash_paths)
            raw_values = []
        else:
            sequential_paths = resolve_sequential_current_placeholders(raw_values, thread_id)
            if sequential_paths is not None:
                selected_paths.extend(sequential_paths)
                raw_values = []

    for raw in raw_values:
        selected_paths.append(resolve_image_reference(raw))

    paths = dedupe_paths(selected_paths)
    if not paths and not allow_empty_images:
        fail("at least one input image is required")
    if len(paths) > IMAGE_MAX_EDIT_IMAGES:
        fail(f"at most {IMAGE_MAX_EDIT_IMAGES} input images are supported for edit")
    return paths, read_prompt(prompt_arg, args.prompt_file, prompt_flag=args.prompt_flag)


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


def redirect_generate_args_to_edit(args: argparse.Namespace) -> argparse.Namespace:
    redirected = argparse.Namespace(**vars(args))
    redirected.command = "edit"
    redirected.func = cmd_edit
    redirected.positional = [args.prompt] if args.prompt else []
    redirected.prompt_flag = args.prompt_flag
    redirected.mask = None
    redirected.input_fidelity = None
    redirected.image_set = []
    redirected.reset_image_set = False
    return redirected


def cmd_generate(args: argparse.Namespace) -> int:
    if getattr(args, "image", None):
        log("redirecting generate --image request to edit")
        return cmd_edit(redirect_generate_args_to_edit(args))
    runtime = resolve_runtime()
    api_key = ensure_api_key(runtime)
    prompt = read_prompt(args.prompt, args.prompt_file, prompt_flag=args.prompt_flag)
    model = effective_model(args.model, runtime)
    transport = effective_transport(getattr(args, "transport", None), runtime)
    size, delivery_size, quality, fmt, compression, background, moderation, size_note = common_runtime_values(args, runtime)
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
        f"transport={transport} "
        f"size={size} quality={quality} format={fmt} background={background} "
        f"moderation={moderation} n={n} outputs={len(out_paths)}"
    )
    if size_note:
        log(size_note)

    prompt = prompt_with_delivery_constraint(
        prompt,
        api_size=size,
        delivery_size=delivery_size,
    )
    if transport == "images":
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
            "transport": transport,
            "outputs": preview_output_strings(out_paths),
            **payload,
        }
    else:
        validate_responses_transport_options(
            fmt=fmt,
            compression=compression,
            mask_path=None,
            input_fidelity=None,
        )
        payload = build_responses_generate_payload(
            model=model,
            prompt=prompt,
            tool=build_responses_tool(
                action="generate",
                size=size,
                quality=quality,
                background=background,
                moderation=moderation,
                n=n,
            ),
            previous_response_id=getattr(args, "previous_response_id", None),
            response_image_id=getattr(args, "response_image_id", None),
        )
        preview = {
            "endpoint": "/v1/responses",
            "transport": transport,
            "outputs": preview_output_strings(out_paths),
            **payload,
        }
    if maybe_print_preview(
        preview,
        dry_run=args.dry_run,
    ):
        return 0

    if transport == "images":
        data = post_json(
            build_api_url(runtime["base_url"], "/images/generations"),
            api_key,
            payload,
            runtime["timeout"],
        )
        images = extract_images_from_images_payload(data)
    else:
        data = post_json(
            build_api_url(runtime["base_url"], "/responses"),
            api_key,
            payload,
            runtime["timeout"],
        )
        images = extract_images_from_responses_payload(data)
        response_id, image_generation_call_ids = extract_responses_metadata(data)
    written = decode_and_save_many(
        images,
        out_paths,
        force=args.force,
        expected_size=delivery_size,
    )
    thread_id = current_thread_id()
    if thread_id is not None:
        save_last_output_set(thread_id, written)
        if transport == "responses":
            save_last_responses_state(
                thread_id,
                response_id=response_id,
                image_generation_call_ids=image_generation_call_ids,
            )
    if transport == "responses":
        if response_id:
            log(f"responses response_id={response_id}")
        if image_generation_call_ids:
            log(f"responses image_generation_call_ids={','.join(image_generation_call_ids)}")
    for path in written:
        log(f"generate saved {path}")
        print(str(path))
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    runtime = resolve_runtime()
    api_key = ensure_api_key(runtime)
    transport = effective_transport(getattr(args, "transport", None), runtime)
    allow_empty_images = transport == "responses" and bool(
        getattr(args, "previous_response_id", None) or getattr(args, "response_image_id", None)
    )
    input_paths, prompt = resolve_edit_inputs(args, allow_empty_images=allow_empty_images)

    mask_path = resolve_image_reference(args.mask) if args.mask else None

    model = effective_model(args.model, runtime)
    size, delivery_size, quality, fmt, compression, background, moderation, size_note = common_runtime_values(args, runtime)
    validate_input_fidelity(args.input_fidelity)
    n = args.n
    validate_n(n)

    if args.name:
        stamp = args.name
    elif input_paths:
        stamp = f"{input_paths[0].stem}-edited"
    elif transport == "responses":
        stamp = "responses-edit"
    else:
        fail("at least one input image is required")
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
        f"transport={transport} "
        f"size={size} quality={quality} format={fmt} background={background} "
        f"moderation={moderation} n={n} input_images={len(input_paths)} outputs={len(out_paths)}"
    )
    if mask_path:
        log(f"edit mask={mask_path}")
    if size_note:
        log(size_note)

    prompt = prompt_with_delivery_constraint(
        prompt,
        api_size=size,
        delivery_size=delivery_size,
    )
    if transport == "images":
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
        endpoint = "/v1/images/edits"
        payload = fields
    else:
        validate_responses_transport_options(
            fmt=fmt,
            compression=compression,
            mask_path=mask_path,
            input_fidelity=args.input_fidelity,
        )
        payload = build_responses_edit_payload(
            model=model,
            prompt=prompt,
            input_paths=input_paths,
            tool=build_responses_tool(
                action="edit",
                size=size,
                quality=quality,
                background=background,
                moderation=moderation,
                n=n,
            ),
            previous_response_id=getattr(args, "previous_response_id", None),
            response_image_id=getattr(args, "response_image_id", None),
        )
        preview = {
            **payload,
            "input_image_paths": [str(path) for path in input_paths],
        }
        endpoint = "/v1/responses"
    thread_id = current_thread_id()
    if maybe_print_preview(
        {
            "endpoint": endpoint,
            "transport": transport,
            "outputs": preview_output_strings(out_paths),
            **preview,
        },
        dry_run=args.dry_run,
    ):
        if thread_id is not None and input_paths:
            save_active_image_set(thread_id, input_paths)
        return 0

    if transport == "images":
        data = post_multipart(
            build_api_url(runtime["base_url"], "/images/edits"),
            api_key,
            fields,
            files,
            runtime["timeout"],
        )
        images = extract_images_from_images_payload(data)
    else:
        data = post_json(
            build_api_url(runtime["base_url"], "/responses"),
            api_key,
            payload,
            runtime["timeout"],
        )
        images = extract_images_from_responses_payload(data)
        response_id, image_generation_call_ids = extract_responses_metadata(data)
    written = decode_and_save_many(
        images,
        out_paths,
        force=args.force,
        expected_size=delivery_size,
    )
    if thread_id is not None:
        if input_paths:
            save_active_image_set(thread_id, input_paths)
        save_last_output_set(thread_id, written)
        if transport == "responses":
            save_last_responses_state(
                thread_id,
                response_id=response_id,
                image_generation_call_ids=image_generation_call_ids,
            )
    if transport == "responses":
        if response_id:
            log(f"responses response_id={response_id}")
        if image_generation_call_ids:
            log(f"responses image_generation_call_ids={','.join(image_generation_call_ids)}")
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
    requested_size = str(job.get("size") or defaults["size"])
    size, size_note = normalize_image_size(requested_size)
    delivery_size = requested_delivery_size(requested_size, size)
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
        prompt=prompt_with_delivery_constraint(
            prompt,
            api_size=size,
            delivery_size=delivery_size,
        ),
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
    written = decode_and_save_many(
        extract_images_from_images_payload(data),
        out_paths,
        force=force,
        expected_size=delivery_size,
    )
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
    output_dir = Path(args.out_dir or runtime["output_dir"]).expanduser()
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
        description="Generate or edit images through an OpenAI-compatible Images API endpoint.",
        prog="codex-image",
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

    transport = argparse.ArgumentParser(add_help=False)
    transport.add_argument(
        "--transport",
        choices=("images", "responses"),
        help="upstream transport: default images API, or explicit responses API for multi-turn image generation state",
    )
    transport.add_argument(
        "--previous-response-id",
        help="responses API previous_response_id for explicit multi-turn follow-up state",
    )
    transport.add_argument(
        "--response-image-id",
        help="responses API image_generation_call id to continue refining a specific prior generated image",
    )

    gen = sub.add_parser(
        "generate",
        parents=[common, transport],
        help="generate a new image",
        prog="codex-image generate",
    )
    gen.add_argument(
        "--image",
        action="append",
        help="reference image path or attachment placeholder like [Image #1] or [Last Output]; warns and redirects to edit when provided",
    )
    gen.add_argument(
        "--prompt",
        dest="prompt_flag",
        metavar="PROMPT",
        help="explicit prompt text; use this instead of positional prompt when quoting would be awkward",
    )
    gen.add_argument("prompt", nargs="?", help="generation prompt")
    gen.set_defaults(func=cmd_generate)

    edit = sub.add_parser(
        "edit",
        parents=[common, transport],
        help="edit one or more existing images",
        prog="codex-image edit",
    )
    edit.add_argument(
        "--image",
        action="append",
        help="input image path or Codex attachment placeholder like [Image #1] or [Last Output]; repeat to provide multiple images",
    )
    edit.add_argument(
        "--prompt",
        dest="prompt_flag",
        metavar="PROMPT",
        help="explicit prompt text; use this instead of positional prompt when quoting would be awkward",
    )
    edit.add_argument(
        "--image-set",
        action="append",
        help="image set selector: active, last-output, latest-turn, turn:-K, or thread:1,2,5; repeat to merge selectors",
    )
    edit.add_argument(
        "--reset-image-set",
        action="store_true",
        help="compatibility flag retained for older calls; explicit --image-set selectors are required",
    )
    edit.add_argument("--mask", help="optional PNG mask image path or attachment placeholder like [Image #1] or [Last Output]")
    edit.add_argument("--input-fidelity", choices=("low", "high"), help="input fidelity hint for images edit")
    edit.add_argument("positional", nargs="*", help="legacy INPUT_IMAGE PROMPT or prompt when --image is used")
    edit.set_defaults(func=cmd_edit)

    batch = sub.add_parser(
        "generate-batch",
        parents=[common],
        help="generate many prompts from a JSONL file",
        prog="codex-image generate-batch",
        allow_abbrev=False,
    )
    batch.add_argument("--input", required=True, help="JSONL file containing one prompt or job object per line")
    batch.add_argument("--concurrency", type=int, default=DEFAULT_BATCH_CONCURRENCY, help="number of concurrent requests")
    batch.add_argument("--fail-fast", action="store_true", help="stop after the first failed job")
    batch.set_defaults(func=cmd_generate_batch)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_legacy_cli_args(sys.argv[1:]))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
