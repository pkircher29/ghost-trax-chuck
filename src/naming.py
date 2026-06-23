"""KV-style filename parser and output schema utilities.

Mirrors the karaoke-normalizer naming conventions.
"""

import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ParsedFilename:
    artist: str
    title: str
    raw_id: str
    manufacturer: str
    cleaned_name: str


DEFAULT_PREFIX = "KV"
DEFAULT_SCHEMA = "{prefix}{id} - {artist} - {title}"
TARGET_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z]{2})(?P<id>\d+(?:-\d+)?)\s+-\s+(?P<artist>.+?)\s+-\s+(?P<title>.+)$"
)


def parse_filename(filename: str, prefix: str = DEFAULT_PREFIX) -> ParsedFilename:
    """Parse a karaoke-version style filename.

    Expected pattern:
        Artist_Title(MP3+CDG_Karaoke)_12345-01.zip
    """
    name = Path(filename).stem

    # Extract trailing ID: underscores or digits after last underscore/space
    id_match = re.search(r"_(\d+(?:-\d+)?)$", name)
    if not id_match:
        id_match = re.search(r"(\d+(?:-\d+)?)$", name)

    raw_id = id_match.group(1) if id_match else "0000"
    name_without_id = name[: id_match.start()] if id_match else name

    # Strip karaoke suffix like (MP3+CDG_Karaoke)
    name_without_id = re.sub(r"\(.*?\)", "", name_without_id).strip("_ ")

    # Split on underscores
    parts = [p for p in name_without_id.split("_") if p]

    if len(parts) >= 3:
        artist = parts[0]
        title = " ".join(parts[1:])
    elif len(parts) == 2:
        artist = parts[0]
        title = parts[1]
    elif len(parts) == 1:
        artist = "Unknown"
        title = parts[0]
    else:
        artist = "Unknown"
        title = name_without_id or "Unknown"

    artist = _pretty(artist)
    title = _pretty(title)

    return ParsedFilename(
        artist=artist,
        title=title,
        raw_id=raw_id,
        manufacturer=prefix,
        cleaned_name=f"{prefix}{raw_id} - {artist} - {title}",
    )


def _pretty(name: str) -> str:
    """Convert 'Ella_Langley' into 'Ella Langley'."""
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name.title()


def already_in_target_schema(filename: str) -> bool:
    """Check if filename already matches the target naming schema."""
    stem = Path(filename).stem
    return bool(TARGET_PATTERN.match(stem))


def build_output_name(
    artist: str,
    title: str,
    prefix: str,
    song_id: str,
    schema: str = DEFAULT_SCHEMA,
) -> str:
    """Apply the user-defined schema to produce a filename stem."""
    result = schema
    result = result.replace("{prefix}", prefix)
    result = result.replace("{id}", song_id)
    result = result.replace("{artist}", artist)
    result = result.replace("{title}", title)
    return result
