import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_image.py"
SPEC = importlib.util.spec_from_file_location("codex_image", SCRIPT_PATH)
codex_image = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(codex_image)


class SizeNormalizationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
