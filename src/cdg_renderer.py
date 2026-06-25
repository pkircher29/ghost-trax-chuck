"""CDG (CD+Graphics) renderer.

Generates a raw CDG subcode packet stream for word-by-word karaoke lyrics.
CDG packets are 24 bytes each and play at exactly 300 packets per second.

This implementation follows the layout used by OpenKJ / CD+G redbook:
  * Packet command byte is always 0x09
  * Instruction is in byte 1
  * Tile block instruction = 6 (normal), 38 (XOR)
  * Color-table load instructions = 30 (low) and 31 (high)
  * Memory preset = 1, border preset = 2
  * Tiles are 6 pixels wide by 12 pixels tall
  * Screen is 50 columns x 18 rows = 300 x 216

Behavior: screen-by-screen karaoke. A page of lyrics is shown, then the
screen blanks, then the next page is drawn. No continuous scrolling.
"""

from dataclasses import dataclass
from typing import List, Tuple
from pathlib import Path

from font_5x7 import get_char_bits

# CDG constants
TILE_WIDTH = 6
TILE_HEIGHT = 12
TILES_H = 50
TILES_V = 18
SCREEN_W = TILES_H * TILE_WIDTH   # 300
SCREEN_H = TILES_V * TILE_HEIGHT  # 216
PACKETS_PER_SECOND = 300

# CDG palette: 4-bit RGB per channel (0-15). Only indices 0-2 are used.
PALETTE = [
    (0, 0, 0),         # 0 black  (background / color0)
    (15, 15, 15),      # 1 white  (upcoming/past text)
    (0, 15, 0),        # 2 bright green (active word/line)
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
]


@dataclass
class Word:
    text: str
    start: float
    end: float


# More robust: read the dict via the module import directly.
import sys
from font_5x7 import FONT_5X7 as _FONT_5X7

# Font orientation fix: the font_5x7 bytes store columns right-to-left with
# bit 0 at the top. Convert to a normal row-major grid (row 0 top, col 0 left).
FONT_5X7_ROWS: dict[str, List[List[int]]] = {}
for _ch, _cols in _FONT_5X7.items():
    _rows = []
    for _row in range(7):
        _byte_mask = 1 << _row
        _row_bits = []
        for _col in reversed(_cols):
            _row_bits.append(1 if _col & _byte_mask else 0)
        _rows.append(_row_bits)
    FONT_5X7_ROWS[_ch] = _rows


def _color_to_cdg_bytes(rgb: Tuple[int, int, int]) -> Tuple[int, int]:
    r = rgb[0] & 0x0F
    g = rgb[1] & 0x0F
    b = rgb[2] & 0x0F
    word = (r << 8) | (g << 4) | b
    return (word >> 6) & 0x3F, word & 0x3F


def make_packet(command: int, instruction: int, data: bytes) -> bytes:
    assert len(data) == 16
    packet = bytearray(24)
    packet[0] = command & 0x3F
    packet[1] = instruction & 0x3F
    for i in range(16):
        packet[4 + i] = data[i] & 0x3F
    return bytes(packet)


def noop_packet() -> bytes:
    return make_packet(0, 0, bytes(bytearray(16)))


def load_color_table_low(palette: List[Tuple[int, int, int]]) -> bytes:
    data = bytearray(16)
    for i in range(8):
        b0, b1 = _color_to_cdg_bytes(palette[i])
        data[i * 2] = b0
        data[i * 2 + 1] = b1
    return make_packet(9, 30, bytes(data))


def load_color_table_high(palette: List[Tuple[int, int, int]]) -> bytes:
    data = bytearray(16)
    for i in range(8):
        b0, b1 = _color_to_cdg_bytes(palette[i + 8])
        data[i * 2] = b0
        data[i * 2 + 1] = b1
    return make_packet(9, 31, bytes(data))


def memory_preset(color: int, repeat: int = 0) -> bytes:
    data = bytearray(16)
    data[0] = color & 0x0F
    data[1] = repeat & 0x0F
    return make_packet(9, 1, bytes(data))


def border_preset(color: int) -> bytes:
    data = bytearray(16)
    data[0] = color & 0x0F
    return make_packet(9, 2, bytes(data))


def set_tile(tile_col: int, tile_row: int, pixels: List[int], color0: int = 0, color1: int = 1) -> bytes:
    assert len(pixels) == TILE_WIDTH * TILE_HEIGHT
    data = bytearray(16)
    data[0] = color0 & 0x0F
    data[1] = color1 & 0x0F
    data[2] = tile_row & 0x1F
    data[3] = tile_col & 0x3F
    for row in range(TILE_HEIGHT):
        byte = 0
        for col in range(TILE_WIDTH):
            idx = pixels[row * TILE_WIDTH + col]
            if idx == color1:
                byte |= 1 << (TILE_WIDTH - 1 - col)
        data[4 + row] = byte & 0x3F
    return make_packet(9, 6, bytes(data))


def _sanitize_tile_colors(tile: List[int], color0: int = 0) -> List[int]:
    foreground = [c for c in tile if c != color0]
    if not foreground:
        return tile
    if len(set(foreground)) <= 1:
        return tile
    counts: dict[int, int] = {}
    for c in foreground:
        counts[c] = counts.get(c, 0) + 1
    majority = max(counts.items(), key=lambda kv: kv[1])[0]
    return [c if c == color0 or c == majority else majority for c in tile]


class BitmapFontCache:
    def __init__(self):
        self._cache: dict[str, dict] = {}

    def get_char_info(self, ch: str) -> dict:
        if ch not in self._cache:
            rows = FONT_5X7_ROWS.get(ch, FONT_5X7_ROWS.get(" ", [[0] * 5] * 7))
            self._cache[ch] = {"width": len(rows[0]), "height": len(rows), "rows": rows}
        return self._cache[ch]


FONT_CACHE = BitmapFontCache()


def get_text_width(text: str, scale: int = 1) -> int:
    width = 0
    for i, ch in enumerate(text):
        width += FONT_CACHE.get_char_info(ch)["width"] * scale
        if i < len(text) - 1:
            width += scale
    return width


class CdgCanvas:
    def __init__(self):
        self.pixels = [0] * (SCREEN_W * SCREEN_H)

    def clear(self, color: int = 0):
        self.pixels = [color] * (SCREEN_W * SCREEN_H)

    def set_pixel(self, x: int, y: int, color: int):
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            self.pixels[y * SCREEN_W + x] = color

    def draw_char(self, ch: str, x: int, y: int, color: int, scale: int = 1,
                  color_active: int | None = None, sweep_x: float | None = None):
        info = FONT_CACHE.get_char_info(ch)
        rows = info["rows"]
        for row_idx, row_bits in enumerate(rows):
            for col_idx, bit in enumerate(row_bits):
                if bit:
                    px = x + col_idx * scale
                    py = y + row_idx * scale
                    for dy in range(scale):
                        for dx in range(scale):
                            if sweep_x is not None and color_active is not None:
                                c = color_active if (px + dx) < sweep_x else color
                            else:
                                c = color
                            self.set_pixel(px + dx, py + dy, c)

    def draw_text(self, text: str, x: int, y: int, color: int, scale: int = 1,
                  color_active: int | None = None, sweep_x: float | None = None) -> int:
        cx = x
        for ch in text:
            self.draw_char(ch, cx, y, color, scale, color_active, sweep_x)
            cx += FONT_CACHE.get_char_info(ch)["width"] * scale + scale
        return cx

    def get_tile(self, col: int, row: int) -> List[int]:
        tile = []
        for ty in range(TILE_HEIGHT):
            for tx in range(TILE_WIDTH):
                x = col * TILE_WIDTH + tx
                y = row * TILE_HEIGHT + ty
                tile.append(self.pixels[y * SCREEN_W + x])
        return _sanitize_tile_colors(tile)


def wrap_words_into_lines(words: List[Word], max_pixels: int, scale: int = 1) -> List[Tuple[int, List[Word]]]:
    space_width = scale
    lines: List[Tuple[int, List[Word]]] = []
    current: List[Word] = []
    current_first = 0
    current_width = 0

    def is_phrase_break(after_word: Word, before_word: Word) -> bool:
        if after_word.text.rstrip("\"'")[-1:] in ".!?;:":
            return True
        gap = before_word.start - after_word.end
        return gap > 0.35

    for idx, word in enumerate(words):
        word_width = get_text_width(word.text, scale)
        fits = not current or current_width + space_width + word_width <= max_pixels
        force_break = False
        if current:
            prev = current[-1]
            if is_phrase_break(prev, word):
                force_break = True
            elif not fits:
                force_break = True

        if current and force_break:
            lines.append((current_first, current))
            current = [word]
            current_first = idx
            current_width = word_width
        else:
            if current:
                current_width += space_width + word_width
            else:
                current_first = idx
                current_width = word_width
            current.append(word)

    if current:
        lines.append((current_first, current))

    return lines


def _active_line_index(words: List[Word], word_index: int, all_lines: List[Tuple[int, List[Word]]]) -> int:
    if not words:
        return 0
    if word_index < 0:
        return 0
    if word_index >= len(words):
        return len(all_lines) - 1
    for i, (first_idx, line) in enumerate(all_lines):
        if first_idx <= word_index < first_idx + len(line):
            return i
    return len(all_lines) - 1


def _find_current_word_index(words: List[Word], t: float, search_start: int = 0) -> int:
    if not words:
        return -1
    for i in range(search_start, len(words)):
        w = words[i]
        if w.start <= t < w.end:
            return i
    if t >= words[-1].end:
        return len(words)
    for i in range(search_start):
        w = words[i]
        if w.start <= t < w.end:
            return i
    return -1


def _draw_line(canvas: CdgCanvas, line_words: List[Word], first_word_index: int, t: float,
               y: int, scale: int, color_upcoming: int = 1, color_active: int = 2):
    space_width = scale
    full_width = sum(get_text_width(w.text, scale) for w in line_words)
    full_width += max(0, len(line_words) - 1) * space_width
    x = max(12, (SCREEN_W - full_width) // 2)
    for word_offset, word in enumerate(line_words):
        w_width = get_text_width(word.text, scale)
        if t <= word.start:
            sweep_x = x
        elif t >= word.end:
            sweep_x = x + w_width
        else:
            p = (t - word.start) / (word.end - word.start)
            sweep_x = x + p * w_width
        x = canvas.draw_text(word.text, x, y, color_upcoming, scale,
                             color_active=color_active, sweep_x=sweep_x)
        x += space_width


def _emit_tiles(canvas: CdgCanvas, color0: int = 0, skip_empty: bool = True) -> List[bytes]:
    packets = []
    for row in range(TILES_V):
        for col in range(TILES_H):
            tile = canvas.get_tile(col, row)
            if skip_empty and all(p == color0 for p in tile):
                continue
            color1 = 1
            for p in tile:
                if p != color0:
                    color1 = p
                    break
            packets.append(set_tile(col, row, tile, color0, color1))
    return packets


def _page_containing_line(all_lines: List[Tuple[int, List[Word]]], line_idx: int, visible_lines: int) -> int:
    return line_idx // visible_lines


def build_cdg_from_words(
    words: List[Word],
    duration_seconds: float,
    output_path: Path,
    palette: List[int] | None = None,
    visible_lines: int = 3,
    scale: int = 4,
    blank_seconds: float = 0.5,
) -> Path:
    """Build a screen-by-screen CDG: show page -> blank -> next page -> blank..."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_packets = max(int(duration_seconds * PACKETS_PER_SECOND), 1)
    blank_packets = max(int(blank_seconds * PACKETS_PER_SECOND), 30)

    margin = 12
    max_pixels = SCREEN_W - margin * 2
    all_lines = wrap_words_into_lines(words, max_pixels, scale)
    line_height = TILE_HEIGHT * scale

    total_vis_height = visible_lines * line_height
    raw_start_y = (SCREEN_H - total_vis_height) // 2
    start_y = max(TILE_HEIGHT, (raw_start_y // TILE_HEIGHT) * TILE_HEIGHT)
    if start_y + total_vis_height > SCREEN_H - TILE_HEIGHT:
        start_y = ((raw_start_y + TILE_HEIGHT - 1) // TILE_HEIGHT) * TILE_HEIGHT
        if start_y < TILE_HEIGHT:
            start_y = TILE_HEIGHT
    line_y_positions = [start_y + i * line_height for i in range(visible_lines)]

    with open(output_path, "wb") as f:
        f.write(load_color_table_low(PALETTE))
        f.write(load_color_table_high(PALETTE))
        f.write(memory_preset(0, repeat=0))
        f.write(border_preset(0))

        packets_emitted = 4
        current_word_index = -1
        viewport_first_line = 0
        blank_until = -1  # packet index until which screen stays blank
        canvas = CdgCanvas()
        canvas.clear(0)
        drawn_page_start = -1  # first line of the page currently on screen

        packets_per_render = 5

        for packet_idx in range(0, total_packets, packets_per_render):
            t = packet_idx / PACKETS_PER_SECOND

            while packets_emitted < packet_idx and packets_emitted < total_packets:
                f.write(noop_packet())
                packets_emitted += 1

            new_word_index = _find_current_word_index(words, t, max(0, current_word_index))
            current_word_index = new_word_index
            active_line = _active_line_index(words, current_word_index, all_lines)
            target_page_start = _page_containing_line(all_lines, active_line, visible_lines) * visible_lines

            # Transition to a new page: blank, then draw the new page after the blank.
            # Skip blank on the very first page so lyrics appear immediately.
            if target_page_start != drawn_page_start:
                if drawn_page_start != -1 and packet_idx > blank_until:
                    drawn_page_start = -1
                    blank_until = packet_idx + blank_packets
                    f.write(memory_preset(0, repeat=0))
                    packets_emitted += 1
                    canvas.clear(0)
                else:
                    # First page or still in blank window: just mark page undrawn.
                    drawn_page_start = -1

            if packet_idx < blank_until:
                # Screen is intentionally blank between pages.
                continue

            if target_page_start != drawn_page_start:
                # Blank interval is over; draw the new page.
                viewport_first_line = target_page_start
                drawn_page_start = target_page_start
                canvas.clear(0)
                page_lines = all_lines[viewport_first_line:viewport_first_line + visible_lines]
                new_canvas = CdgCanvas()
                new_canvas.clear(0)
                for offset, (first_idx, line_words) in enumerate(page_lines):
                    if offset >= len(line_y_positions):
                        break
                    y = line_y_positions[offset]
                    _draw_line(new_canvas, line_words, first_idx, t, y, scale)
                packets = _emit_tiles(new_canvas)
                f.write(b"".join(packets))
                packets_emitted += len(packets)
                canvas = new_canvas

            # Update word sweeps on the current page.
            page_lines = all_lines[viewport_first_line:viewport_first_line + visible_lines]
            new_canvas = CdgCanvas()
            new_canvas.clear(0)
            for offset, (first_idx, line_words) in enumerate(page_lines):
                if offset >= len(line_y_positions):
                    break
                y = line_y_positions[offset]
                _draw_line(new_canvas, line_words, first_idx, t, y, scale)

            # Emit only changed tiles for smooth word sweeps.
            diff = []
            for row in range(TILES_V):
                for col in range(TILES_H):
                    new_tile = new_canvas.get_tile(col, row)
                    old_tile = canvas.get_tile(col, row)
                    if new_tile != old_tile:
                        color1 = 1
                        for p in new_tile:
                            if p != 0:
                                color1 = p
                                break
                        diff.append(set_tile(col, row, new_tile, 0, color1))
            f.write(b"".join(diff))
            packets_emitted += len(diff)
            canvas = new_canvas

        while packets_emitted < total_packets:
            f.write(noop_packet())
            packets_emitted += 1

    return output_path


def parse_word_segments(segments: List[dict]) -> List[Word]:
    words = []
    for seg in segments:
        seg_words = seg.get("words", [])
        if seg_words:
            for w in seg_words:
                words.append(Word(
                    text=w.get("word", "").strip(),
                    start=w.get("start", 0.0),
                    end=w.get("end", 0.0),
                ))
        else:
            words.append(Word(
                text=seg.get("text", "").strip(),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
            ))
    return words


def clean_words_for_display(words: List[Word]) -> List[Word]:
    result = []
    for w in words:
        text = w.text.strip()
        if not text:
            continue
        text = text.lstrip(" -")
        if text:
            result.append(Word(text=text, start=w.start, end=w.end))
    return result


def write_lyrics_txt(words: List[Word], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if words:
        text = " ".join(w.text for w in words)
        output_path.write_text(text + "\n", encoding="utf-8")
    else:
        output_path.write_text("(no lyrics detected)\n", encoding="utf-8")
    return output_path


if __name__ == "__main__":
    test_words = [
        Word("Hello", 1.0, 2.0),
        Word("world", 2.1, 3.0),
        Word("this", 3.1, 3.8),
        Word("is", 3.9, 4.2),
        Word("karaoke", 4.3, 5.5),
    ]
    path = build_cdg_from_words(test_words, 7.0, Path("test.cdg"))
    print(f"Wrote {path} ({path.stat().st_size} bytes)")
