#!/usr/bin/env python3
"""GIM RENDER — Utility functions."""
from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from constants import (
    HEIC_EXTENSIONS,
    IMAGE_EXTENSIONS,
    OVERLAY_TYPES,
    OVERLAY_THICKNESSES,
    VIDEO_EXTENSIONS,
)

heif_support = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    heif_support = True
except ImportError:
    pass


def _tag_text(tags: object, key: str) -> str | None:
    if not tags or key not in tags:
        return None
    value = tags[key]
    text = str(value).strip()
    return text or None


def read_audio_metadata(mp3_path: Path) -> dict[str, str]:
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp3 import MP3

    try:
        audio = MP3(str(mp3_path))
    except ID3NoHeaderError:
        return {}

    tags = audio.tags or {}
    metadata = {
        "title": _tag_text(tags, "TIT2"),
        "artist": _tag_text(tags, "TPE1"),
        "album": _tag_text(tags, "TALB"),
        "date": _tag_text(tags, "TDRC") or _tag_text(tags, "TYER"),
        "comment": _tag_text(tags, "TENC") or _tag_text(tags, "TSSE"),
    }
    filtered = {key: value for key, value in metadata.items() if value}

    artist = filtered.get("artist", "")
    if artist and any(word in artist.lower() for word in ("suno", "udio", "suno ai", "udio ai")):
        filtered["artist"] = ""

    return filtered


def clean_mp3_metadata(mp3_path: Path, encoder_label: str = "Gim Studio 22") -> int:
    from mutagen.mp3 import MP3
    from mutagen.id3 import TENC

    try:
        mp3 = MP3(str(mp3_path))
    except Exception:
        return 0

    tags = mp3.tags
    if not tags:
        return 0

    removed = 0
    ai_keywords = ("suno", "udio", "made with")

    for key in list(tags.keys()):
        if key.startswith("COMM"):
            val = str(tags[key]).lower()
            if any(w in val for w in ai_keywords):
                del tags[key]
                removed += 1
        elif key.startswith("WOA"):
            val = str(tags[key]).lower()
            if "suno.com" in val or "udio.com" in val:
                del tags[key]
                removed += 1
        elif key in ("TENC", "TSSE"):
            val = str(tags[key]).lower()
            if any(w in val for w in ai_keywords):
                del tags[key]
                removed += 1

    artist_tag = tags.get("TPE1")
    if artist_tag and any(w in str(artist_tag).lower() for w in ("suno ai", "udio ai")):
        del tags["TPE1"]
        removed += 1

    if removed:
        tags.add(TENC(encoding=3, text=encoder_label))
        tags.save(str(mp3_path))

    return removed


def display_title(mp3_path: Path, metadata: dict[str, str] | None = None) -> str:
    info = metadata if metadata is not None else read_audio_metadata(mp3_path)
    return info.get("title") or mp3_path.stem.replace("_", " ").replace("-", " ").strip() or "GIM RENDER"


def parse_resolution(value: str) -> tuple[int, int]:
    cleaned = value.lower().replace("x", " ").replace(",", " ")
    parts = [part for part in cleaned.split() if part]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Resolution must look like 1280x720")
    width, height = (int(parts[0]), int(parts[1]))
    if width < 320 or height < 240:
        raise argparse.ArgumentTypeError("Resolution is too small")
    return width, height


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("Use true or false")


def load_cover(path: Path, resolution: tuple[int, int]) -> Image.Image:
    if path.suffix.lower() in HEIC_EXTENSIONS and not heif_support:
        raise RuntimeError("HEIC/HEIF images require pillow-heif. Install it with: pip install -r requirements.txt")
    image = Image.open(path).convert("RGB")
    width, height = resolution
    ratio = max(width / image.width, height / image.height)
    resized = image.resize(
        (int(image.width * ratio), int(image.height * ratio)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def cover_square(path: Path, size: int) -> Image.Image:
    image = Image.open(path).convert("RGB")
    side = min(image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def circular_artwork(path: Path, size: int) -> Image.Image:
    artwork = cover_square(path, size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    artwork.putalpha(mask)
    return artwork


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def overlay_asset_path(overlay_type: str, overlay_thickness: str) -> Path:
    overlay_dirs = {
        "rain": "hujan",
        "snow": "salju",
    }
    overlay_files = {
        "thin": "ringan",
        "medium": "sedang",
        "thick": "deras",
    }
    effect_dir = overlay_dirs.get(overlay_type, "hujan")
    effect_level = overlay_files.get(overlay_thickness, "sedang")
    return Path(__file__).resolve().parent / "efek" / effect_dir / f"{effect_dir}_{effect_level}.mov"


def probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return 0.0
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


def smooth(values: np.ndarray, kernel_size: int) -> np.ndarray:
    if kernel_size <= 1:
        return values
    kernel = np.ones(kernel_size, dtype=np.float32) / kernel_size
    return np.convolve(values, kernel, mode="same")


def output_path_for(mp3_path: Path, requested: Path | None) -> Path:
    if requested:
        return requested
    return mp3_path.with_suffix(".mp4")


def output_path_for_batch(mp3_path: Path, output_dir: Path | None) -> Path:
    directory = output_dir if output_dir else mp3_path.parent
    return directory / mp3_path.with_suffix(".mp4").name


def find_batch_pairs(folder: Path, random_images: bool = False) -> list[tuple[Path, Path]]:
    import random

    mp3_files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".mp3")
    image_files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    images_by_stem = {path.stem.lower(): path for path in image_files}

    if not mp3_files:
        raise ValueError(f"No MP3 files found in {folder}")
    if not image_files:
        raise ValueError(f"No JPG or PNG images found in {folder}")

    pairs = []
    shared_image = image_files[0]
    missing = []
    for mp3_path in mp3_files:
        matched_image = images_by_stem.get(mp3_path.stem.lower())
        fallback_image = random.choice(image_files) if random_images else shared_image
        image_path = matched_image or fallback_image
        if image_path:
            pairs.append((mp3_path, image_path))
            if not matched_image:
                mode = "random" if random_images else "default"
                print(f"Warning: using {mode} image {image_path.name} for {mp3_path.name}")
        else:
            missing.append(mp3_path.name)

    if missing:
        names = ", ".join(missing)
        raise ValueError(f"No matching image found for: {names}")
    return pairs


def parse_pair_values(values: list[str]) -> list[tuple[Path, Path]]:
    if len(values) % 2 != 0:
        raise ValueError("--pair expects an even number of paths: mp3 image mp3 image ...")
    pairs = []
    for idx in range(0, len(values), 2):
        pairs.append((Path(values[idx]), Path(values[idx + 1])))
    return pairs
