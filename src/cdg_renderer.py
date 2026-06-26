"""CDG (CD+Graphics) renderer. - Updated

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
"""

from dataclasses import dataclass
from typing import List, Tuple
from pathlib import Path

from PIL import Image, ImageFont, ImageDraw

# CDG constants
TILE_WIDTH = 6
TILE_HEIGHT = 12
TILES_H = 50
TILES_V = 18
SCREEN_W = TILES_H * TILE_WIDTH   # 300
SCREEN_H = TILES_V * TILE_HEIGHT  # 216
PACKETS_PER_SECOND = 300
# Keep lyrics inside the CDG title-safe area. CDG frames are 300x216,
# but many players/TVs crop near the edges.
SAFE_MARGIN_X = 18

# Default CDG colors are 4-bit RGB per channel (0-15). Indices 0-15.
# Each tile supports only 2 colors (color0/color1). We keep the palette
# filled so standard players decode correctly.
PALETTE = [
    (0, 0, 0),         # 0 black  (background / color0 default)
    (15, 15, 15),      # 1 white  (text / color1 default)
    (0, 15, 0),        # 2 bright green (active line)
    (8, 8, 8),         # 3 gray   (unused)
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


def _color_to_cdg_bytes(rgb: Tuple[int, int, int]) -> Tuple[int, int]:
    """Pack 4-bit RGB into two 6-bit CDG color bytes (OpenKJ format).

    OpenKJ reconstructs the 12-bit word as:
      red   = lowbyte  bits 5..2  (8,4,2,1)
      green = lowbyte  bits 1..0 + highbyte bits 5..4
      blue  = highbyte bits 3..0
    We store the 12-bit word as (r << 8) | (g << 4) | b and then split it
    the same way: the high 6 bits go to byte0, the low 6 bits to byte1.
    """
    r = rgb[0] & 0x0F
    g = rgb[1] & 0x0F
    b = rgb[2] & 0x0F
    word = (r << 8) | (g << 4) | b
    return (word >> 6) & 0x3F, word & 0x3F


def make_packet(command: int, instruction: int, data: bytes) -> bytes:
    """Build a 24-byte CDG packet matching OpenKJ's decoder.

    Layout:
      byte 0  : command (must be 0x09)
      byte 1  : instruction (low 6 bits)
      bytes 2-3: parity (ignored here)
      bytes 4-19: 16 data bytes
      bytes 20-23: parity (ignored here)
    """
    assert len(data) == 16
    packet = bytearray(24)
    packet[0] = command & 0x3F
    packet[1] = instruction & 0x3F
    for i in range(16):
        packet[4 + i] = data[i] & 0x3F
    return bytes(packet)


def noop_packet() -> bytes:
    """A valid CDG no-op packet (command 0, instruction 0)."""
    return make_packet(0, 0, bytes(bytearray(16)))


def load_color_table_low(palette: List[Tuple[int, int, int]]) -> bytes:
    """Load colors 0-7 of the palette (CDG instruction 30)."""
    data = bytearray(16)
    for i in range(8):
        b0, b1 = _color_to_cdg_bytes(palette[i])
        data[i * 2] = b0
        data[i * 2 + 1] = b1
    return make_packet(9, 30, bytes(data))


def load_color_table_high(palette: List[Tuple[int, int, int]]) -> bytes:
    """Load colors 8-15 of the palette (CDG instruction 31)."""
    data = bytearray(16)
    for i in range(8):
        b0, b1 = _color_to_cdg_bytes(palette[i + 8])
        data[i * 2] = b0
        data[i * 2 + 1] = b1
    return make_packet(9, 31, bytes(data))


def memory_preset(color: int, repeat: int = 0) -> bytes:
    """Clear the screen to a single color (CDG instruction 1)."""
    data = bytearray(16)
    data[0] = color & 0x0F
    data[1] = repeat & 0x0F
    return make_packet(9, 1, bytes(data))


def border_preset(color: int) -> bytes:
    """Set border color (CDG instruction 2)."""
    data = bytearray(16)
    data[0] = color & 0x0F
    return make_packet(9, 2, bytes(data))


def set_tile(
    tile_col: int,
    tile_row: int,
    pixels: List[int],
    color0: int = 0,
    color1: int = 1,
) -> bytes:
    """Update a 6x12 tile (CDG instruction 6).

    pixels is 72 color indices arranged as 12 rows x 6 columns.  Each byte
    holds one row: bit 5 = col 0, bit 4 = col 1, ..., bit 0 = col 5.
    Values equal to color1 draw with color1, otherwise color0.
    """
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


def sanitize_tile_colors(tile: List[int], color0: int = 0) -> List[int]:
    """Ensure the tile contains at most 2 colors by mapping minority foreground colors to the majority foreground color."""
    foreground_colors = [c for c in tile if c != color0]
    if not foreground_colors:
        return tile
    unique_fg = set(foreground_colors)
    if len(unique_fg) <= 1:
        return tile
    counts = {}
    for c in foreground_colors:
        counts[c] = counts.get(c, 0) + 1
    majority_fg = max(counts, key=counts.get)
    return [c if c == color0 or c == majority_fg else majority_fg for c in tile]


class TrueTypeFontCache:
    def __init__(self, size: int = 18, height: int = 24):
        import sys
        # Use the bundled font first so Linux/Windows builds render identically.
        # In source runs it lives under src/assets; in PyInstaller one-file
        # builds it is extracted under sys._MEIPASS/src/assets.
        meipass = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None
        local_paths = [
            Path(__file__).parent / "assets" / "DejaVuSans-Bold.ttf",
        ]
        if meipass is not None:
            local_paths.extend([
                meipass / "src" / "assets" / "DejaVuSans-Bold.ttf",
                meipass / "assets" / "DejaVuSans-Bold.ttf",
                meipass / "DejaVuSans-Bold.ttf",
            ])
        font_path = None
        for p in local_paths:
            if p.exists():
                font_path = str(p)
                break
        if font_path is None:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            ]
            for p in font_paths:
                if Path(p).exists():
                    font_path = p
                    break
        self.font_path = font_path
        if font_path is None:
            self.font = ImageFont.load_default()
        else:
            self.font = ImageFont.truetype(font_path, size)
        self.height = height
        self.char_cache = {}
        for code in range(32, 127):
            ch = chr(code)
            self._render_char(ch)

    def _render_char(self, ch: str):
        if hasattr(self.font, "getlength"):
            w = int(self.font.getlength(ch))
        else:
            # Fallback for default font
            w, _ = self.font.getsize(ch) if hasattr(self.font, "getsize") else (6, 12)
        if w <= 0:
            w = 5
        img = Image.new("1", (w, self.height), 0)
        draw = ImageDraw.Draw(img)
        # Shift text slightly down to vertically align
        draw.text((0, 1), ch, font=self.font, fill=1)
        cols = []
        for x in range(w):
            col = []
            for y in range(self.height):
                col.append(img.getpixel((x, y)))
            cols.append(col)
        self.char_cache[ch] = {
            "width": w,
            "height": self.height,
            "pixels": cols
        }

    def get_char_info(self, ch: str) -> dict:
        if ch not in self.char_cache:
            self._render_char(ch)
        return self.char_cache.get(ch, self.char_cache.get(" "))


FONT_CACHE = TrueTypeFontCache()


def get_text_width(text: str) -> int:
    width = 0
    for ch in text:
        width += FONT_CACHE.get_char_info(ch)["width"] + 1
    return width


class CdgCanvas:
    """Logical 300x216 pixel buffer storing color indices."""

    def __init__(self):
        self.pixels = [0] * (SCREEN_W * SCREEN_H)

    def clear(self, color: int = 0):
        self.pixels = [color] * (SCREEN_W * SCREEN_H)

    def set_pixel(self, x: int, y: int, color: int):
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            self.pixels[y * SCREEN_W + x] = color

    def draw_char(self, ch: str, x: int, y: int, color: int, scale: int = 1, color_active: int | None = None, sweep_x: float | None = None):
        info = FONT_CACHE.get_char_info(ch)
        w = info["width"]
        h = info["height"]
        cols = info["pixels"]
        for col_idx in range(w):
            col_pixels = cols[col_idx]
            for row_idx in range(h):
                if col_pixels[row_idx]:
                    px = x + col_idx
                    py = y + row_idx
                    if sweep_x is not None and color_active is not None:
                        c = color_active if px < sweep_x else color
                    else:
                        c = color
                    self.set_pixel(px, py, c)

    def draw_text(self, text: str, x: int, y: int, color: int, scale: int = 1, color_active: int | None = None, sweep_x: float | None = None):
        cx = x
        for ch in text:
            self.draw_char(ch, cx, y, color, scale, color_active, sweep_x)
            cx += FONT_CACHE.get_char_info(ch)["width"] + 1
        return cx

    def get_tile(self, col: int, row: int) -> List[int]:
        """Return 72 pixel indices for one 6x12 tile, sanitized to at most 2 colors."""
        tile_pixels = []
        for ty in range(TILE_HEIGHT):
            for tx in range(TILE_WIDTH):
                x = col * TILE_WIDTH + tx
                y = row * TILE_HEIGHT + ty
                tile_pixels.append(self.pixels[y * SCREEN_W + x])
        return sanitize_tile_colors(tile_pixels)


def wrap_words_into_lines(words: List[Word], max_pixels: int, scale: int = 1) -> List[Tuple[int, List[Word]]]:
    """Wrap words into screen lines based on pixel width and natural phrasing.

    Returns a list of (first_word_index, line_words) tuples so callers can
    map the active word back to a line index even when words repeat.

    Heuristics matching commercial CDGs (e.g., OpenKJ-rendered files):
      * break after punctuation (.,!?;:)
      * break after a long silence gap between words (>> 0.35 s)
      * otherwise fill to the pixel budget
    """
    space_width = get_text_width(" ")
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
        word_width = get_text_width(word.text)

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


def _render_screen_canvas(
    words: List[Word],
    t: float,
    scale: int = 2,
    color_upcoming: int = 1,
    color_active: int = 2,
    color_past: int = 2,
    visible_lines: int = 5,
) -> CdgCanvas:
    """Render lyrics to a CdgCanvas with smooth progress coloring."""
    canvas = CdgCanvas()
    canvas.clear(0)

    if not words:
        return canvas

    char_width = 6 * scale
    space_width = 6 * scale
    line_height = TILE_HEIGHT * scale

    margin = SAFE_MARGIN_X
    max_pixels = SCREEN_W - margin * 2
    all_lines = wrap_words_into_lines(words, max_pixels, scale)

    # Find the word/page that should be displayed at time t. During gaps, keep
    # the previous lyric page instead of jumping back to the first screen.
    current_word_index = _display_word_index_at_time(words, t)

    # Find the line that contains the current word by index.
    active_line_idx = 0
    found = False
    for i, (first_idx, line) in enumerate(all_lines):
        line_len = len(line)
        if first_idx <= current_word_index < first_idx + line_len:
            active_line_idx = i
            found = True
            break
    if not found and words and current_word_index >= len(words):
        # Past the end: keep the last line active.
        active_line_idx = len(all_lines) - 1

    # Show a window centered on the active line.
    half = visible_lines // 2
    start_line = max(0, active_line_idx - half)
    if start_line + visible_lines > len(all_lines):
        start_line = max(0, len(all_lines) - visible_lines)
    display_lines = all_lines[start_line:start_line + visible_lines]

    # Center vertically and align to tile rows.
    total_height = len(display_lines) * line_height
    raw_start_y = (SCREEN_H - total_height) // 2
    start_y = max(TILE_HEIGHT, (raw_start_y // TILE_HEIGHT) * TILE_HEIGHT)
    if start_y + total_height > SCREEN_H - TILE_HEIGHT:
        start_y = ((raw_start_y + TILE_HEIGHT - 1) // TILE_HEIGHT) * TILE_HEIGHT
        if start_y < TILE_HEIGHT:
            start_y = TILE_HEIGHT

    for offset, (first_idx, line_words) in enumerate(display_lines):
        y = start_y + offset * line_height
        _draw_line(canvas, line_words, first_idx, t, y, scale, color_upcoming, color_active, margin)

    return canvas


def encode_tiles(canvas: CdgCanvas, color0: int = 0, skip_empty: bool = True) -> List[bytes]:
    """Emit tile packets for the canvas, skipping tiles that are all background."""
    packets = []
    for row in range(TILES_V):
        for col in range(TILES_H):
            tile = canvas.get_tile(col, row)
            if skip_empty and all(p == color0 for p in tile):
                continue
            color1 = _tile_foreground_color(tile, color0)
            packets.append(set_tile(col, row, tile, color0, color1))
    return packets


def encode_diff(
    old_canvas: CdgCanvas | None,
    new_canvas: CdgCanvas,
    color0: int = 0,
) -> List[bytes]:
    """Emit tile packets only for tiles that changed."""
    packets = []
    for row in range(TILES_V):
        for col in range(TILES_H):
            new_tile = new_canvas.get_tile(col, row)
            if old_canvas is None or old_canvas.get_tile(col, row) != new_tile:
                color1 = _tile_foreground_color(new_tile, color0)
                packets.append(set_tile(col, row, new_tile, color0, color1))
    return packets


def _tile_foreground_color(tile: List[int], color0: int) -> int:
    """Return the first non-background color used in the tile.

    CDG tiles support exactly two colors (color0 and color1). Our canvas may
    use indices 1 and 2 for text, so each tile's actual foreground color must
    be discovered and used as color1.
    """
    for idx in tile:
        if idx != color0:
            return idx
    return 1  # default foreground color




def _display_word_index_at_time(words: List[Word], t: float, previous_index: int = -1) -> int:
    """Return the word index that should control the visible lyric page at time t.

    During instrumental/silence gaps between words, there is no actively swept
    word. The old renderer returned -1 in those gaps, which mapped back to line
    0 and made later pages flash the first lyric screen. Instead, hold the most
    recent word/page until the next word starts.
    """
    if not words:
        return -1
    if t < words[0].start:
        return 0

    last_started = -1
    for i, word in enumerate(words):
        if word.start <= t:
            last_started = i
            if t < word.end:
                return i
        else:
            break

    if last_started >= 0:
        return last_started
    if t >= words[-1].end:
        return len(words)
    return max(0, previous_index)


def _active_line_index(words: List[Word], word_index: int, all_lines: List[Tuple[int, List[Word]]]) -> int:
    """Return the line index containing word_index, or the nearest valid line."""
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


def _draw_line(
    canvas: CdgCanvas,
    line_words: List[Word],
    first_word_index: int,
    t: float,
    y: int,
    scale: int = 2,
    color_upcoming: int = 1,
    color_active: int = 2,
    margin: int = SAFE_MARGIN_X,
):
    """Draw one lyric line onto the canvas at the given y position, with a smooth sweep at time t."""
    space_width = get_text_width(" ")
    full_width = sum(get_text_width(w.text) for w in line_words)
    full_width += max(0, len(line_words) - 1) * space_width
    x = max(margin, (SCREEN_W - full_width) // 2)
    for word_offset, word in enumerate(line_words):
        w_width = get_text_width(word.text)
        
        # Calculate sweep coordinate for this word
        if t <= word.start:
            sweep_x = x
        elif t >= word.end:
            sweep_x = x + w_width
        else:
            p = (t - word.start) / (word.end - word.start)
            sweep_x = x + p * w_width
            
        x = canvas.draw_text(word.text, x, y, color_upcoming, scale, color_active=color_active, sweep_x=sweep_x)
        x += space_width


def _emit_line_tiles(
    canvas: CdgCanvas,
    line_y: int,
    line_words: List[Word],
    first_word_index: int,
    t: float,
    scale: int = 2,
    color0: int = 0,
) -> List[bytes]:
    """Emit tile packets for a single line at time t."""
    temp = CdgCanvas()
    temp.clear(color0)
    _draw_line(temp, line_words, first_word_index, t, line_y, scale)
    packets = []
    start_row = line_y // TILE_HEIGHT
    end_row = (line_y + 24 - 1) // TILE_HEIGHT
    for row in range(start_row, min(end_row + 1, TILES_V)):
        for col in range(TILES_H):
            tile = temp.get_tile(col, row)
            old_tile = canvas.get_tile(col, row)
            if tile != old_tile:
                color1 = _tile_foreground_color(tile, color0)
                packets.append(set_tile(col, row, tile, color0, color1))
    return packets


def _apply_scroll_to_canvas(canvas: CdgCanvas, direction: str):
    """Update a logical canvas the same way a CDG scroll-copy does."""
    new_pixels = [0] * (SCREEN_W * SCREEN_H)
    if direction == "up":
        for y in range(SCREEN_H - TILE_HEIGHT):
            for x in range(SCREEN_W):
                new_pixels[y * SCREEN_W + x] = canvas.pixels[(y + TILE_HEIGHT) * SCREEN_W + x]
        for y in range(TILE_HEIGHT):
            for x in range(SCREEN_W):
                new_pixels[(SCREEN_H - TILE_HEIGHT + y) * SCREEN_W + x] = canvas.pixels[y * SCREEN_W + x]
    elif direction == "down":
        for y in range(SCREEN_H - 1, TILE_HEIGHT - 1, -1):
            for x in range(SCREEN_W):
                new_pixels[y * SCREEN_W + x] = canvas.pixels[(y - TILE_HEIGHT) * SCREEN_W + x]
        for y in range(TILE_HEIGHT):
            for x in range(SCREEN_W):
                new_pixels[y * SCREEN_W + x] = canvas.pixels[(SCREEN_H - TILE_HEIGHT + y) * SCREEN_W + x]
    canvas.pixels = new_pixels


def scroll_copy_packet(h_cmd: int, v_cmd: int, h_offset: int = 0, v_offset: int = 0, color: int = 0) -> bytes:
    """Emit a CDG scroll-copy command (instruction 24)."""
    assert h_cmd in (0, 1, 2)
    assert v_cmd in (0, 1, 2)
    data = bytearray(16)
    data[0] = color & 0x0F
    hscroll = (h_cmd << 4) | (h_offset & 0x07)
    vscroll = (v_cmd << 4) | (v_offset & 0x0F)
    data[1] = hscroll & 0x3F
    data[2] = vscroll & 0x3F
    return make_packet(9, 24, bytes(data))

def build_cdg_from_words(
    words: List[Word],
    duration_seconds: float,
    output_path: Path,
    palette: List[int] | None = None,
    visible_lines: int = 4,
    scale: int = 2,
) -> Path:
    """Build a complete .cdg file synchronized to music, using page-by-page rendering.

    Uses smooth pixel-level lyric sweep (wipe). When the lyrics reach the end of the page,
    the screen is cleared, and the next page of lyrics is drawn.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    palette = palette or list(range(16))
    total_packets = max(int(duration_seconds * PACKETS_PER_SECOND), 1)

    margin = SAFE_MARGIN_X
    max_pixels = SCREEN_W - margin * 2
    all_lines = wrap_words_into_lines(words, max_pixels, scale)
    line_height = TILE_HEIGHT * scale

    # Fixed Y positions for visible lines, centered vertically.
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
        # Start viewport at the beginning of the first page (line 0)
        viewport_first_line = 0

        # Logical canvas matching the CDG framebuffer
        canvas = CdgCanvas()
        canvas.clear(0)

        # Draw initial visible lines (all upcoming color at t=0.0)
        for offset, (first_idx, line_words) in enumerate(all_lines[viewport_first_line:viewport_first_line + visible_lines]):
            if offset < len(line_y_positions):
                y = line_y_positions[offset]
                packets = _emit_line_tiles(canvas, y, line_words, first_idx, 0.0, scale)
                f.write(b"".join(packets))
                packets_emitted += len(packets)
                _draw_line(canvas, line_words, first_idx, 0.0, y, scale)

        packets_per_render = 10

        for packet_idx in range(0, total_packets, packets_per_render):
            t = packet_idx / PACKETS_PER_SECOND

            while packets_emitted < packet_idx and packets_emitted < total_packets:
                f.write(noop_packet())
                packets_emitted += 1

            current_word_index = _display_word_index_at_time(words, t, current_word_index)
            active_line = _active_line_index(words, current_word_index, all_lines)

            # Page-by-page pagination logic
            current_page = active_line // visible_lines
            expected_first_line = current_page * visible_lines

            if expected_first_line != viewport_first_line:
                # Page changed! Clear screen and draw new page.
                viewport_first_line = expected_first_line

                # 1. Clear physical screen (memory preset)
                f.write(memory_preset(0, repeat=0))
                packets_emitted += 1

                # 2. Clear logical canvas
                canvas.clear(0)

                # 3. Draw and emit the new page lines (all in upcoming color at time t)
                page_lines = all_lines[viewport_first_line : viewport_first_line + visible_lines]
                for offset, (first_idx, line_words) in enumerate(page_lines):
                    if offset < len(line_y_positions):
                        y = line_y_positions[offset]
                        packets = _emit_line_tiles(canvas, y, line_words, first_idx, t, scale)
                        f.write(b"".join(packets))
                        packets_emitted += len(packets)
                        _draw_line(canvas, line_words, first_idx, t, y, scale)

            # Update colors on the active line (and any previous visible lines, but they are already blue)
            new_canvas = CdgCanvas()
            new_canvas.clear(0)
            for offset, (first_idx, line_words) in enumerate(all_lines[viewport_first_line:viewport_first_line + visible_lines]):
                if offset < len(line_y_positions):
                    y = line_y_positions[offset]
                    _draw_line(new_canvas, line_words, first_idx, t, y, scale)
            diff = encode_diff(canvas, new_canvas)
            f.write(b"".join(diff))
            packets_emitted += len(diff)
            canvas = new_canvas

        while packets_emitted < total_packets:
            f.write(noop_packet())
            packets_emitted += 1

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


def write_lyrics_txt(words: List[Word], output_path: Path) -> Path:
    """Write a human-readable .txt file with the lyrics."""
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
