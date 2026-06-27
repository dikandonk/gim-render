#!/usr/bin/env python3
"""GIM RENDER — Constants."""
from __future__ import annotations

import os

DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_FPS = 24
DEFAULT_BANDS = 32
DEFAULT_ENCODER_PRESET = "ultrafast"
DEFAULT_CRF = 25
DEFAULT_THREADS = max(1, os.cpu_count() or 4)
DEFAULT_VIDEO_ENCODER = "libx264"
DEFAULT_OVERLAY_TYPE = "rain"
DEFAULT_OVERLAY_THICKNESS = "medium"

VIDEO_ENCODERS = ["auto", "libx264", "h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi"]
HARDWARE_ENCODER_PRIORITY = ["h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi"]

ANALYSIS_SAMPLE_RATE = 22050
FFT_SIZE = 1024

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg"}
OVERLAY_TYPES = ["rain", "snow"]
OVERLAY_THICKNESSES = ["thin", "medium", "thick"]
HEIC_EXTENSIONS = {".heic", ".heif"}
