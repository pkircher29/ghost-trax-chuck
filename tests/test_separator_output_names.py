import unittest

from separator import package_member_names


class SeparatorOutputNameTests(unittest.TestCase):
    def test_package_member_names_are_cdg_player_compatible(self):
        names = package_member_names("KV11043315 - Ella Langley - I Gotta Quit")
        self.assertEqual(names["music"], "KV11043315 - Ella Langley - I Gotta Quit.mp3")
        self.assertEqual(names["cdg"], "KV11043315 - Ella Langley - I Gotta Quit.cdg")
        self.assertEqual(names["vocals"], "KV11043315 - Ella Langley - I Gotta Quit(vocals).mp3")
        self.assertEqual(names["txt"], "KV11043315 - Ella Langley - I Gotta Quit.txt")


if __name__ == "__main__":
    unittest.main()
