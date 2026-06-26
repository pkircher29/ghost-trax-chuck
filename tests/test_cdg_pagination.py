import unittest

from cdg_renderer import Word, _active_line_index, _display_word_index_at_time, wrap_words_into_lines


class CDGPaginationTests(unittest.TestCase):
    def test_silence_gap_after_later_page_does_not_jump_back_to_first_page(self):
        # One short word per line. visible_lines=4 means word 4 is on page 2.
        words = [
            Word("one", 0.0, 0.2),
            Word("two", 0.4, 0.6),
            Word("three", 0.8, 1.0),
            Word("four", 1.2, 1.4),
            Word("five", 2.0, 2.2),
        ]
        all_lines = wrap_words_into_lines(words, max_pixels=1, scale=2)

        active_word = _display_word_index_at_time(words, 2.05)
        self.assertEqual(active_word, 4)
        self.assertEqual(_active_line_index(words, active_word, all_lines), 4)

        # During the silence after "five", hold word/page 4 instead of returning -1 / line 0.
        gap_word = _display_word_index_at_time(words, 2.8, previous_index=active_word)
        self.assertEqual(gap_word, 4)
        self.assertEqual(_active_line_index(words, gap_word, all_lines), 4)


if __name__ == "__main__":
    unittest.main()
