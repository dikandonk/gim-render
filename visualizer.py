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
        equalizer_style: str = "rounded",
        video_zoom: bool = False,
        overlay_enabled: bool = False,
        overlay_type: str = DEFAULT_OVERLAY_TYPE,
        overlay_thickness: str = DEFAULT_OVERLAY_THICKNESS,
        time_offset: float = 0.0,
        timeline_duration: float | None = None,
        playlist_titles: list[str] | None = None,
        current_track_index: int | None = None,
        fast_render: bool = False,
        internal_scale: float = 0.5,
        watermark_path: Path | None = None,
        extra_images: list[Path] | None = None,
        image_duration: float = 0.0,
        lrc_path: Path | None = None,
        progress_callback=None,
    ) -> None:
        self.image_path = image_path
        self.mp3_path = mp3_path
        self.metadata = metadata
        self.background_path = background_path or image_path
        self.out_width, self.out_height = resolution
        self._internal_scale = internal_scale
        self.width = int(self.out_width * self._internal_scale)
        self.height = int(self.out_height * self._internal_scale)
        self.fps = fps
        self.bands = bands
        self.rotate_image = rotate_image
        self.image_effect = image_effect
        self.artwork_equalizer = artwork_equalizer
        self.equalizer_color = equalizer_color
        self.equalizer_bars = equalizer_bars
        self.equalizer_style = equalizer_style
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
        self.watermark = None
        if watermark_path and watermark_path.exists():
            wm = Image.open(str(watermark_path)).convert("RGBA")
            wm_w, wm_h = max(40, int(self.out_width * 0.08)), int(self.out_height * 0.06)
            wm = wm.resize((wm_w, wm_h), Image.Resampling.LANCZOS)
            alpha = wm.split()[3].point(lambda v: min(v, 120)) if wm.mode == "RGBA" else None
            if alpha:
                wm.putalpha(alpha)
            self.watermark = wm
        self.image_duration = image_duration
        self.lrc_lines: list[tuple[float, str]] = []
        if lrc_path and lrc_path.exists():
            self._load_lrc(lrc_path)
        self.background_clip = None
        self.overlay_clip = None
        self.overlay_path = overlay_asset_path(self.overlay_type, self.overlay_thickness) if self.overlay_enabled else None
        self.background_is_video = is_video_path(self.background_path)
        self.analysis = AudioAnalysis(mp3_path, fps=fps, bands=bands)
        self.background = self._prepare_background(self.background_path, (self.width, self.height))
        self.background_rgba = self.background.convert("RGBA")
        if self.overlay_enabled:
            self.overlay_clip = self._prepare_overlay_clip()
        if not self.background_is_video:
            self.background_rgb = self.background_rgba.convert("RGB")
        self.vignette = self._prepare_vignette()
        if not self.background_is_video:
            self.background_rgba.alpha_composite(self.vignette)
            self.background_rgb = self.background_rgba.convert("RGB")
        self.artwork = circular_artwork(image_path, int(min(self.width, self.height) * 0.42))
        self._artworks = [self.artwork]
        if extra_images:
            for p in extra_images:
                if p.exists():
                    self._artworks.append(circular_artwork(p, int(min(self.width, self.height) * 0.42)))
        if not self.fast_render:
            shadow_base = max(self.artwork.width, self.artwork.height) + 28
            self._artwork_shadow = Image.new("RGBA", (shadow_base, shadow_base), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(self._artwork_shadow)
            half = shadow_base // 2
            radius = min(self.artwork.width, self.artwork.height) // 2
            shadow_draw.ellipse((half - radius, half - radius, half + radius, half + radius), fill=(0, 0, 0, 90))
            self._artwork_shadow = self._artwork_shadow.filter(ImageFilter.GaussianBlur(radius=10))
        self.resize_filter = Image.Resampling.BILINEAR if fast_render else Image.Resampling.LANCZOS
        self.rotate_filter = Image.Resampling.BILINEAR if fast_render else Image.Resampling.BICUBIC
        self.font_large = self._font(38)
        self.font_playlist = self._font(22)
        self.font_playlist_bold = self._font(24, bold=True)
        self.visual_spectrum = np.zeros(self.bands, dtype=np.float32)
        self.frame_bar = tqdm(total=self.analysis.frame_count, desc="Rendering frames")
        self._tqdm_pending = 0
        self.last_frame_index = -1
        self._video_blur_counter = 0
        self._cached_bg_raw = None
        self._cached_bg_time = -1.0
        self._last_zoom = 1.0
        self._eq_overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        self._eq_glow = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))

    @staticmethod
    def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        candidates = []
        if bold:
            candidates.extend(
                [
                    # macOS
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/Library/Fonts/Arial Bold.ttf",
                    # Windows
                    "C:/Windows/Fonts/arialbd.ttf",
                    # Linux
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                ]
            )
        candidates.extend(
            [
                # macOS
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
                # Windows
                "C:/Windows/Fonts/arial.ttf",
                # Linux
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
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
            self._tqdm_pending += frame_index - self.last_frame_index
            self.last_frame_index = frame_index
            if self._tqdm_pending >= 30:
                self.frame_bar.update(self._tqdm_pending)
                self._tqdm_pending = 0
            if self.progress_callback:
                value = (frame_index + 1) / max(1, self.analysis.frame_count)
                try:
                    self.progress_callback(value, frame_index + 1, self.analysis.frame_count)
                except TypeError:
                    self.progress_callback(value)

        energy, spectrum = self.analysis.at(time_seconds)
        self.visual_spectrum = self.visual_spectrum * 0.72 + spectrum * 0.28
        silent = energy < 0.004
        image = self._background(energy, global_time).convert("RGBA")
        draw = ImageDraw.Draw(image, "RGBA")

        self._draw_overlay(image, global_time, energy)
        self._draw_artwork(image, energy, spectrum, global_time)
        if not silent:
            self._draw_equalizer(draw, self.visual_spectrum, energy, time_seconds)
        if self.playlist_titles:
            self._draw_text(draw)
        self._draw_playlist(draw)
        self._draw_lrc(draw, global_time)
        self._draw_vignette(image)

        if self.video_zoom:
            image = self._apply_video_zoom(image, energy, global_time)

        if self.watermark:
            wm_w, wm_h = self.watermark.size
            wx = self.width - wm_w - 16
            wy = 12
            image.paste(self.watermark, (wx, wy), self.watermark)

        if self._internal_scale < 1.0:
            image = image.resize((self.out_width, self.out_height), Image.Resampling.BILINEAR)
        return np.asarray(image.convert("RGB"), dtype=np.uint8)

    def close(self) -> None:
        if self._tqdm_pending:
            self.frame_bar.update(self._tqdm_pending)
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
            if self._cached_bg_raw is not None and abs(time_seconds - self._cached_bg_time) < 0.04:
                base = self._cached_bg_raw.copy()
            else:
                base = self._fit_background_frame(self._background_video_frame(time_seconds), (self.width, self.height)).convert("RGBA")
                self._cached_bg_raw = base.copy()
                self._cached_bg_time = time_seconds
            self._video_blur_counter += 1
            if self._video_blur_counter % 2 == 0:
                radius = 1 if self.fast_render else 3
                half_w, half_h = max(1, self.width // 2), max(1, self.height // 2)
                small = base.resize((half_w, half_h), Image.Resampling.BILINEAR)
                small = small.filter(ImageFilter.GaussianBlur(radius=radius))
                base = small.resize((self.width, self.height), Image.Resampling.BILINEAR)
            base.alpha_composite(Image.new("RGBA", base.size, (5, 8, 13, 82)))
            image = base
        else:
            image = self.background_rgb.copy()
        if not self.fast_render and energy > 0.02:
            pulse = int(energy * 28)
            pulse_layer = Image.new("RGB", image.size, (255, 255, 255))
            image = Image.blend(image, pulse_layer, pulse / 255.0)
        return image

    def _apply_video_zoom(self, image: Image.Image, energy: float, time_seconds: float) -> Image.Image:
        zoom = 1.0 + energy * 0.025
        zoom += max(0.0, math.sin(time_seconds * 2.1)) * 0.007
        if self.fast_render:
            zoom = min(1.05, zoom)
        else:
            zoom = min(1.08, zoom)
        if zoom <= 1.001:
            return image
        if abs(zoom - self._last_zoom) < 0.003:
            return image
        self._last_zoom = zoom
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
        image.alpha_composite(overlay)

    def _draw_artwork(self, image: Image.Image, energy: float, spectrum: np.ndarray, time_seconds: float) -> None:
        if self.image_duration > 0 and len(self._artworks) > 1:
            idx = int(time_seconds / self.image_duration) % len(self._artworks)
            current_artwork = self._artworks[idx]
        else:
            current_artwork = self.artwork

        pulse = 1.0 + energy * 0.055 + math.sin(time_seconds * 1.4) * 0.01
        size = int(current_artwork.width * pulse)
        if self.rotate_image:
            angle = -(time_seconds * 18.0 + energy * 10.0)
            artwork = current_artwork.rotate(angle, resample=self.rotate_filter)
        else:
            artwork = current_artwork
        if size != artwork.width:
            artwork = artwork.resize((size, size), self.resize_filter)
        x = (self.width - size) // 2
        y = (self.height - size) // 2

        if self.fast_render:
            ImageDraw.Draw(image, "RGBA").ellipse((x - 5, y - 5, x + size + 5, y + size + 5), fill=(0, 0, 0, 70))
        else:
            shadow_size = size + 28
            if shadow_size != self._artwork_shadow.width:
                shadow = self._artwork_shadow.resize((shadow_size, shadow_size), Image.Resampling.BILINEAR)
            else:
                shadow = self._artwork_shadow
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
        if energy < 0.003:
            return

        center_x = x + size / 2
        center_y = y + size / 2
        base_radius = size / 2
        outer_padding = 10 if self.fast_render else 15
        rotation = time_seconds * (1.8 + energy * 1.1)
        band_count = max(72, min(180, max(8, self.equalizer_bars) * 6))
        raw_values = np.interp(np.linspace(0, len(spectrum) - 1, band_count), np.arange(len(spectrum)), spectrum)
        smooth_values = smooth(raw_values.astype(np.float32), 2 if self.fast_render else 3)
        smooth_values = smooth(smooth_values, 1 if self.fast_render else 2)

        if self.image_effect in ("bars", "wave", "dots"):
            self._draw_eq_style(image, center_x, center_y, base_radius, outer_padding, smooth_values, energy, rotation, band_count)
            return

        # flex: polygon ring (default)
        overlay = self._eq_overlay
        glow_overlay = self._eq_glow
        overlay.paste((0, 0, 0, 0), (0, 0, self.width, self.height))
        glow_overlay.paste((0, 0, 0, 0), (0, 0, self.width, self.height))
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")
        glow_draw = ImageDraw.Draw(glow_overlay, "RGBA")

        inner_radius = base_radius
        outer_points = []
        inner_points = []
        for idx, value in enumerate(smooth_values):
            angle = (idx / band_count) * math.tau + rotation
            eased = min(1.0, max(0.0, float(value))) ** 1.15
            pulse = 1.0 + energy * 0.55
            outer = base_radius + outer_padding * eased * pulse * 1.05
            dx = math.cos(angle)
            dy = math.sin(angle)
            outer_points.append((center_x + dx * outer, center_y + dy * outer))
            inner_points.append((center_x + dx * inner_radius, center_y + dy * inner_radius))

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

        image.alpha_composite(glow_overlay)
        image.alpha_composite(overlay)

    def _draw_eq_style(self, image, cx, cy, base_r, pad, values, energy, rotation, count):
        overlay = self._eq_overlay
        overlay.paste((0, 0, 0, 0), (0, 0, self.width, self.height))
        draw = ImageDraw.Draw(overlay, "RGBA")

        if self.image_effect == "bars":
            bar_count = min(count, self.equalizer_bars)
            step = count // bar_count
            for i in range(bar_count):
                idx = i * step
                value = float(values[idx])
                eased = min(1.0, max(0.0, value)) ** 1.2
                angle = (idx / count) * math.tau + rotation
                bar_h = max(2, int(eased * pad * 2.5 + energy * 10))
                bar_w = max(2, int(base_r * 0.08))
                dx = math.cos(angle)
                dy = math.sin(angle)
                r0 = base_r + pad * 0.3
                r1 = r0 + bar_h
                inner = (cx + dx * r0, cy + dy * r0)
                outer = (cx + dx * r1, cy + dy * r1)
                color = self._equalizer_color(i / max(1, bar_count - 1), energy)
                draw.line([inner, outer], fill=color, width=bar_w)

        elif self.image_effect == "wave":
            points = []
            for idx in range(count):
                angle = (idx / count) * math.tau + rotation
                value = float(values[idx])
                eased = min(1.0, max(0.0, value)) ** 1.3
                r = base_r + pad * 0.5 + eased * pad * 2.0 + energy * 12
                dx = math.cos(angle)
                dy = math.sin(angle)
                points.append((cx + dx * r, cy + dy * r))
            color = self._equalizer_color(0.5, energy)
            alpha = 160 if self.fast_render else 200
            draw.line(points + [points[0]], fill=(color[0], color[1], color[2], alpha), width=3 if self.fast_render else 4)

        elif self.image_effect == "dots":
            dot_count = min(count // 3, 80)
            step = max(1, count // dot_count)
            for i in range(dot_count):
                idx = (i * step + int(rotation * 10)) % count
                value = float(values[idx])
                eased = min(1.0, max(0.0, value))
                angle = (idx / count) * math.tau
                r = base_r + pad * 0.5 + eased * pad * 3.0 + energy * 15
                dx = math.cos(angle)
                dy = math.sin(angle)
                px = cx + dx * r
                py = cy + dy * r
                dot_r = max(2, int(3 + eased * 6))
                color = self._equalizer_color(i / max(1, dot_count - 1), energy)
                draw.ellipse((px - dot_r, py - dot_r, px + dot_r, py + dot_r), fill=color)

        image.alpha_composite(overlay)

    def _draw_equalizer(self, draw: ImageDraw.ImageDraw, spectrum: np.ndarray, energy: float, time_seconds: float = 0.0) -> None:
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
        style = self.equalizer_style

        if style == "waveform":
            self._draw_waveform(draw, start_x, total_width, center_y, max_height, energy, time_seconds)
            return

        if style == "line":
            points = []
            for idx in range(bar_count):
                value = float(values[idx])
                weighted = min(1.0, max(0.0, value)) ** 1.35 * (0.78 + energy * 0.42)
                bh = int(weighted * max_height)
                x0 = start_x + idx * (bar_width + gap) + bar_width // 2
                y0 = center_y - bh // 2
                points.append((x0, y0))
            for idx in range(bar_count - 1, -1, -1):
                value = float(values[idx])
                weighted = min(1.0, max(0.0, value)) ** 1.35 * (0.78 + energy * 0.42)
                bh = int(weighted * max_height)
                x0 = start_x + idx * (bar_width + gap) + bar_width // 2
                y1 = center_y + bh // 2
                points.append((x0, y1))
            color = self._equalizer_color(0.5, energy)
            draw.polygon(points, fill=(color[0], color[1], color[2], 100))
            draw.line(points + [points[0]], fill=(color[0], color[1], color[2], 200), width=1)
            return

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

            if style == "mirror":
                y0 = center_y - bar_height
                y1 = center_y + bar_height
            elif style == "upward":
                y0 = center_y - bar_height
                y1 = center_y

            use_radius = radius if style != "sharp" else 0

            if not self.fast_render and style != "sharp":
                glow = (color[0], color[1], color[2], 30)
                draw.rounded_rectangle((x0 - 1, y0 - 2, x1 + 1, y1 + 2), radius=use_radius, fill=glow)
            draw.rounded_rectangle((x0, y0, x1, y1), radius=use_radius, fill=color)
            if not self.fast_render and style != "sharp":
                highlight_height = max(1, min(4, bar_height // 6))
                draw.rounded_rectangle(
                    (x0, y0, x1, y0 + highlight_height),
                    radius=use_radius,
                    fill=(255, 255, 255, 58),
                )

    def _draw_waveform(self, draw: ImageDraw.ImageDraw, x_start: int, total_width: int, cy: int, max_h: int, energy: float, t: float) -> None:
        sr = self.analysis.sr
        samples = self.analysis.y
        sample_count = len(samples)
        duration = sample_count / sr
        center_sample = int(t * sr)
        window_samples = max(200, int(sr * 0.08))
        start = max(0, center_sample - window_samples)
        end = min(sample_count, center_sample + window_samples)
        chunk = samples[start:end]
        if len(chunk) < 4:
            return

        points = []
        step = max(1, len(chunk) // total_width)
        for i in range(0, total_width):
            idx = i * step
            if idx >= len(chunk):
                break
            val = float(chunk[min(idx, len(chunk) - 1)])
            y = cy - int(val * max_h * 1.5)
            points.append((x_start + i, y))

        if points:
            color = self._equalizer_color(0.5, energy)
            alpha = 140 if self.fast_render else 200
            draw.line(points, fill=(color[0], color[1], color[2], alpha), width=2 if self.fast_render else 3)

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

    def _load_lrc(self, path: Path) -> None:
        import re
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.findall(r"\[(\d+):(\d+\.\d+)\]", line)
                if m:
                    text = re.sub(r"\[\d+:\d+\.\d+\]", "", line).strip()
                    if text:
                        minutes, seconds = m[-1]
                        t = int(minutes) * 60 + float(seconds)
                        self.lrc_lines.append((t, text))
        self.lrc_lines.sort()

    def _draw_lrc(self, draw: ImageDraw.ImageDraw, time_seconds: float) -> None:
        if not self.lrc_lines:
            return
        for i in range(len(self.lrc_lines) - 1, -1, -1):
            if time_seconds >= self.lrc_lines[i][0]:
                text = self.lrc_lines[i][1]
                bbox = draw.textbbox((0, 0), text, font=self.font_large)
                x = (self.width - (bbox[2] - bbox[0])) // 2
                y = int(self.height * 0.78)
                draw.text((x + 2, y + 2), text, font=self.font_large, fill=(0, 0, 0, 140))
                draw.text((x, y), text, font=self.font_large, fill=(255, 255, 255, 210))
                next_t = self.lrc_lines[i + 1][0] if i + 1 < len(self.lrc_lines) else time_seconds + 5
                remaining = next_t - time_seconds
                if remaining < 0.3:
                    alpha = max(0, int(255 * remaining / 0.3))
                    draw.text((x, y), text, font=self.font_large, fill=(255, 255, 255, alpha))
                return

    def _draw_vignette(self, image: Image.Image) -> None:
        if not self.background_is_video:
            return
        image.alpha_composite(self.vignette)
