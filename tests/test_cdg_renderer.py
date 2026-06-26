import tempfile
import unittest
from pathlib import Path

from cdg_renderer import FONT_CACHE, Word, build_cdg_from_words


class CdgRendererTests(unittest.TestCase):
    def test_uses_bundled_dejavu_font(self):
        self.assertIsNotNone(FONT_CACHE.font_path)
        self.assertTrue(str(FONT_CACHE.font_path).endswith("DejaVuSans-Bold.ttf"))

    def test_glyph_is_not_vertically_duplicated(self):
        info = FONT_CACHE.get_char_info("A")
        cols = info["pixels"]
        top = tuple(tuple(col[: info["height"] // 2]) for col in cols)
        bottom = tuple(tuple(col[info["height"] // 2 :]) for col in cols)
        self.assertNotEqual(top, bottom)

    def test_build_cdg_writes_packet_aligned_file(self):
        words = [Word("Hello", 0.0, 0.6), Word("world", 0.7, 1.2)]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_cdg_from_words(words, 2.0, Path(tmp) / "sample.cdg")
            data = path.read_bytes()
        self.assertGreater(len(data), 0)
        self.assertEqual(len(data) % 24, 0)


if __name__ == "__main__":
    unittest.main()
