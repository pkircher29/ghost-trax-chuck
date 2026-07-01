# Optimized CDG Renderer with dirty tile tracking
# Changes:
# 1. CdgCanvas tracks dirty tiles instead of comparing all tiles
# 2. Skip rendering during long gaps (render only on word changes)
# 3. Batch processing support

from dataclasses import dataclass
from typing import List, Tuple, Set, Optional
from pathlib import Path

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from PIL import Image, ImageFont, ImageDraw

# CDG constants (unchanged)
TILE_WIDTH = 6
TILE_HEIGHT = 12
TILES_H = 50
TILES_V = 18
SCREEN_W = TILES_H * TILE_WIDTH   # 300
SCREEN_H = TILES_V * TILE_HEIGHT  # 216
PACKETS_PER_SECOND = 300
SAFE_MARGIN_X = 18

PALETTE = [
    (0, 0, 0),         # 0 black  (background / color0 default)
    (15, 15, 15),      # 1 white  (text / color1 default)
    (0, 15, 0),        # 2 bright green (active line)
    (8, 8, 8),         # 3 gray   (unused)
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

@dataclass
class Word:
    text: str
    start: float
    end: float

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

_NOOP = bytes(24)

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

def sanitize_tile_colors(tile: List[int], color0: int = 0) -> List[int]:
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
    def __init__(self, size: int = 9, height: int = 24):
        import sys
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
            try:
                w, _ = self.font.getsize(ch)
            except AttributeError:
                w = 6
        if w <= 0:
            w = 5
        img = Image.new("1", (w, self.height), 0)
        draw = ImageDraw.Draw(img)
        draw.text((0, 1), ch, font=self.font, fill=1)
        cols = []
        for x in range(w):
            col = []
            for y in range(self.height):
                col.append(img.getpixel((x, y)))
            cols.append(col)
        self.char_cache[ch] = {"width": w, "height": self.height, "pixels": cols}

    def get_char_info(self, ch: str) -> dict:
        if ch not in self.char_cache:
            self._render_char(ch)
        return self.char_cache.get(ch, self.char_cache.get(" ", {}))

FONT_CACHE = TrueTypeFontCache(size=9, height=TILE_HEIGHT)

def get_text_width(text: str, scale: int = 1) -> int:
    width = 0
    for ch in text:
        info = FONT_CACHE.get_char_info(ch)
        width += info["width"] + 1
    return width * scale

class CdgCanvas:
    """Logical 300x216 pixel buffer with dirty tile tracking."""
    
    def __init__(self):
        if NUMPY_AVAILABLE:
            self.pixels = np.zeros(SCREEN_W * SCREEN_H, dtype=np.uint8)
            self._use_numpy = True
        else:
            self.pixels = [0] * (SCREEN_W * SCREEN_H)
            self._use_numpy = False
        self.dirty_tiles: Set[Tuple[int, int]] = set()
        self.prev_tiles: dict = {}
    
    def clear(self, color: int = 0):
        if self._use_numpy:
            self.pixels[:] = color
        else:
            for i in range(len(self.pixels)):
                self.pixels[i] = color
        # All tiles dirty after clear
        self.dirty_tiles = {(c, r) for c in range(TILES_H) for r in range(TILES_V)}
    
    def set_pixel(self, x: int, y: int, color: int):
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            if self._use_numpy:
                self.pixels[y * SCREEN_W + x] = color
            else:
                self.pixels[y * SCREEN_W + x] = color
            tile_col = x // TILE_WIDTH
            tile_row = y // TILE_HEIGHT
            self.dirty_tiles.add((tile_col, tile_row))
    
    def draw_char(self, ch: str, x: int, y: int, color: int, scale: int = 1, color_active: int | None = None, sweep_x: float | None = None):
        info = FONT_CACHE.get_char_info(ch)
        w = info["width"]
        h = info["height"]
        cols = info["pixels"]
        for col_idx in range(w):
            col_pixels = cols[col_idx]
            for row_idx in range(h):
                if col_pixels[row_idx]:
                    for sx in range(scale):
                        for sy in range(scale):
                            px = x + col_idx * scale + sx
                            py = y + row_idx * scale + sy
                            if sweep_x is not None and color_active is not None:
                                c = color_active if px < sweep_x else color
                            else:
                                c = color
                            self.set_pixel(px, py, c)
    
    def draw_text(self, text: str, x: int, y: int, color: int, scale: int = 1, color_active: int | None = None, sweep_x: float | None = None):
        cx = x
        for ch in text:
            self.draw_char(ch, cx, y, color, scale, color_active, sweep_x)
            info = FONT_CACHE.get_char_info(ch)
            cx += (info["width"] + 1) * scale
        return cx
    
    def get_tile(self, col: int, row: int) -> Optional[List[int]]:
        """Return tile pixels for changed tiles only."""
        if (col, row) in self.dirty_tiles:
            if self._use_numpy:
                arr = self.pixels.reshape(SCREEN_H, SCREEN_W)
                tile_pixels = arr[row * TILE_HEIGHT:(row + 1) * TILE_HEIGHT, col * TILE_WIDTH:(col + 1) * TILE_WIDTH].flatten().tolist()
            else:
                tile_pixels = []
                for ty in range(TILE_HEIGHT):
                    for tx in range(TILE_WIDTH):
                        x = col * TILE_WIDTH + tx
                        y = row * TILE_HEIGHT + ty
                        tile_pixels.append(self.pixels[y * SCREEN_W + x])
            return sanitize_tile_colors(tile_pixels)
        return None
    
    def commit_dirty(self):
        """Store current dirty tiles as previous state and clear dirty set."""
        for col, row in self.dirty_tiles:
            tile = self.get_tile(col, row)
            if tile:
                self.prev_tiles[(col, row)] = tile
        self.dirty_tiles.clear()

def wrap_words_into_lines(words: List[Word], max_pixels: int, scale: int = 1) -> List[Tuple[int, List[Word]]]:
    space_width = get_text_width(" ", scale)
    lines: List[Tuple[int, List[Word]]] = []
    current: List[Word] = []
    current_first = 0
    current_width = 0

    def is_phrase_break(prev: Word, next_word: Word) -> bool:
        if prev.text.rstrip("\"'")[-1:] in ".!?;,":
            return True
        gap = next_word.start - prev.end
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

def _display_word_index_at_time(words: List[Word], t: float, previous_index: int = -1) -> int:
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
    if not words:
        return 0
    if word_index < 0:
        return 0
    if word_index >= len(words):
        return max(0, len(all_lines) - 1)
    for i, (first_idx, line) in enumerate(all_lines):
        if first_idx <= word_index < first_idx + len(line):
            return i
    return max(0, len(all_lines) - 1)

def _draw_line(canvas: CdgCanvas, line_words: List[Word], first_word_index: int, t: float, y: int, scale: int = 1, color_upcoming: int = 1, color_active: int = 2, margin: int = SAFE_MARGIN_X):
    space_width = get_text_width(" ", scale)
    full_width = sum(get_text_width(w.text, scale) for w in line_words)
    full_width += max(0, len(line_words) - 1) * space_width
    x = max(margin, (SCREEN_W - full_width) // 2)
    for word_offset, word in enumerate(line_words):
        w_width = get_text_width(word.text, scale)
        if t <= word.start:
            sweep_x = x
        elif t >= word.end:
            sweep_x = x + w_width
        else:
            p = (t - word.start) / (word.end - word.start)
            sweep_x = x + p * w_width
        x = canvas.draw_text(word.text, x, y, color_upcoming, scale, color_active=color_active, sweep_x=sweep_x)
        x += space_width

def _tile_foreground_color(tile: List[int], color0: int) -> int:
    for idx in tile:
        if idx != color0:
            return idx
    return 1

def build_cdg_from_words_optimized(
    words: List[Word],
    duration_seconds: float,
    output_path: Path,
    visible_lines: int = 4,
    scale: int = 2,
) -> Path:
    """Optimized CDG builder that renders only at key times."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_packets = max(int(duration_seconds * PACKETS_PER_SECOND), 1)
    margin = SAFE_MARGIN_X
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

    # Find key times to render (word boundaries)
    key_times: Set[int] = {0, total_packets}
    for w in words:
        key_times.add(int(w.start * PACKETS_PER_SECOND))
        key_times.add(int(w.end * PACKETS_PER_SECOND))
    # Add page changes
    for idx in range(len(all_lines)):
        line_first = idx
        if idx > 0:
            page_start_time = words[idx].start if idx < len(words) else duration_seconds
            key_times.add(int((idx // visible_lines) * PACKETS_PER_SECOND))

    with open(output_path, "wb") as f:
        f.write(load_color_table_low(PALETTE))
        f.write(load_color_table_high(PALETTE))
        f.write(memory_preset(0, repeat=0))
        f.write(border_preset(0))

        packets_emitted = 4
        current_word_index = -1
        viewport_first_line = 0

        canvas = CdgCanvas()
        canvas.clear(0)
        # Draw initial page
        for offset, (first_idx, line_words) in enumerate(all_lines[viewport_first_line:viewport_first_line + visible_lines]):
            if offset < len(line_y_positions):
                y = line_y_positions[offset]
                _draw_line(canvas, line_words, first_idx, 0.0, y, scale)
        # Emit dirty tiles
        for col, row in canvas.dirty_tiles:
            tile = canvas.get_tile(col, row)
            if tile:
                color1 = _tile_foreground_color(tile, 0)
                f.write(set_tile(col, row, tile, 0, color1))
                packets_emitted += 1
        canvas.commit_dirty()

        sorted_times = sorted(key_times)
        for i in range(len(sorted_times) - 1):
            render_packet = sorted_times[i]
            next_packet = min(sorted_times[i + 1], total_packets)
            
            if packets_emitted >= total_packets:
                break
            
            # Fill NOOPs until render point
            while packets_emitted < render_packet:
                f.write(_NOOP)
                packets_emitted += 1
                if packets_emitted >= total_packets:
                    break
            
            if packets_emitted >= total_packets:
                break

            t = render_packet / PACKETS_PER_SECOND
            current_word_index = _display_word_index_at_time(words, t, current_word_index)
            active_line = _active_line_index(words, current_word_index, all_lines)

            current_page = active_line // visible_lines
            expected_first_line = current_page * visible_lines

            if expected_first_line != viewport_first_line:
                viewport_first_line = expected_first_line
                f.write(memory_preset(0, repeat=0))
                packets_emitted += 1

            # Draw current page
            for offset, (first_idx, line_words) in enumerate(all_lines[viewport_first_line:viewport_first_line + visible_lines]):
                if offset < len(line_y_positions):
                    y = line_y_positions[offset]
                    _draw_line(canvas, line_words, first_idx, t, y, scale)
            
            # Emit dirty tiles
            for col, row in canvas.dirty_tiles:
                tile = canvas.get_tile(col, row)
                if tile:
                    color1 = _tile_foreground_color(tile, 0)
                    f.write(set_tile(col, row, tile, 0, color1))
                    packets_emitted += 1
            canvas.commit_dirty()

        while packets_emitted < total_packets:
            f.write(_NOOP)
            packets_emitted += 1

    return output_path

if __name__ == "__main__":
    test_words = [
        Word("Hello", 1.0, 2.0),
        Word("world", 2.1, 3.0),
        Word("this", 3.1, 3.8),
        Word("is", 3.9, 4.2),
        Word("karaoke", 4.3, 5.5),
    ]
    path = build_cdg_from_words_optimized(test_words, 7.0, Path("test.cdg"))
    print(f"Wrote {path} ({path.stat().st_size} bytes)")