"""CDG (CD+Graphics) renderer.

Generates a raw CDG subcode packet stream for word-by-word karaoke lyrics.
CDG packets are 24 bytes each. The format is documented publicly; this
implementation uses the tile-update commands only (no scroll/border).

Screen: 300x216 visible pixels, organized as 25 columns x 18 rows of 12x6
pixel tiles. We use a 2x scaled bitmap font: each logical pixel is 2x2
screen pixels.
"""

from dataclasses import dataclass
from typing import List, Tuple
from pathlib import Path

from font_5x7 import get_char_bits

# CDG constants
TILE_WIDTH = 12
TILE_HEIGHT = 6
TILES_H = 25
TILES_V = 18
SCREEN_W = TILES_H * TILE_WIDTH   # 300
SCREEN_H = TILES_V * TILE_HEIGHT  # 216
PACKETS_PER_SECOND = 300

# Default CDG colors are 4-bit RGB (0-15 per channel). Indices 0-15.
PALETTE = [
    (0, 0, 0),        # 0 black
    (15, 15, 15),     # 1 white
    (0, 15, 0),       # 2 green (active word)
    (0, 0, 15),       # 3 blue
    (15, 0, 0),       # 4 red
    (15, 15, 0),      # 5 yellow
    (15, 0, 15),      # 6 magenta
    (0, 15, 15),      # 7 cyan
    (8, 8, 8),        # 8 gray
    (12, 12, 12),     # 9 light gray
    (8, 15, 8),       # 10 light green
    (8, 8, 15),       # 11 light blue
    (15, 8, 8),       # 12 light red
    (15, 15, 8),      # 13 light yellow
    (15, 8, 15),      # 14 light magenta
    (8, 15, 15),      # 15 light cyan
]


@dataclass
class Word:
    text: str
    start: float
    end: float


def rgb_to_cdg_byte(rgb: Tuple[int, int, int]) -> int:
    """Pack 4-bit RGB into a single CDG color byte."""
    r = (rgb[0] & 0x0F)
    g = (rgb[1] & 0x0F) << 4
    b = (rgb[2] & 0x0F) << 8
    return (r | g | b) & 0xFF


def make_packet(command: int, data: bytes) -> bytes:
    """Build a 24-byte CDG packet."""
    assert len(data) == 16
    packet = bytearray(24)
    packet[0] = command & 0x3F
    packet[1:] = data
    return bytes(packet)


def load_color_table_low(palette_indices: List[int]) -> bytes:
    """Load colors 0-7 of the palette."""
    data = bytearray(16)
    for i in range(8):
        idx = palette_indices[i] if i < len(palette_indices) else 0
        data[i] = rgb_to_cdg_byte(PALETTE[idx])
    return make_packet(0x1B, bytes(data))


def load_color_table_high(palette_indices: List[int]) -> bytes:
    """Load colors 8-15 of the palette."""
    data = bytearray(16)
    for i in range(8):
        idx = palette_indices[i + 8] if (i + 8) < len(palette_indices) else 0
        data[i] = rgb_to_cdg_byte(PALETTE[idx])
    return make_packet(0x1C, bytes(data))


def set_tile(tile_col: int, tile_row: int, pixels: List[int]) -> bytes:
    """Update a 12x6 tile. pixels is 12*6=72 color indices, row-major."""
    assert len(pixels) == TILE_WIDTH * TILE_HEIGHT
    data = bytearray(16)
    data[0] = tile_row & 0x1F
    data[1] = tile_col & 0x3F
    # Pack 72 pixels into 12 bytes (6 pixels per byte, 2 bits each)
    for i in range(12):
        byte = 0
        for j in range(6):
            byte |= (pixels[i * 6 + j] & 0x03) << (j * 2)
        data[2 + i] = byte & 0xFF
    return make_packet(0x18, bytes(data))


class CdgCanvas:
    """Logical 300x216 pixel buffer storing color indices."""

    def __init__(self):
        self.pixels = [0] * (SCREEN_W * SCREEN_H)

    def clear(self, color: int = 0):
        self.pixels = [color] * (SCREEN_W * SCREEN_H)

    def set_pixel(self, x: int, y: int, color: int):
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            self.pixels[y * SCREEN_W + x] = color

    def draw_char(self, ch: str, x: int, y: int, color: int, scale: int = 2):
        bits = get_char_bits(ch)
        for col in range(5):
            col_byte = bits[col]
            for row in range(7):
                if (col_byte >> row) & 1:
                    for dy in range(scale):
                        for dx in range(scale):
                            self.set_pixel(x + col * scale + dx, y + row * scale + dy, color)

    def draw_text(self, text: str, x: int, y: int, color: int, scale: int = 2):
        cx = x
        for ch in text:
            self.draw_char(ch, cx, y, color, scale)
            cx += (5 + 1) * scale  # 5 pixel char + 1 pixel spacing
        return cx

    def encode_tiles(self) -> List[bytes]:
        """Convert canvas to CDG tile-update packets."""
        packets = []
        for row in range(TILES_V):
            for col in range(TILES_H):
                tile_pixels = []
                for ty in range(TILE_HEIGHT):
                    for tx in range(TILE_WIDTH):
                        x = col * TILE_WIDTH + tx
                        y = row * TILE_HEIGHT + ty
                        tile_pixels.append(self.pixels[y * SCREEN_W + x])
                packets.append(set_tile(col, row, tile_pixels))
        return packets


def wrap_words_into_lines(words: List[Word], max_pixels: int, scale: int = 2) -> List[List[Word]]:
    """Wrap words into screen lines based on pixel width."""
    char_width = 6 * scale
    lines: List[List[Word]] = []
    current: List[Word] = []
    current_width = 0

    for word in words:
        word_width = len(word.text) * char_width
        if current and current_width + word_width > max_pixels:
            lines.append(current)
            current = [word]
            current_width = word_width
        else:
            current.append(word)
            current_width += word_width

    if current:
        lines.append(current)

    return lines


def render_word_screen(
    words: List[Word],
    current_word_index: int,
    color_upcoming: int = 1,
    color_active: int = 2,
    color_past: int = 8,
    scale: int = 2,
) -> List[bytes]:
    """Render one frame of lyrics with current word highlighted."""
    canvas = CdgCanvas()
    canvas.clear(0)

    max_pixels = SCREEN_W - 40  # leave margins
    lines = wrap_words_into_lines(words, max_pixels, scale)

    # Center vertically
    line_height = (7 + 3) * scale
    total_height = len(lines) * line_height
    start_y = max(10, (SCREEN_H - total_height) // 2)

    for line_words in lines:
        # Compute full line pixel width
        full_width = sum((len(w.text) + 1) * 6 * scale for w in line_words) - 6 * scale
        x = max(20, (SCREEN_W - full_width) // 2)
        y = start_y

        for idx, word in enumerate(words):
            if word not in line_words:
                continue
            if idx < current_word_index:
                color = color_past
            elif idx == current_word_index:
                color = color_active
            else:
                color = color_upcoming
            x = canvas.draw_text(word.text, x, y, color, scale)
            x += 6 * scale  # word spacing

        start_y += line_height

    return canvas.encode_tiles()


def build_cdg_from_words(
    words: List[Word],
    duration_seconds: float,
    output_path: Path,
    palette: List[int] | None = None,
) -> Path:
    """Build a complete .cdg file synchronized to music."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    palette = palette or list(range(16))

    total_packets = int(duration_seconds * PACKETS_PER_SECOND)

    with open(output_path, "wb") as f:
        # Initialize palette
        f.write(load_color_table_low(palette))
        f.write(load_color_table_high(palette))

        # Clear screen
        clear_canvas = CdgCanvas()
        clear_canvas.clear(0)
        f.write(b"".join(clear_canvas.encode_tiles()))

        # Determine frame changes
        current_word_index = -1
        packets_per_render = 4  # 4 CDG packets = 1/75 sec

        for packet_idx in range(0, total_packets, packets_per_render):
            t = packet_idx / PACKETS_PER_SECOND

            # Find active word at time t
            new_index = -1
            for i, word in enumerate(words):
                if word.start <= t < word.end:
                    new_index = i
                    break

            if new_index == -1:
                # Before first word or after last word
                if words and t >= words[-1].end:
                    new_index = len(words)
                else:
                    new_index = 0

            if new_index != current_word_index:
                current_word_index = new_index
                packets = render_word_screen(words, current_word_index)
                f.write(b"".join(packets))

        # Final frame: all words past
        final_packets = render_word_screen(words, len(words))
        f.write(b"".join(final_packets))

    return output_path


def parse_word_segments(segments: List[dict]) -> List[Word]:
    """Convert Whisper-style segments with word-level info into Word list."""
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
    """Drop empty words and trim punctuation spacing."""
    result = []
    for w in words:
        text = w.text.strip()
        if not text:
            continue
        text = text.lstrip(" -")
        if text:
            result.append(Word(text=text, start=w.start, end=w.end))
    return result


if __name__ == "__main__":
    # Quick test
    test_words = [
        Word("Hello", 1.0, 2.0),
        Word("world", 2.1, 3.0),
        Word("this", 3.1, 3.8),
        Word("is", 3.9, 4.2),
        Word("karaoke", 4.3, 5.5),
    ]
    path = build_cdg_from_words(test_words, 7.0, Path("/tmp/test.cdg"))
    print(f"Wrote {path}")
