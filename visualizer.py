#!/usr/bin/env python3
"""GIM RENDER — Frame rendering engine for audio-reactive music visualizer."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from tqdm import tqdm

try:
    from moviepy import VideoFileClip as MoviePyVideoFileClip
except ImportError:
    from moviepy.editor import VideoFileClip as MoviePyVideoFileClip

from constants import (
    DEFAULT_BANDS,
    DEFAULT_OVERLAY_THICKNESS,
    DEFAULT_OVERLAY_TYPE,
    OVERLAY_THICKNESSES,
    OVERLAY_TYPES,
)
from audio import AudioAnalysis
from utils import (
    circular_artwork,
    display_title,
    is_video_path,
    load_cover,
    overlay_asset_path,
    smooth,
)


class Visualizer:
    def __init__(
        self,
        image_path: Path,
        background_path: Path | None,
        mp3_path: Path,
        metadata: dict[str, str],
        resolution: tuple[int, int],
        fps: int,
        bands: int,
        rotate_image: bool,
        image_effect: str = "flex",
        artwork_equalizer: bool = True,
        equalizer_color: str = "default",
        equalizer_bars: int = DEFAULT_BANDS,
        video_zoom: bool = False,
        overlay_enabled: bool = False,
        overlay_type: str = DEFAULT_OVERLAY_TYPE,
        overlay_thickness: str = DEFAULT_OVERLAY_THICKNESS,
        time_offset: float = 0.0,
        timeline_duration: float | None = None,
        playlist_titles: list[str] | None = None,
        current_track_index: int | None = None,
        fast_render: bool = False,
        progress_callback=None,
    ) -> None:
        self.image_path = image_path
        self.mp3_path = mp3_path
        self.metadata = metadata
        self.background_path = background_path or image_path
        self.width, self.height = resolution
        self.fps = fps
        self.bands = bands
        self.rotate_image = rotate_image
        self.image_effect = image_effect
        self.artwork_equalizer = artwork_equalizer
        self.equalizer_color = equalizer_color
        self.equalizer_bars = equalizer_bars
        self.video_zoom = video_zoom
        self.overlay_enabled = overlay_enabled
        self.overlay_type = overlay_type if overlay_type in OVERLAY_TYPES else DEFAULT_OVERLAY_TYPE
        self.overlay_thickness = (
            overlay_thickness if overlay_thickness in OVERLAY_THICKNESSES else DEFAULT_OVERLAY_THICKNESS
        )
        self.time_offset = time_offset
        self.timeline_duration = timeline_duration or 0.0
        self.fast_render = fast_render
        self.playlist_titles = playlist_titles or []
        self.current_track_index = current_track_index
        self.progress_callback = progress_callback
        self.background_clip = None
        self.overlay_clip = None
        self.overlay_path = overlay_asset_path(self.overlay_type, self.overlay_thickness) if self.overlay_enabled else None
        self.background_is_video = is_video_path(self.background_path)
        self.analysis = AudioAnalysis(mp3_path, fps=fps, bands=bands)
        self.background = self._prepare_background(self.background_path, resolution)
        self.background_rgba = self.background.convert("RGBA")
        if self.overlay_enabled:
            self.overlay_clip = self._prepare_overlay_clip()
        self.vignette = self._prepare_vignette()
        self.artwork = circular_artwork(image_path, int(min(self.width, self.height) * 0.42))
        self.resize_filter = Image.Resampling.BILINEAR if fast_render else Image.Resampling.LANCZOS
        self.rotate_filter = Image.Resampling.BILINEAR if fast_render else Image.Resampling.BICUBIC
        self.font_large = self._font(38)
        self.font_playlist = self._font(22)
        self.font_playlist_bold = self._font(24, bold=True)
        self.visual_spectrum = np.zeros(self.bands, dtype=np.float32)
        self.frame_bar = tqdm(total=self.analysis.frame_count, desc="Rendering frames")
        self.last_frame_index = -1

    @staticmethod
    def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        candidates = []
        if bold:
            candidates.extend(
                [
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/Library/Fonts/Arial Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                ]
            )
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
        for candidate in candidates:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()

    def make_frame(self, time_seconds: float) -> np.ndarray:
        global_time = time_seconds + self.time_offset
        frame_index = min(
            self.analysis.frame_count - 1,
            max(0, int(time_seconds * self.fps)),
        )
        if frame_index > self.last_frame_index:
            self.frame_bar.update(frame_index - self.last_frame_index)
            self.last_frame_index = frame_index
            if self.progress_callback:
                value = (frame_index + 1) / max(1, self.analysis.frame_count)
                try:
                    self.progress_callback(value, frame_index + 1, self.analysis.frame_count)
                except TypeError:
                    self.progress_callback(value)

        energy, spectrum = self.analysis.at(time_seconds)
        self.visual_spectrum = self.visual_spectrum * 0.72 + spectrum * 0.28
        image = self._background(energy, global_time)
        draw = ImageDraw.Draw(image, "RGBA")

        self._draw_overlay(image, global_time, energy)
        self._draw_artwork(image, energy, spectrum, global_time)
        self._draw_equalizer(draw, self.visual_spectrum, energy)
        if self.playlist_titles:
            self._draw_text(draw)
        self._draw_playlist(draw)
        self._draw_vignette(image)

        if self.video_zoom:
            image = self._apply_video_zoom(image, energy, global_time)

        return np.asarray(image, dtype=np.uint8)

    def close(self) -> None:
        if self.last_frame_index < self.analysis.frame_count - 1:
            self.frame_bar.update(self.analysis.frame_count - 1 - self.last_frame_index)
        self.frame_bar.close()
        if self.background_clip is not None:
            self.background_clip.close()
        if self.overlay_clip is not None:
            self.overlay_clip.close()

    def _prepare_background(self, image_path: Path, resolution: tuple[int, int]) -> Image.Image:
        if self.background_is_video:
            self.background_clip = MoviePyVideoFileClip(str(image_path), audio=False)
            frame = self._background_video_frame(0.0)
            return self._fit_background_frame(frame, resolution)
        blur_radius = 1 if self.fast_render else 3
        blur = load_cover(image_path, resolution).filter(ImageFilter.GaussianBlur(radius=blur_radius))
        overlay = Image.new("RGBA", blur.size, (5, 8, 13, 82))
        image = blur.convert("RGBA")
        image.alpha_composite(overlay)
        return image.convert("RGB")

    def _background_video_frame(self, time_seconds: float) -> Image.Image:
        if self.background_clip is None or self.background_clip.duration in (None, 0):
            if self.background_clip is not None:
                return Image.fromarray(self.background_clip.get_frame(0.0)).convert("RGB")
            return load_cover(self.background_path, (self.width, self.height))
        duration = float(self.background_clip.duration or 0.0)
        if duration > 0:
            time_seconds = time_seconds % duration
        frame = self.background_clip.get_frame(time_seconds)
        return Image.fromarray(frame).convert("RGB")

    def _fit_background_frame(self, frame: Image.Image, resolution: tuple[int, int]) -> Image.Image:
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        width, height = resolution
        ratio = max(width / frame.width, height / frame.height)
        resized = frame.resize(
            (int(frame.width * ratio), int(frame.height * ratio)),
            Image.Resampling.LANCZOS,
        )
        left = (resized.width - width) // 2
        top = (resized.height - height) // 2
        return resized.crop((left, top, left + width, top + height))

    def _prepare_overlay_clip(self):
        if self.overlay_path is None or not self.overlay_path.exists():
            raise FileNotFoundError(f"Overlay video not found: {self.overlay_path}")
        return MoviePyVideoFileClip(str(self.overlay_path), audio=False)

    def _overlay_frame(self, time_seconds: float) -> Image.Image | None:
        if self.overlay_clip is None:
            return None
        duration = float(self.overlay_clip.duration or 0.0)
        if duration > 0:
            time_seconds = time_seconds % duration
        frame = Image.fromarray(self.overlay_clip.get_frame(time_seconds)).convert("RGB")
        frame = self._fit_background_frame(frame, (self.width, self.height)).convert("RGBA")
        luminance = frame.convert("L")
        alpha = luminance.point(lambda value: 0 if value < 10 else 65)
        frame.putalpha(alpha)
        return frame

    def _prepare_vignette(self) -> Image.Image:
        y, x = np.ogrid[: self.height, : self.width]
        center_x = self.width / 2
        center_y = self.height / 2
        distance = np.sqrt(((x - center_x) / center_x) ** 2 + ((y - center_y) / center_y) ** 2)
        alpha = np.clip((distance - 0.42) / 0.82, 0, 1) * 95
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        overlay.putalpha(Image.fromarray(alpha.astype(np.uint8)))
        return overlay

    def _background(self, energy: float, time_seconds: float) -> Image.Image:
        if self.background_is_video:
            base = self._fit_background_frame(self._background_video_frame(time_seconds), (self.width, self.height)).convert("RGBA")
            if self.fast_render:
                base = base.filter(ImageFilter.GaussianBlur(radius=1))
            else:
                base = base.filter(ImageFilter.GaussianBlur(radius=3))
            base.alpha_composite(Image.new("RGBA", base.size, (5, 8, 13, 82)))
            image = base
        else:
            image = self.background_rgba.copy()
        if not self.fast_render and energy > 0.02:
            pulse = int(energy * 28)
            image.alpha_composite(Image.new("RGBA", image.size, (255, 255, 255, pulse)))
        return image.convert("RGB")

    def _apply_video_zoom(self, image: Image.Image, energy: float, time_seconds: float) -> Image.Image:
        zoom = 1.0 + energy * 0.025
        zoom += max(0.0, math.sin(time_seconds * 2.1)) * 0.007
        if self.fast_render:
            zoom = min(1.05, zoom)
        else:
            zoom = min(1.08, zoom)
        if zoom <= 1.001:
            return image
        new_width = max(1, int(round(self.width * zoom)))
        new_height = max(1, int(round(self.height * zoom)))
        scaled = image.resize((new_width, new_height), self.resize_filter)
        left = max(0, (new_width - self.width) // 2)
        top = max(0, (new_height - self.height) // 2)
        return scaled.crop((left, top, left + self.width, top + self.height))

    def _draw_overlay(self, image: Image.Image, time_seconds: float, energy: float) -> None:
        if not self.overlay_enabled:
            return
        overlay = self._overlay_frame(time_seconds)
        if overlay is None:
            return
        image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))

    def _draw_artwork(self, image: Image.Image, energy: float, spectrum: np.ndarray, time_seconds: float) -> None:
        pulse = 1.0 + energy * 0.055 + math.sin(time_seconds * 1.4) * 0.01
        size = int(self.artwork.width * pulse)
        if self.rotate_image:
            angle = -(time_seconds * 18.0 + energy * 10.0)
            artwork = self.artwork.rotate(angle, resample=self.rotate_filter)
        else:
            artwork = self.artwork
        if size != artwork.width:
            artwork = artwork.resize((size, size), self.resize_filter)
        x = (self.width - size) // 2
        y = (self.height - size) // 2

        if self.fast_render:
            ImageDraw.Draw(image, "RGBA").ellipse((x - 5, y - 5, x + size + 5, y + size + 5), fill=(0, 0, 0, 70))
        else:
            shadow = Image.new("RGBA", (size + 28, size + 28), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.ellipse((14, 14, size + 14, size + 14), fill=(0, 0, 0, 90))
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
            image.paste(shadow, (x - 14, y - 14), shadow)
        self._draw_artwork_equalizer(image, x, y, size, spectrum, energy, time_seconds)
        image.paste(artwork, (x, y), artwork)

    def _draw_artwork_equalizer(
        self,
        image: Image.Image,
        x: int,
        y: int,
        size: int,
        spectrum: np.ndarray,
        energy: float,
        time_seconds: float,
    ) -> None:
        if self.image_effect == "none" or not self.artwork_equalizer:
            return

        center_x = x + size / 2
        center_y = y + size / 2
        base_radius = size / 2
        outer_padding = 10 if self.fast_render else 15
        band_count = max(72, max(8, self.equalizer_bars) * 8)
        raw_values = np.interp(np.linspace(0, len(spectrum) - 1, band_count), np.arange(len(spectrum)), spectrum)
        smooth_values = smooth(raw_values.astype(np.float32), 2 if self.fast_render else 3)
        smooth_values = smooth(smooth_values, 1 if self.fast_render else 2)
        rotation = time_seconds * (1.8 + energy * 1.1)

        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        glow_overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")
        glow_draw = ImageDraw.Draw(glow_overlay, "RGBA")

        inner_radius = base_radius
        outer_points = []
        inner_points = []

        for idx, value in enumerate(smooth_values):
            angle = (idx / band_count) * math.tau + rotation
            eased = min(1.0, max(0.0, float(value)))
            eased = eased ** 1.15
            pulse = 1.0 + energy * 0.55
            outer = base_radius + outer_padding * eased * pulse
            if self.image_effect == "flex":
                outer *= 1.05
            dx = math.cos(angle)
            dy = math.sin(angle)
            outer_point = (center_x + dx * outer, center_y + dy * outer)
            inner_point = (center_x + dx * inner_radius, center_y + dy * inner_radius)
            outer_points.append(outer_point)
            inner_points.append(inner_point)

        fill_color = self._equalizer_color(0.5, energy)
        fill_alpha = 130 if self.fast_render else 175
        polygon_points = outer_points + list(reversed(inner_points))
        overlay_draw.polygon(polygon_points, fill=(fill_color[0], fill_color[1], fill_color[2], fill_alpha))

        glow_width = 5 if self.fast_render else 8
        glow_alpha = 85 if self.fast_render else 130
        glow_color = (fill_color[0], fill_color[1], fill_color[2], glow_alpha)
        glow_draw.line(outer_points + [outer_points[0]], fill=glow_color, width=glow_width)

        edge_alpha = 175 if self.fast_render else 225
        edge_color = (fill_color[0], fill_color[1], fill_color[2], edge_alpha)
        edge_width = 2 if self.fast_render else 3
        overlay_draw.line(outer_points + [outer_points[0]], fill=edge_color, width=edge_width)

        image.paste(Image.alpha_composite(image.convert("RGBA"), glow_overlay).convert("RGB"))
        image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))

    def _draw_equalizer(self, draw: ImageDraw.ImageDraw, spectrum: np.ndarray, energy: float) -> None:
        margin = int(self.width * 0.12)
        center_y = int(self.height * 0.86)
        max_height = int(self.height * 0.135)
        gap = max(3, int(self.width * 0.004))
        available = self.width - margin * 2
        bar_count = max(8, self.equalizer_bars)
        bar_width = max(2, min(8, (available - gap * (bar_count - 1)) // bar_count))
        total_width = bar_count * bar_width + (bar_count - 1) * gap
        start_x = (self.width - total_width) // 2

        baseline_width = max(1, int(self.height * 0.004))
        draw.rounded_rectangle(
            (start_x, center_y - baseline_width // 2, start_x + total_width, center_y + baseline_width // 2),
            radius=baseline_width,
            fill=(255, 255, 255, 35),
        )

        values = np.interp(np.linspace(0, len(spectrum) - 1, bar_count), np.arange(len(spectrum)), spectrum)
        for idx, value in enumerate(values):
            distance = abs((idx / max(1, bar_count - 1)) - 0.5) * 2
            center_bias = 1.0 - distance * 0.18
            weighted = min(1.0, max(0.0, float(value)) ** 1.35 * (0.78 + energy * 0.42) * center_bias)
            bar_height = max(4, int(weighted * max_height))
            x0 = start_x + idx * (bar_width + gap)
            x1 = x0 + bar_width
            y0 = center_y - bar_height // 2
            y1 = center_y + bar_height // 2
            hue = idx / max(1, bar_count - 1)
            color = self._equalizer_color(hue, energy)
            radius = max(2, bar_width // 2)
            if not self.fast_render:
                glow = (color[0], color[1], color[2], 30)
                draw.rounded_rectangle((x0 - 1, y0 - 2, x1 + 1, y1 + 2), radius=radius, fill=glow)
            draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=color)
            if not self.fast_render:
                highlight_height = max(1, min(4, bar_height // 6))
                draw.rounded_rectangle(
                    (x0, y0, x1, y0 + highlight_height),
                    radius=radius,
                    fill=(255, 255, 255, 58),
                )

    def _equalizer_color(self, position: float, energy: float) -> tuple[int, int, int, int]:
        palettes = {
            "default": ((36, 224, 220), (255, 91, 134), (255, 214, 104)),
            "cyan": ((80, 255, 245), (36, 224, 220), (128, 190, 255)),
            "pink": ((255, 91, 134), (255, 130, 190), (255, 214, 104)),
            "amber": ((255, 214, 104), (255, 167, 64), (255, 102, 56)),
            "green": ((42, 233, 165), (56, 205, 117), (164, 240, 95)),
            "purple": ((179, 109, 255), (126, 87, 255), (255, 109, 214)),
            "white": ((255, 255, 255), (242, 242, 242), (214, 214, 214)),
            "blue": ((76, 175, 255), (48, 122, 255), (146, 228, 255)),
            "red": ((255, 93, 93), (255, 54, 97), (255, 171, 71)),
            "orange": ((255, 183, 77), (255, 138, 48), (255, 96, 72)),
            "teal": ((45, 212, 191), (34, 197, 94), (125, 211, 252)),
            "violet": ((196, 181, 253), (168, 85, 247), (244, 114, 182)),
            "lime": ((163, 230, 53), (132, 204, 22), (250, 204, 21)),
        }
        colors = palettes.get(self.equalizer_color, palettes["default"])
        if position < 0.5:
            mix = position * 2.0
            rgb = np.array(colors[0]) * (1.0 - mix) + np.array(colors[1]) * mix
        else:
            mix = (position - 0.5) * 2.0
            rgb = np.array(colors[1]) * (1.0 - mix) + np.array(colors[2]) * mix
        rgb = np.clip(rgb + energy * 22, 0, 255).astype(int)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 218

    def _draw_text(self, draw: ImageDraw.ImageDraw) -> None:
        title = display_title(self.mp3_path, self.metadata)
        title = title[:54]
        bbox = draw.textbbox((0, 0), title, font=self.font_large)
        x = (self.width - (bbox[2] - bbox[0])) // 2
        y = int(self.height * (0.685 if self.playlist_titles else 0.765))
        draw.text((x + 2, y + 2), title, font=self.font_large, fill=(0, 0, 0, 150))
        draw.text((x, y), title, font=self.font_large, fill=(255, 255, 255, 235))

    def _draw_playlist(self, draw: ImageDraw.ImageDraw) -> None:
        if not self.playlist_titles:
            return

        max_items = min(len(self.playlist_titles), 12)
        x = int(self.width * 0.055)
        y = int(self.height * 0.08)
        max_width = int(self.width * 0.33)
        line_height = max(22, int(self.height * 0.034))

        panel_height = line_height * max_items + 28
        draw.rounded_rectangle(
            (x - 14, y - 14, x + max_width + 14, y + panel_height),
            radius=8,
            fill=(0, 0, 0, 88),
        )

        total = len(self.playlist_titles)
        start = 0
        if total > max_items and self.current_track_index is not None:
            half = max_items // 2
            start = max(0, min(self.current_track_index - half, total - max_items))

        for visible_index, title in enumerate(self.playlist_titles[start : start + max_items]):
            real_index = start + visible_index
            is_current = real_index == self.current_track_index
            font = self.font_playlist_bold if is_current else self.font_playlist
            prefix = "> " if is_current else "  "
            text = self._fit_text(draw, prefix + title, font, max_width)
            text_y = y + visible_index * line_height
            fill = (255, 255, 255, 245) if is_current else (255, 255, 255, 135)
            if is_current:
                draw.rounded_rectangle(
                    (x - 6, text_y - 3, x + max_width + 6, text_y + line_height - 2),
                    radius=5,
                    fill=(45, 212, 191, 70),
                )
            draw.text((x, text_y), text, font=font, fill=fill)

    @staticmethod
    def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text
        ellipsis = "..."
        trimmed = text
        while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + ellipsis) if trimmed else ellipsis

    def _draw_vignette(self, image: Image.Image) -> None:
        image.paste(Image.alpha_composite(image.convert("RGBA"), self.vignette).convert("RGB"))
