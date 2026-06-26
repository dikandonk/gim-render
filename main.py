#!/usr/bin/env python3
"""GIM RENDER — Generate an audio-reactive MP4 visualizer from an MP3 and a cover image."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as _numpy_check
except ImportError:
    sys.exit(
        "Missing dependencies. Activate the virtual environment first:\n\n"
        "  source .venv/bin/activate\n"
        "  python3 main.py --help\n"
    )

from constants import (
    DEFAULT_BANDS,
    DEFAULT_CRF,
    DEFAULT_ENCODER_PRESET,
    DEFAULT_FPS,
    DEFAULT_OVERLAY_THICKNESS,
    DEFAULT_OVERLAY_TYPE,
    DEFAULT_RESOLUTION,
    DEFAULT_THREADS,
    DEFAULT_VIDEO_ENCODER,
    OVERLAY_THICKNESSES,
    OVERLAY_TYPES,
    VIDEO_ENCODERS,
)
from render import render_batch, render_combined_folder, render_video
from utils import (
    find_batch_pairs,
    output_path_for_batch,
    parse_bool,
    parse_pair_values,
    parse_resolution,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GIM RENDER — Generate a music visualizer MP4 from an MP3 and cover image.",
    )
    parser.add_argument("mp3", type=Path, nargs="?", help="Input MP3 file")
    parser.add_argument("image", type=Path, nargs="?", help="Cover image, JPG or PNG")
    parser.add_argument("--gui", action="store_true", help="Open the web-based graphical interface")
    parser.add_argument("--gui-tk", action="store_true", help="Open the native Tkinter graphical interface")
    parser.add_argument("-o", "--output", type=Path, help="Output MP4 path")
    parser.add_argument("--background-image", type=Path, help="Optional background image or video for the background layer")
    parser.add_argument("--folder", type=Path, help="Render all MP3 files in a folder")
    parser.add_argument("--combine", action="store_true", help="With --folder, combine all songs into one MP4")
    parser.add_argument(
        "--pair",
        nargs="+",
        metavar="PATH",
        help="Render multiple pairs: --pair song1.mp3 image1.jpg song2.mp3 image2.jpg",
    )
    parser.add_argument("--output-dir", type=Path, help="Output directory for --folder or --pair")
    parser.add_argument(
        "--random-images",
        action="store_true",
        help="For --folder, use a random image when no same-name image exists",
    )
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, choices=[24, 30, 60], help="Video frame rate")
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=DEFAULT_RESOLUTION,
        help="Output resolution, for example 1280x720 or 1920x1080",
    )
    parser.add_argument("--bands", type=int, default=DEFAULT_BANDS, choices=range(16, 97), metavar="16-96")
    parser.add_argument(
        "--rotate-image",
        type=parse_bool,
        default=False,
        metavar="true|false",
        help="Rotate the circular cover image, default false",
    )
    parser.add_argument(
        "--image-effect",
        choices=["none", "flex"],
        default="flex",
        help="Artwork border effect, default flex",
    )
    parser.add_argument(
        "--artwork-equalizer",
        type=parse_bool,
        default=False,
        metavar="true|false",
        help="Show the spectrum equalizer around the artwork, default false",
    )
    parser.add_argument(
        "--equalizer-color",
        choices=["default", "cyan", "pink", "amber", "green", "purple", "white", "blue", "red", "orange", "teal", "violet", "lime"],
        default="default",
        help="Equalizer color preset, default keeps the current palette",
    )
    parser.add_argument(
        "--equalizer-bars",
        type=int,
        default=DEFAULT_BANDS,
        choices=range(8, 129),
        metavar="8-128",
        help="Number of equalizer bars, default 32",
    )
    parser.add_argument(
        "--video-zoom",
        type=parse_bool,
        default=False,
        metavar="true|false",
        help="Apply beat-reactive video zoom, default false",
    )
    parser.add_argument(
        "--overlay",
        type=parse_bool,
        default=False,
        metavar="true|false",
        help="Enable an animated overlay effect, default false",
    )
    parser.add_argument(
        "--overlay-type",
        choices=OVERLAY_TYPES,
        default=DEFAULT_OVERLAY_TYPE,
        help="Overlay effect type: rain or snow",
    )
    parser.add_argument(
        "--overlay-thickness",
        choices=OVERLAY_THICKNESSES,
        default=DEFAULT_OVERLAY_THICKNESS,
        help="Overlay thickness: thin, medium, or thick",
    )
    parser.add_argument(
        "--fast-render",
        action="store_true",
        help="Skip heavier per-frame effects for faster rendering",
    )
    parser.add_argument(
        "--encoder-preset",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"],
        default=DEFAULT_ENCODER_PRESET,
        help=f"FFmpeg x264 preset, default {DEFAULT_ENCODER_PRESET}",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=DEFAULT_CRF,
        choices=range(0, 52),
        metavar="0-51",
        help=f"x264 CRF quality (0 lossless - 51 worst), lower = better quality + larger file, default {DEFAULT_CRF}",
    )
    parser.add_argument(
        "--video-encoder",
        choices=VIDEO_ENCODERS,
        default=DEFAULT_VIDEO_ENCODER,
        help="Video encoder: auto chooses hardware encoder when available, otherwise libx264",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"FFmpeg encoder threads, default {DEFAULT_THREADS}",
    )
    parser.add_argument(
        "--encoder-label",
        type=str,
        default="Gim Studio 22",
        help="Encoder label replacing Suno/Udio metadata",
    )
    parser.add_argument("--render-segment", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--segment-input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--segment-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--segment-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--segment-background", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--segment-resolution", type=parse_resolution, help=argparse.SUPPRESS)
    parser.add_argument("--segment-fps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--segment-bands", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--segment-rotate-image", type=parse_bool, help=argparse.SUPPRESS)
    parser.add_argument("--segment-image-effect", help=argparse.SUPPRESS)
    parser.add_argument("--segment-artwork-equalizer", type=parse_bool, help=argparse.SUPPRESS)
    parser.add_argument("--segment-equalizer-color", help=argparse.SUPPRESS)
    parser.add_argument("--segment-equalizer-bars", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--segment-video-zoom", type=parse_bool, help=argparse.SUPPRESS)
    parser.add_argument("--segment-overlay-enabled", type=parse_bool, help=argparse.SUPPRESS)
    parser.add_argument("--segment-overlay-type", help=argparse.SUPPRESS)
    parser.add_argument("--segment-overlay-thickness", help=argparse.SUPPRESS)
    parser.add_argument("--segment-time-offset", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--segment-timeline-duration", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--segment-fast-render", type=parse_bool, help=argparse.SUPPRESS)
    parser.add_argument("--segment-encoder-preset", help=argparse.SUPPRESS)
    parser.add_argument("--segment-threads", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--segment-video-encoder", help=argparse.SUPPRESS)
    parser.add_argument("--segment-crf", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--segment-encoder-label", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--segment-playlist", help=argparse.SUPPRESS)
    parser.add_argument("--segment-current-track-index", type=int, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.render_segment:
        if not args.segment_input or not args.segment_output or not args.segment_image or not args.segment_resolution:
            parser.error("--render-segment requires segment input, output, image, and resolution")
        playlist_titles = args.segment_playlist.split("\n") if args.segment_playlist else None
        render_video(
            mp3_path=args.segment_input,
            image_path=args.segment_image,
            background_path=args.segment_background,
            output_path=args.segment_output,
            resolution=args.segment_resolution,
            fps=args.segment_fps or DEFAULT_FPS,
            bands=args.segment_bands or DEFAULT_BANDS,
            rotate_image=bool(args.segment_rotate_image),
            image_effect=args.segment_image_effect or "flex",
            artwork_equalizer=bool(args.segment_artwork_equalizer),
            equalizer_color=args.segment_equalizer_color or "default",
            equalizer_bars=args.segment_equalizer_bars or DEFAULT_BANDS,
            video_zoom=bool(args.segment_video_zoom),
            overlay_enabled=bool(args.segment_overlay_enabled),
            overlay_type=args.segment_overlay_type or DEFAULT_OVERLAY_TYPE,
            overlay_thickness=args.segment_overlay_thickness or DEFAULT_OVERLAY_THICKNESS,
            time_offset=args.segment_time_offset or 0.0,
            timeline_duration=args.segment_timeline_duration,
            playlist_titles=playlist_titles,
            current_track_index=args.segment_current_track_index,
            fast_render=bool(args.segment_fast_render),
            encoder_preset=args.segment_encoder_preset if args.segment_encoder_preset in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium") else DEFAULT_ENCODER_PRESET,
            threads=max(1, args.segment_threads or DEFAULT_THREADS),
            video_encoder=args.segment_video_encoder or DEFAULT_VIDEO_ENCODER,
            encoder_label=args.segment_encoder_label or "Gim Studio 22",
            crf=args.segment_crf if args.segment_crf is not None else DEFAULT_CRF,
            parallelize=False,
        )
        return 0

    if args.gui:
        from gui import launch_gui
        return launch_gui()

    if args.gui_tk:
        from gui_tkinter import launch_gui_tkinter
        return launch_gui_tkinter()

    if args.folder and args.pair:
        parser.error("Use either --folder or --pair, not both")
    if args.combine and not args.folder:
        parser.error("--combine requires --folder")
    if args.folder:
        if not args.folder.exists() or not args.folder.is_dir():
            parser.error(f"Folder not found: {args.folder}")
        try:
            pairs = find_batch_pairs(args.folder, random_images=args.random_images)
            if args.combine:
                output = args.output or output_path_for_batch(Path("combined.mp3"), args.output_dir or args.folder)
                created_video = render_combined_folder(
                    pairs=pairs,
                    background_path=args.background_image,
                    output_path=output,
                    resolution=args.resolution,
                    fps=args.fps,
                    bands=args.bands,
                    rotate_image=args.rotate_image,
                    image_effect=args.image_effect,
                    artwork_equalizer=args.artwork_equalizer,
                    equalizer_color=args.equalizer_color,
                    equalizer_bars=args.equalizer_bars,
                    video_zoom=args.video_zoom,
                    overlay_enabled=args.overlay,
                    overlay_type=args.overlay_type,
                    overlay_thickness=args.overlay_thickness,
                    fast_render=args.fast_render,
                    encoder_preset=args.encoder_preset,
                    threads=args.threads,
                    video_encoder=args.video_encoder,
                    crf=args.crf,
            encoder_label=args.encoder_label,
                )
                print(f"Created {created_video}")
                return 0
            created = render_batch(
                pairs=pairs,
                background_path=args.background_image,
                output_dir=args.output_dir,
                resolution=args.resolution,
                fps=args.fps,
                bands=args.bands,
                rotate_image=args.rotate_image,
                image_effect=args.image_effect,
                artwork_equalizer=args.artwork_equalizer,
                equalizer_color=args.equalizer_color,
                equalizer_bars=args.equalizer_bars,
                video_zoom=args.video_zoom,
                overlay_enabled=args.overlay,
                overlay_type=args.overlay_type,
                overlay_thickness=args.overlay_thickness,
                fast_render=args.fast_render,
                encoder_preset=args.encoder_preset,
                threads=args.threads,
                video_encoder=args.video_encoder,
                crf=args.crf,
            encoder_label=args.encoder_label,
            )
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
        print("Created:")
        for path in created:
            print(f"- {path}")
        return 0
    if args.pair:
        try:
            pairs = parse_pair_values(args.pair)
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
        created = render_batch(
            pairs=pairs,
            background_path=args.background_image,
            output_dir=args.output_dir,
            resolution=args.resolution,
            fps=args.fps,
            bands=args.bands,
            rotate_image=args.rotate_image,
            image_effect=args.image_effect,
            artwork_equalizer=args.artwork_equalizer,
            equalizer_color=args.equalizer_color,
            equalizer_bars=args.equalizer_bars,
            video_zoom=args.video_zoom,
            overlay_enabled=args.overlay,
            overlay_type=args.overlay_type,
            overlay_thickness=args.overlay_thickness,
            fast_render=args.fast_render,
            encoder_preset=args.encoder_preset,
            threads=args.threads,
            video_encoder=args.video_encoder,
            crf=args.crf,
            encoder_label=args.encoder_label,
        )
        print("Created:")
        for path in created:
            print(f"- {path}")
        return 0

    if args.mp3 is None or args.image is None:
        parser.error("mp3 and image are required unless --gui, --folder, or --pair is used")
    if not args.mp3.exists():
        parser.error(f"MP3 file not found: {args.mp3}")
    if not args.image.exists():
        parser.error(f"Image file not found: {args.image}")

    output_path = render_video(
        mp3_path=args.mp3,
        image_path=args.image,
        background_path=args.background_image,
        output_path=args.output,
        resolution=args.resolution,
        fps=args.fps,
        bands=args.bands,
        rotate_image=args.rotate_image,
        image_effect=args.image_effect,
        artwork_equalizer=args.artwork_equalizer,
        equalizer_color=args.equalizer_color,
        equalizer_bars=args.equalizer_bars,
        video_zoom=args.video_zoom,
        overlay_enabled=args.overlay,
        overlay_type=args.overlay_type,
        overlay_thickness=args.overlay_thickness,
        fast_render=args.fast_render,
        encoder_preset=args.encoder_preset,
        threads=args.threads,
        video_encoder=args.video_encoder,
        crf=args.crf,
            encoder_label=args.encoder_label,
    )
    print(f"Created {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
