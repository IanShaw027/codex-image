import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "codex-image"
SCRIPT_PATH = SKILL_ROOT / "scripts" / "codex_image.py"
OPENAI_YAML_PATH = SKILL_ROOT / "agents" / "openai.yaml"
SPEC = importlib.util.spec_from_file_location("codex_image", SCRIPT_PATH)
codex_image = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(codex_image)


class SizeNormalizationTests(unittest.TestCase):
    def test_skill_default_prompt_stays_within_loader_limit(self):
        contents = OPENAI_YAML_PATH.read_text(encoding="utf-8")
        match = re.search(r'^\s{2}default_prompt:\s+"(.*)"\s*$', contents, re.MULTILINE)

        self.assertIsNotNone(match)
        default_prompt = match.group(1)
        self.assertLessEqual(len(default_prompt), 1024)

    def test_plain_ratio_still_maps_to_largest_valid_size(self):
        self.assertEqual(codex_image.normalize_image_size("9:16")[0], "2160x3840")

    def test_ratio_tier_maps_to_short_edge_resolution(self):
        self.assertEqual(codex_image.normalize_image_size("9:16 1k")[0], "1008x1792")
        self.assertEqual(codex_image.normalize_image_size("9:16@2k")[0], "2016x3584")
        self.assertEqual(codex_image.normalize_image_size("9:16@4k")[0], "2160x3840")

    def test_tier_ratio_order_is_flexible(self):
        self.assertEqual(codex_image.normalize_image_size("1k@16:9")[0], "1792x1008")

    def test_prompt_is_augmented_with_final_canvas_size(self):
        prompt = codex_image.augment_prompt_with_size("Create a phone screenshot.", "1008x1792")

        self.assertIn("1008x1792 pixel portrait canvas", prompt)
        self.assertIn("aspect ratio", prompt)

    def test_explicit_non_standard_size_is_sent_as_requested(self):
        api_size, _ = codex_image.normalize_image_size("1000x1800")

        self.assertEqual(api_size, "1000x1800")
        self.assertEqual(codex_image.requested_delivery_size("1000x1800", api_size), "1000x1800")

    def test_ratio_tier_delivery_size_is_resolved_standard_size(self):
        api_size, _ = codex_image.normalize_image_size("9:16@1k")

        self.assertEqual(codex_image.requested_delivery_size("9:16@1k", api_size), "1008x1792")

    def test_large_aspect_ratio_mismatch_is_not_stretched_automatically(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            with mock.patch.object(codex_image, "read_image_dimensions", return_value=(1024, 1024)):
                with mock.patch.object(codex_image, "resize_image_to_size") as resize:
                    with self.assertRaises(SystemExit):
                        codex_image.ensure_output_dimensions(Path(tmp.name), "1000x1800")

        resize.assert_not_called()

    def test_small_aspect_ratio_mismatch_can_resize(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            with mock.patch.object(codex_image, "read_image_dimensions", side_effect=[(1024, 1792), (1000, 1800)]):
                with mock.patch.object(codex_image, "resize_image_to_size") as resize:
                    codex_image.ensure_output_dimensions(Path(tmp.name), "1000x1800")

        resize.assert_called_once()

    def test_multipart_uses_repeated_image_fields_for_multiple_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "person.png"
            second = Path(tmpdir) / "bag.png"
            first.write_bytes(b"person")
            second.write_bytes(b"bag")

            body, boundary = codex_image.encode_multipart(
                {"prompt": "combine references"},
                [("image", first), ("image", second)],
            )

        self.assertTrue(boundary.startswith("----codex-image-"))
        self.assertEqual(body.count(b'name="image"'), 2)
        self.assertNotIn(b'name="images"', body)

    def test_generate_redirects_image_inputs_to_edit(self):
        parser = codex_image.build_parser()
        args = parser.parse_args(["generate", "--image", "ref.png", "prompt"])

        with mock.patch.object(codex_image, "log") as log:
            with mock.patch.object(codex_image, "cmd_edit", return_value=0) as cmd_edit:
                result = codex_image.cmd_generate(args)

        self.assertEqual(result, 0)
        log.assert_called_once()
        self.assertIn("redirect", log.call_args.args[0].lower())
        self.assertIn("generate", log.call_args.args[0].lower())
        self.assertIn("edit", log.call_args.args[0].lower())
        cmd_edit.assert_called_once()
        redirected_args = cmd_edit.call_args.args[0]
        self.assertEqual(redirected_args.command, "edit")
        self.assertEqual(redirected_args.image, ["ref.png"])
        self.assertEqual(redirected_args.positional, ["prompt"])
        self.assertIsNone(redirected_args.mask)
        self.assertIsNone(redirected_args.input_fidelity)
        self.assertEqual(redirected_args.image_set, [])
        self.assertFalse(redirected_args.reset_image_set)

    def test_attachment_placeholder_resolves_from_current_thread_rollout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            attachment = tmp / "attachments" / "ref.png"
            attachment.parent.mkdir(parents=True)
            attachment.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-123.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["attachments/ref.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-123"},
                clear=False,
            ):
                resolved = codex_image.resolve_image_reference("[Image #1]")

        self.assertEqual(resolved, attachment.resolve())

    def test_attachment_placeholder_accepts_spacing_and_case_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            attachment = tmp / "ref.png"
            attachment.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-789.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["ref.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-789"},
                clear=False,
            ):
                compact = codex_image.resolve_image_reference("[Image#1]")
                spaced = codex_image.resolve_image_reference("[image # 1]")

        self.assertEqual(compact, attachment.resolve())
        self.assertEqual(spaced, attachment.resolve())

    def test_dash_image_arguments_can_consume_latest_attachment_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-dash.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image", "-", "--image", "-", "use latest attachments"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-dash"},
                clear=False,
            ):
                paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(paths, [first.resolve(), second.resolve()])
        self.assertEqual(prompt, "use latest attachments")

    def test_sequential_current_placeholders_can_fallback_to_thread_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            older_first = tmp / "older-first.png"
            older_second = tmp / "older-second.png"
            current = tmp / "current.png"
            older_first.write_bytes(b"older-first")
            older_second.write_bytes(b"older-second")
            current.write_bytes(b"current")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-seq.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["older-first.png","older-second.png"]}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["current.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(
                [
                    "edit",
                    "--image",
                    "[Image #1]",
                    "--image",
                    "[Image #2]",
                    "--image",
                    "[Image #3]",
                    "carry forward older images plus the new one",
                ]
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-seq"},
                clear=False,
            ):
                paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(paths, [older_first.resolve(), older_second.resolve(), current.resolve()])
        self.assertEqual(prompt, "carry forward older images plus the new one")

    def test_last_output_placeholder_and_selector_resolve_saved_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first-out.png"
            second = tmp / "second-out.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-last-output"},
                clear=False,
            ):
                codex_image.save_last_output_set("thread-last-output", [first.resolve(), second.resolve()])
                parser = codex_image.build_parser()
                args = parser.parse_args(
                    [
                        "edit",
                        "--image-set",
                        "last-output",
                        "--image",
                        "[Last Output #2]",
                        "refine prior result",
                    ]
                )
                paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(paths, [first.resolve(), second.resolve()])
        self.assertEqual(prompt, "refine prior result")

    def test_attachment_placeholder_uses_turn_context_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first_dir = tmp / "first"
            second_dir = tmp / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "ref.png"
            second = second_dir / "ref.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-cwd.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(first_dir).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(first_dir).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["ref.png"]}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(second_dir).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["ref.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-cwd"},
                clear=False,
            ):
                latest = codex_image.resolve_image_reference("[Image #1]")
                previous = codex_image.resolve_image_reference("[Turn -1 Image #1]")

        self.assertEqual(latest, second.resolve())
        self.assertEqual(previous, first.resolve())

    def test_attachment_placeholder_does_not_fallback_to_process_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            trap = Path.cwd() / "trap.png"
            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-trap.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"turn_context","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["trap.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            trap.write_bytes(b"trap")
            try:
                with mock.patch.dict(
                    codex_image.os.environ,
                    {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-trap"},
                    clear=False,
                ):
                    with self.assertRaises(SystemExit):
                        codex_image.resolve_image_reference("[Image #1]")
            finally:
                trap.unlink(missing_ok=True)

    def test_current_turn_short_placeholder_prefers_latest_attachment_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            older = tmp / "older.png"
            current = tmp / "current.png"
            older.write_bytes(b"older")
            current.write_bytes(b"current")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-current.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["older.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","message":"plain text only","local_images":[]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["current.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-current"},
                clear=False,
            ):
                resolved = codex_image.resolve_image_reference("[Image #1]")

        self.assertEqual(resolved, current.resolve())

    def test_turn_placeholder_resolves_previous_attachment_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-turn.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","message":"no images here","local_images":[]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-turn"},
                clear=False,
            ):
                resolved = codex_image.resolve_image_reference("[Turn -1 Image #2]")

        self.assertEqual(resolved, second.resolve())

    def test_thread_placeholder_resolves_stable_attachment_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-global.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-global"},
                clear=False,
            ):
                resolved = codex_image.resolve_image_reference("[Thread Image #3]")

        self.assertEqual(resolved, third.resolve())

    def test_edit_inputs_accept_attachment_placeholder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            attachment = tmp / "ref.png"
            attachment.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-456.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["ref.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image", "[Image #1]", "replace background"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-456"},
                clear=False,
            ):
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [attachment.resolve()])
        self.assertEqual(prompt, "replace background")

    def test_edit_inputs_can_mix_current_and_historical_attachment_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-mixed.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(
                [
                    "edit",
                    "--image",
                    "[Turn -1 Image #1]",
                    "--image",
                    "[Turn -1 Image #2]",
                    "--image",
                    "[Image #1]",
                    "make the first person replace the second scene, but keep the third image realism reference",
                ]
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-mixed"},
                clear=False,
            ):
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [first.resolve(), second.resolve(), third.resolve()])
        self.assertIn("third image realism reference", prompt)

    def test_edit_inputs_explicit_image_sets_can_merge_active_and_latest_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-active.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(
                [
                    "edit",
                    "--image-set",
                    "active",
                    "--image-set",
                    "latest-turn",
                    "make the person more realistic",
                ]
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-active"},
                clear=False,
            ):
                codex_image.save_active_image_set("thread-active", [first.resolve(), second.resolve()])
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [first.resolve(), second.resolve(), third.resolve()])
        self.assertEqual(prompt, "make the person more realistic")

    def test_edit_inputs_without_explicit_images_or_selectors_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-reset.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "only use the newest upload"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-reset"},
                clear=False,
            ):
                codex_image.save_active_image_set("thread-reset", [first.resolve(), second.resolve()])
                with self.assertRaises(SystemExit):
                    codex_image.resolve_edit_inputs(args)

    def test_edit_inputs_support_image_set_selectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-selector.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(
                [
                    "edit",
                    "--image-set",
                    "turn:-1",
                    "--image-set",
                    "thread:3",
                    "compose from explicit sets",
                ]
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-selector"},
                clear=False,
            ):
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [first.resolve(), second.resolve(), third.resolve()])
        self.assertEqual(prompt, "compose from explicit sets")

    def test_active_image_selector_does_not_append_latest_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-active-only.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image-set", "active", "reuse only active set"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-active-only"},
                clear=False,
            ):
                codex_image.save_active_image_set("thread-active-only", [first.resolve(), second.resolve()])
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [first.resolve(), second.resolve()])
        self.assertEqual(prompt, "reuse only active set")

    def test_thread_image_set_ignores_unrequested_missing_attachments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            missing = tmp / "missing.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-missing.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["missing.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image-set", "thread:3", "use only the third thread image"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-missing"},
                clear=False,
            ):
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [third.resolve()])
        self.assertEqual(prompt, "use only the third thread image")

    def test_thread_placeholder_fails_when_attachment_history_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.png"
            second = tmp / "second.png"
            third = tmp / "third.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")
            third.write_bytes(b"3")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-limit.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["first.png","second.png"]}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["third.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-limit"},
                clear=False,
            ):
                with mock.patch.object(codex_image, "THREAD_ATTACHMENT_MAX_IMAGES", 2):
                    with self.assertRaises(SystemExit):
                        codex_image.resolve_image_reference("[Thread Image #3]")

    def test_cmd_edit_persists_active_image_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source.png"
            source.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-save.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["source.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image", "[Image #1]", "save active set"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-save"},
                clear=False,
            ):
                with mock.patch.object(codex_image, "resolve_runtime", return_value={"base_url": "https://example.com", "timeout": 30, "output_dir": str(tmp), "size": "1024x1024", "quality": "medium", "format": "png", "compression": None, "background": "auto", "moderation": "auto", "model": "gpt-image-2"}):
                    with mock.patch.object(codex_image, "ensure_api_key", return_value="test-key"):
                        with mock.patch.object(codex_image, "effective_model", return_value="gpt-image-2"):
                            with mock.patch.object(codex_image, "common_runtime_values", return_value=("1024x1024", "1024x1024", "medium", "png", None, "auto", "auto", None)):
                                with mock.patch.object(codex_image, "post_multipart", return_value={"data": [{"b64_json": "AAAA"}]}):
                                    with mock.patch.object(codex_image, "extract_images_from_images_payload", return_value=["AAAA"]):
                                        with mock.patch.object(codex_image, "decode_and_save_many", return_value=[tmp / "out.png"]):
                                            codex_image.cmd_edit(args)

                active_images = codex_image.load_active_image_set("thread-save")

        self.assertEqual(active_images, [source.resolve()])

    def test_cmd_edit_persists_last_output_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source.png"
            source.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-last-save.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["source.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image", "[Image #1]", "save last output"])
            output_path = tmp / "out.png"

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-last-save"},
                clear=False,
            ):
                with mock.patch.object(codex_image, "resolve_runtime", return_value={"base_url": "https://example.com", "timeout": 30, "output_dir": str(tmp), "size": "1024x1024", "quality": "medium", "format": "png", "compression": None, "background": "auto", "moderation": "auto", "model": "gpt-image-2"}):
                    with mock.patch.object(codex_image, "ensure_api_key", return_value="test-key"):
                        with mock.patch.object(codex_image, "effective_model", return_value="gpt-image-2"):
                            with mock.patch.object(codex_image, "common_runtime_values", return_value=("1024x1024", "1024x1024", "medium", "png", None, "auto", "auto", None)):
                                with mock.patch.object(codex_image, "post_multipart", return_value={"data": [{"b64_json": "AAAA"}]}):
                                    with mock.patch.object(codex_image, "extract_images_from_images_payload", return_value=["AAAA"]):
                                        def fake_decode_and_save_many(*_args, **_kwargs):
                                            output_path.write_bytes(b"png")
                                            return [output_path]

                                        with mock.patch.object(codex_image, "decode_and_save_many", side_effect=fake_decode_and_save_many):
                                            codex_image.cmd_edit(args)

                last_outputs = codex_image.load_last_output_set("thread-last-save")

        self.assertEqual(last_outputs, [output_path.resolve()])

    def test_cmd_edit_dry_run_persists_active_image_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source.png"
            source.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-dry-save.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"cwd":"'
                        + str(tmp).replace("\\", "\\\\")
                        + '"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","local_images":["source.png"]}}',
                    ]
                ),
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--dry-run", "--image", "[Image #1]", "save active set on dry run"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-dry-save"},
                clear=False,
            ):
                with mock.patch.object(
                    codex_image,
                    "resolve_runtime",
                    return_value={
                        "api_key": "test-key",
                        "base_url": "https://example.com",
                        "model": "gpt-image-2",
                        "size": "1024x1024",
                        "quality": "medium",
                        "format": "png",
                        "compression": None,
                        "background": "auto",
                        "moderation": "auto",
                        "timeout": 30,
                        "output_dir": str(tmp),
                        "config_path": str(tmp / "config.toml"),
                        "provider_id": "openai",
                        "provider_env_key": "OPENAI_API_KEY",
                    },
                ):
                    codex_image.cmd_edit(args)
                active_images = codex_image.load_active_image_set("thread-dry-save")

        self.assertEqual(active_images, [source.resolve()])

    def test_edit_inputs_can_reuse_active_set_explicitly_without_attachment_turns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "source.png"
            source.write_bytes(b"png")

            sessions = tmp / "sessions" / "2026" / "04" / "24"
            sessions.mkdir(parents=True)
            rollout = sessions / "rollout-2026-04-24T18-00-35-thread-path-only.jsonl"
            rollout.write_text(
                '{"type":"session_meta","payload":{"cwd":"'
                + str(tmp).replace("\\", "\\\\")
                + '"}}',
                encoding="utf-8",
            )

            parser = codex_image.build_parser()
            args = parser.parse_args(["edit", "--image-set", "active", "refine the same source image"])

            with mock.patch.dict(
                codex_image.os.environ,
                {"CODEX_HOME": tmpdir, "CODEX_THREAD_ID": "thread-path-only"},
                clear=False,
            ):
                codex_image.save_active_image_set("thread-path-only", [source.resolve()])
                input_paths, prompt = codex_image.resolve_edit_inputs(args)

        self.assertEqual(input_paths, [source.resolve()])
        self.assertEqual(prompt, "refine the same source image")


if __name__ == "__main__":
    unittest.main()
