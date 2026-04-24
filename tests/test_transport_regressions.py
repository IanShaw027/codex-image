import importlib.util
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "codex-image"
SCRIPT_PATH = SKILL_ROOT / "scripts" / "codex_image.py"
SPEC = importlib.util.spec_from_file_location("codex_image", SCRIPT_PATH)
codex_image = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(codex_image)


class ResponsesTransportRegressionTests(unittest.TestCase):
    def runtime(self, output_dir: str) -> dict[str, object]:
        return {
            "api_key": "key",
            "base_url": "https://example.com",
            "model": codex_image.DEFAULT_MODEL,
            "transport": "images",
            "size": codex_image.DEFAULT_SIZE,
            "quality": codex_image.DEFAULT_QUALITY,
            "format": codex_image.DEFAULT_FORMAT,
            "compression": None,
            "background": codex_image.DEFAULT_BACKGROUND,
            "moderation": codex_image.DEFAULT_MODERATION,
            "timeout": codex_image.DEFAULT_TIMEOUT,
            "output_dir": output_dir,
            "config_path": "/tmp/config.toml",
            "provider_id": None,
            "provider_env_key": None,
        }

    def test_responses_edit_followup_without_input_images_uses_safe_default_name(self):
        parser = codex_image.build_parser()
        args = parser.parse_args(
            [
                "edit",
                "--transport",
                "responses",
                "--previous-response-id",
                "resp_123",
                "--prompt",
                "Keep the composition and make it more realistic",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(codex_image, "resolve_runtime", return_value=self.runtime(tmpdir)):
                with mock.patch.object(codex_image, "maybe_print_preview", return_value=True) as maybe_print_preview:
                    result = codex_image.cmd_edit(args)

        self.assertEqual(result, 0)
        preview = maybe_print_preview.call_args.args[0]
        self.assertEqual(preview["transport"], "responses")
        self.assertTrue(preview["outputs"][0].endswith(".png"))

    def test_responses_edit_dry_run_does_not_clear_active_image_set_when_no_local_images(self):
        parser = codex_image.build_parser()
        args = parser.parse_args(
            [
                "edit",
                "--transport",
                "responses",
                "--previous-response-id",
                "resp_123",
                "--name",
                "resp-followup",
                "--prompt",
                "Keep the composition",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-review"},
                clear=False,
            ):
                base = Path(tmpdir) / "generated_images" / "thread-review"
                base.mkdir(parents=True, exist_ok=True)
                active_path = base / "active_image_set.json"
                original = {
                    "thread_id": "thread-review",
                    "images": ["/tmp/fake-a.png", "/tmp/fake-b.png"],
                }
                active_path.write_text(json.dumps(original), encoding="utf-8")
                with mock.patch.object(codex_image, "resolve_runtime", return_value=self.runtime(tmpdir)):
                    with mock.patch.object(codex_image, "maybe_print_preview", return_value=True):
                        codex_image.cmd_edit(args)

                current = json.loads(active_path.read_text(encoding="utf-8"))

        self.assertEqual(current, original)

    def test_responses_metadata_is_saved_for_followup_reuse(self):
        parser = codex_image.build_parser()
        args = parser.parse_args(
            [
                "generate",
                "--transport",
                "responses",
                "--prompt",
                "Draw a skyline",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "result.png"
            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-meta"},
                clear=False,
            ):
                with mock.patch.object(codex_image, "resolve_runtime", return_value=self.runtime(tmpdir)):
                    with mock.patch.object(
                        codex_image,
                        "post_json",
                        return_value={
                            "id": "resp_123",
                            "output": [
                                {
                                    "type": "image_generation_call",
                                    "id": "ig_123",
                                    "result": "AAAA",
                                }
                            ],
                        },
                    ):
                        with mock.patch.object(codex_image, "decode_and_save_many", return_value=[output_path]):
                            with mock.patch.object(codex_image, "log") as log:
                                codex_image.cmd_generate(args)

                meta_path = Path(tmpdir) / "generated_images" / "thread-meta" / "last_responses_state.json"
                payload = json.loads(meta_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["response_id"], "resp_123")
        self.assertEqual(payload["image_generation_call_ids"], ["ig_123"])
        logged = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertIn("response_id=resp_123", logged)
        self.assertIn("image_generation_call_ids=ig_123", logged)

    def test_normalize_legacy_cli_args_does_not_probe_long_prompt_as_path(self):
        long_prompt = (
            "A cheerful Doraemon, the iconic blue robotic cat from Japanese manga, "
            "round white face and belly, red nose, bell collar, friendly smile, "
            "standing in a bright playful bedroom with soft morning light, polished "
            "digital illustration, clean linework, vibrant colors, high detail, "
            "square composition, no text"
        )

        normalized = codex_image.normalize_legacy_cli_args(
            ["generate", "--prompt", long_prompt]
        )

        self.assertEqual(normalized, ["generate", "--prompt", long_prompt])

    def test_prompt_with_delivery_constraint_skips_standard_api_size(self):
        prompt = "Draw Doraemon"

        actual = codex_image.prompt_with_delivery_constraint(
            prompt,
            api_size="1024x1024",
            delivery_size="1024x1024",
        )

        self.assertEqual(actual, prompt)

    def test_prompt_with_delivery_constraint_keeps_nonstandard_delivery_size(self):
        prompt = "Draw Doraemon"

        actual = codex_image.prompt_with_delivery_constraint(
            prompt,
            api_size="1024x1792",
            delivery_size="1000x1800",
        )

        self.assertIn(prompt, actual)
        self.assertIn("1000x1800", actual)

    def test_read_thread_attachment_turns_caches_inline_user_images(self):
        png_data_url = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W7d0AAAAASUVORK5CYII="
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rollout_path = Path(tmpdir) / "rollout.jsonl"
            rollout_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {"cwd": "/tmp/workspace"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {"cwd": "/tmp/workspace"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "user_message",
                                    "images": [png_data_url],
                                    "local_images": [],
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"CODEX_HOME": tmpdir}, clear=False):
                with mock.patch.object(codex_image, "find_thread_rollout_path", return_value=rollout_path):
                    turns = codex_image.read_thread_attachment_turns("thread-inline")

            self.assertEqual(len(turns), 1)
            images, rollout_cwd = turns[0]
            self.assertEqual(rollout_cwd, Path("/tmp/workspace"))
            self.assertEqual(len(images), 1)
            cached_path = Path(images[0])
            self.assertTrue(cached_path.is_file())
            self.assertEqual(cached_path.parent.name, "rollout_images")

    def test_resolve_image_reference_supports_inline_rollout_attachment_placeholder(self):
        png_data_url = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W7d0AAAAASUVORK5CYII="
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rollout_path = Path(tmpdir) / "rollout.jsonl"
            rollout_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {"cwd": "/tmp/workspace"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "user_message",
                                    "images": [png_data_url],
                                    "local_images": [],
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-inline"},
                clear=False,
            ):
                with mock.patch.object(codex_image, "find_thread_rollout_path", return_value=rollout_path):
                    resolved = codex_image.resolve_image_reference("[Image #1]")

            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.parent.name, "rollout_images")

    def test_read_thread_attachment_turns_caches_remote_user_images(self):
        class FakeResponse:
            def __init__(self, body: bytes, content_type: str) -> None:
                self._body = body
                headers = Message()
                headers.add_header("Content-Type", content_type)
                self.headers = headers

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        remote_url = "https://example.com/reference.png"
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc`\x00\x00"
            b"\x00\x02\x00\x01\xe5'\xd4\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rollout_path = Path(tmpdir) / "rollout.jsonl"
            rollout_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {"cwd": "/tmp/workspace"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "user_message",
                                    "images": [remote_url],
                                    "local_images": [],
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"CODEX_HOME": tmpdir}, clear=False):
                with mock.patch.object(codex_image, "find_thread_rollout_path", return_value=rollout_path):
                    with mock.patch.object(
                        codex_image.request,
                        "urlopen",
                        return_value=FakeResponse(png_bytes, "image/png"),
                    ):
                        turns = codex_image.read_thread_attachment_turns("thread-remote")

            self.assertEqual(len(turns), 1)
            images, rollout_cwd = turns[0]
            self.assertEqual(rollout_cwd, Path("/tmp/workspace"))
            self.assertEqual(len(images), 1)
            cached_path = Path(images[0])
            self.assertTrue(cached_path.is_file())
            self.assertEqual(cached_path.parent.name, "rollout_images")
            self.assertEqual(cached_path.suffix, ".png")

    def test_default_prompt_keeps_executable_launcher_and_boundary(self):
        prompt = yaml.safe_load(
            (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )["interface"]["default_prompt"]

        self.assertLessEqual(len(prompt), 1024)
        self.assertIn("Prefer built-in `imagegen`", prompt)
        self.assertIn("current-turn image context", prompt)
        self.assertIn("explicit local references", prompt)
        self.assertIn("bash", prompt)
        self.assertIn("${CODEX_HOME:-$HOME/.codex}/skills/codex-image/scripts/codex-image", prompt)
        self.assertIn(".cmd", prompt)

    def test_cli_reference_makes_image_placeholder_history_semantics_explicit(self):
        cli_text = (SKILL_ROOT / "references" / "cli.md").read_text(encoding="utf-8")

        self.assertIn(
            "`--image '[Image #N]'` resolves against the most recent attachment-bearing user turn",
            cli_text,
        )
        self.assertIn(
            "They are not the same thing as built-in `imagegen`'s native current-turn runtime image context.",
            cli_text,
        )


if __name__ == "__main__":
    unittest.main()
