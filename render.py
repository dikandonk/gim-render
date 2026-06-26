#!/usr/bin/env python3
"""GIM RENDER — Render pipeline: single video, batch, parallel, and combined folder modes."""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from constants import (
    DEFAULT_BANDS,
    DEFAULT_CRF,
    DEFAULT_ENCODER_PRESET,
    DEFAULT_OVERLAY_THICKNESS,
    DEFAULT_OVERLAY_TYPE,
    DEFAULT_THREADS,
    DEFAULT_VIDEO_ENCODER,
    HARDWARE_ENCODER_PRIORITY,
)
from utils import (
    clean_mp3_metadata,
    display_title,
    output_path_for,
    output_path_for_batch,
    probe_duration,
    read_audio_metadata,
)
from visualizer import Visualizer

try:
    from moviepy import AudioFileClip, VideoClip
except ImportError:
    from moviepy.editor import AudioFileClip, VideoClip


def available_ffmpeg_encoders() -> set[str]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    found = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            found.add(parts[1])
    return found


def resolve_video_encoder(requested: str) -> str:
    if requested == "libx264":
        return requested
    available = available_ffmpeg_encoders()
    if requested == "auto":
        for encoder in HARDWARE_ENCODER_PRIORITY:
            if encoder in available:
                return encoder
        return "libx264"
    if requested not in available:
        print(f"Warning: FFmpeg encoder {requested} is not available. Falling back to libx264.")
        return "libx264"
    return requested


def ffmpeg_output_args(metadata: dict[str, str], video_encoder: str, crf: int) -> list[str]:
    args = []
    if video_encoder == "libx264":
        args.extend(["-pix_fmt", "yuv420p", "-crf", str(crf)])
    elif video_encoder == "h264_videotoolbox":
        bitrate = {0: "50M", 18: "20M", 23: "10M", 28: "5M", 35: "2M", 51: "1M"}.get(crf, "10M")
        args.extend(["-allow_sw", "1", "-pix_fmt", "yuv420p", "-b:v", bitrate])
    elif video_encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        qp_map = {0: 0, 18: 20, 23: 26, 28: 32, 35: 40, 51: 51}
        qp = qp_map.get(crf, 26)
        if video_encoder == "h264_nvenc":
            args.extend(["-pix_fmt", "yuv420p", "-qp", str(qp)])
        elif video_encoder == "h264_qsv":
            args.extend(["-pix_fmt", "yuv420p", "-global_quality", str(qp)])
        else:
            args.extend(["-pix_fmt", "yuv420p", "-qp_i", str(qp), "-qp_p", str(qp)])
    elif video_encoder == "h264_vaapi":
        args.extend(["-pix_fmt", "yuv420p"])
    else:
        args.extend(["-pix_fmt", "yuv420p"])
    for key in ("title", "artist", "album", "date", "comment"):
        value = metadata.get(key)
        if value:
            args.extend(["-metadata", f"{key}={value}"])
    return args


def write_video_clip(
    clip,
    output: Path,
    metadata: dict[str, str],
    fps: int,
    video_encoder: str,
    encoder_preset: str,
    threads: int,
    crf: int,
) -> None:
    write_options = {
        "filename": str(output),
        "codec": video_encoder,
        "audio_codec": "aac",
        "fps": fps,
        "threads": threads,
        "ffmpeg_params": ffmpeg_output_args(metadata, video_encoder, crf) + [
            "-filter_threads",
            str(threads),
            "-filter_complex_threads",
            str(threads),
        ],
    }
    if video_encoder == "libx264":
        write_options["preset"] = encoder_preset
    clip.write_videofile(**write_options)


def trim_audio_segment(source: Path, start_seconds: float, duration_seconds: float, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_seconds:.6f}",
            "-t",
            f"{duration_seconds:.6f}",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(output),
        ],
        check=True,
    )
    return output


def normalize_audio(source: Path, output: Path | None = None) -> Path:
    if output is None:
        output = source.parent / f"{source.stem}_norm.mp3"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(source),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=summary",
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output


def concat_videos(segment_paths: list[Path], output_path: Path) -> Path:
    if not segment_paths:
        raise ValueError("No video segments to combine.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.parent / f".{output_path.stem}-concat.txt"
    try:
        with list_path.open("w", encoding="utf-8") as handle:
            for segment in segment_paths:
                escaped = str(segment.resolve()).replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ],
            check=True,
        )
    finally:
        if list_path.exists():
            list_path.unlink()
    return output_path


def render_video(
    mp3_path: Path,
    image_path: Path,
    background_path: Path | None,
    output_path: Path | None,
    resolution: tuple[int, int],
    fps: int,
    bands: int,
    rotate_image: bool,
    image_effect: str,
    artwork_equalizer: bool,
    equalizer_color: str,
    equalizer_bars: int,
    video_zoom: bool,
    overlay_enabled: bool,
    overlay_type: str,
    overlay_thickness: str,
    time_offset: float = 0.0,
    timeline_duration: float | None = None,
    playlist_titles: list[str] | None = None,
    current_track_index: int | None = None,
    fast_render: bool = False,
    encoder_preset: str = DEFAULT_ENCODER_PRESET,
    threads: int = DEFAULT_THREADS,
    video_encoder: str = DEFAULT_VIDEO_ENCODER,
    crf: int = DEFAULT_CRF,
    encoder_label: str = "Gim Studio 22",
    normalize: bool = False,
    parallelize: bool = True,
    progress_callback=None,
) -> Path:
    if parallelize:
        return render_video_parallel(
            mp3_path=mp3_path,
            image_path=image_path,
            background_path=background_path,
            output_path=output_path,
            resolution=resolution,
            fps=fps,
            bands=bands,
            rotate_image=rotate_image,
            image_effect=image_effect,
            artwork_equalizer=artwork_equalizer,
            equalizer_color=equalizer_color,
            equalizer_bars=equalizer_bars,
            video_zoom=video_zoom,
            overlay_enabled=overlay_enabled,
            overlay_type=overlay_type,
            overlay_thickness=overlay_thickness,
            time_offset=time_offset,
            timeline_duration=timeline_duration,
            playlist_titles=playlist_titles,
            current_track_index=current_track_index,
            fast_render=fast_render,
            encoder_preset=encoder_preset,
            threads=threads,
            video_encoder=video_encoder,
            crf=crf,
        encoder_label=encoder_label,
            progress_callback=progress_callback,
        )

    output = output_path_for(mp3_path, output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    actual_mp3 = mp3_path
    if normalize:
        normalized = mp3_path.parent / f"{mp3_path.stem}_norm.mp3"
        print(f"Normalizing audio to EBU R128...")
        normalize_audio(mp3_path, normalized)
        actual_mp3 = normalized

    cleaned = clean_mp3_metadata(actual_mp3, encoder_label)
    if cleaned:
        print(f"Cleaned {cleaned} AI metadata tag(s) from {actual_mp3.name}")
    metadata = read_audio_metadata(actual_mp3)
    resolved_encoder = resolve_video_encoder(video_encoder)
    if progress_callback:
        progress_callback(0.02)

    visualizer = Visualizer(
        image_path=image_path,
        background_path=background_path,
        mp3_path=actual_mp3,
        metadata=metadata,
        resolution=resolution,
        fps=fps,
        bands=bands,
        rotate_image=rotate_image,
        image_effect=image_effect,
        artwork_equalizer=artwork_equalizer,
        equalizer_color=equalizer_color,
        equalizer_bars=equalizer_bars,
        video_zoom=video_zoom,
        overlay_enabled=overlay_enabled,
        overlay_type=overlay_type,
        overlay_thickness=overlay_thickness,
        time_offset=time_offset,
        timeline_duration=timeline_duration,
        playlist_titles=playlist_titles,
        current_track_index=current_track_index,
        fast_render=fast_render,
        progress_callback=(lambda *a: progress_callback(0.08 + a[0] * 0.84, *a[1:])) if progress_callback else None,
    )
    if progress_callback:
        progress_callback(0.08)
    audio = AudioFileClip(str(actual_mp3))
    clip = VideoClip(visualizer.make_frame, duration=visualizer.analysis.duration).with_fps(fps)
    clip = clip.with_audio(audio)

    try:
        try:
            write_video_clip(clip, output, metadata, fps, resolved_encoder, encoder_preset, threads, crf)
        except OSError:
            if resolved_encoder == "libx264":
                raise
            print(f"Warning: encoder {resolved_encoder} failed. Retrying with libx264.")
            visualizer.close()
            audio.close()
            clip.close()
            visualizer = Visualizer(
                image_path=image_path,
                background_path=background_path,
                mp3_path=mp3_path,
                metadata=metadata,
                resolution=resolution,
                fps=fps,
                bands=bands,
                rotate_image=rotate_image,
                image_effect=image_effect,
                artwork_equalizer=artwork_equalizer,
                equalizer_color=equalizer_color,
                equalizer_bars=equalizer_bars,
                video_zoom=video_zoom,
                overlay_enabled=overlay_enabled,
                overlay_type=overlay_type,
                overlay_thickness=overlay_thickness,
                time_offset=time_offset,
                timeline_duration=timeline_duration,
                playlist_titles=playlist_titles,
                current_track_index=current_track_index,
                fast_render=fast_render,
                progress_callback=(lambda *a: progress_callback(0.08 + a[0] * 0.84, *a[1:])) if progress_callback else None,
            )
            audio = AudioFileClip(str(actual_mp3))
            clip = VideoClip(visualizer.make_frame, duration=visualizer.analysis.duration).with_fps(fps)
            clip = clip.with_audio(audio)
            write_video_clip(clip, output, metadata, fps, "libx264", encoder_preset, threads, crf)
        if progress_callback:
            progress_callback(1.0)
    finally:
        visualizer.close()
        audio.close()
        clip.close()

    return output


def render_video_parallel(
    mp3_path: Path,
    image_path: Path,
    background_path: Path | None,
    output_path: Path | None,
    resolution: tuple[int, int],
    fps: int,
    bands: int,
    rotate_image: bool,
    image_effect: str,
    artwork_equalizer: bool,
    equalizer_color: str,
    equalizer_bars: int,
    video_zoom: bool,
    overlay_enabled: bool,
    overlay_type: str,
    overlay_thickness: str,
    time_offset: float = 0.0,
    timeline_duration: float | None = None,
    playlist_titles: list[str] | None = None,
    current_track_index: int | None = None,
    fast_render: bool = False,
    encoder_preset: str = DEFAULT_ENCODER_PRESET,
    threads: int = DEFAULT_THREADS,
    video_encoder: str = DEFAULT_VIDEO_ENCODER,
    crf: int = DEFAULT_CRF,
    encoder_label: str = "Gim Studio 22",
    progress_callback=None,
) -> Path:
    duration = probe_duration(mp3_path)
    if duration <= 0.0:
        return render_video(
            mp3_path=mp3_path,
            image_path=image_path,
            background_path=background_path,
            output_path=output_path,
            resolution=resolution,
            fps=fps,
            bands=bands,
            rotate_image=rotate_image,
            image_effect=image_effect,
            artwork_equalizer=artwork_equalizer,
            equalizer_color=equalizer_color,
            equalizer_bars=equalizer_bars,
            video_zoom=video_zoom,
            overlay_enabled=overlay_enabled,
            overlay_type=overlay_type,
            overlay_thickness=overlay_thickness,
            time_offset=time_offset,
            timeline_duration=timeline_duration,
            playlist_titles=playlist_titles,
            current_track_index=current_track_index,
            fast_render=fast_render,
            encoder_preset=encoder_preset,
            threads=threads,
            video_encoder=video_encoder,
            progress_callback=progress_callback,
            crf=crf,
        encoder_label=encoder_label,
            parallelize=False,
        )

    if timeline_duration is None:
        timeline_duration = duration

    cpu_total = os.cpu_count() or 1
    if cpu_total < 2 or duration < 18 or threads < 2:
        return render_video(
            mp3_path=mp3_path,
            image_path=image_path,
            background_path=background_path,
            output_path=output_path,
            resolution=resolution,
            fps=fps,
            bands=bands,
            rotate_image=rotate_image,
            image_effect=image_effect,
            artwork_equalizer=artwork_equalizer,
            equalizer_color=equalizer_color,
            equalizer_bars=equalizer_bars,
            video_zoom=video_zoom,
            overlay_enabled=overlay_enabled,
            overlay_type=overlay_type,
            overlay_thickness=overlay_thickness,
            time_offset=time_offset,
            timeline_duration=timeline_duration,
            playlist_titles=playlist_titles,
            current_track_index=current_track_index,
            fast_render=fast_render,
            encoder_preset=encoder_preset,
            threads=threads,
            video_encoder=video_encoder,
            progress_callback=progress_callback,
            crf=crf,
        encoder_label=encoder_label,
            parallelize=False,
        )

    workers = min(cpu_total, max(2, min(8, int(math.ceil(duration / 20.0)))))
    if workers < 2:
        return render_video(
            mp3_path=mp3_path,
            image_path=image_path,
            background_path=background_path,
            output_path=output_path,
            resolution=resolution,
            fps=fps,
            bands=bands,
            rotate_image=rotate_image,
            image_effect=image_effect,
            artwork_equalizer=artwork_equalizer,
            equalizer_color=equalizer_color,
            equalizer_bars=equalizer_bars,
            video_zoom=video_zoom,
            overlay_enabled=overlay_enabled,
            overlay_type=overlay_type,
            overlay_thickness=overlay_thickness,
            time_offset=time_offset,
            timeline_duration=timeline_duration,
            playlist_titles=playlist_titles,
            current_track_index=current_track_index,
            fast_render=fast_render,
            encoder_preset=encoder_preset,
            threads=threads,
            video_encoder=video_encoder,
            progress_callback=progress_callback,
            crf=crf,
        encoder_label=encoder_label,
            parallelize=False,
        )

    output = output_path_for(mp3_path, output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = read_audio_metadata(mp3_path)
    resolved_encoder = resolve_video_encoder(video_encoder)

    script_path = Path(__file__).resolve().parent / "main.py"
    with tempfile.TemporaryDirectory(prefix="musik-parallel-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        segment_duration = duration / workers
        segment_paths = []
        segment_threads = max(1, threads // workers)
        for index in range(workers):
            start = index * segment_duration
            end = duration if index == workers - 1 else min(duration, (index + 1) * segment_duration)
            local_duration = max(0.1, end - start)
            segment_mp3 = temp_dir / f"{index:04d}.mp3"
            segment_mp4 = temp_dir / f"{index:04d}.mp4"
            trim_audio_segment(mp3_path, start, local_duration, segment_mp3)
            command = [
                sys.executable,
                str(script_path),
                "--render-segment",
                "--segment-input",
                str(segment_mp3),
                "--segment-output",
                str(segment_mp4),
                "--segment-image",
                str(image_path),
                "--segment-resolution",
                f"{resolution[0]}x{resolution[1]}",
                "--segment-fps",
                str(fps),
                "--segment-bands",
                str(bands),
                "--segment-rotate-image",
                "true" if rotate_image else "false",
                "--segment-image-effect",
                image_effect,
                "--segment-artwork-equalizer",
                "true" if artwork_equalizer else "false",
                "--segment-equalizer-color",
                equalizer_color,
                "--segment-equalizer-bars",
                str(equalizer_bars),
                "--segment-video-zoom",
                "true" if video_zoom else "false",
                "--segment-overlay-enabled",
                "true" if overlay_enabled else "false",
                "--segment-overlay-type",
                overlay_type,
                "--segment-overlay-thickness",
                overlay_thickness,
                "--segment-time-offset",
                f"{time_offset + start:.6f}",
                "--segment-timeline-duration",
                f"{timeline_duration:.6f}",
                "--segment-fast-render",
                "true" if fast_render else "false",
                "--segment-encoder-preset",
                encoder_preset,
                "--segment-threads",
                str(segment_threads),
                "--segment-video-encoder",
                resolved_encoder,
                "--segment-crf",
                str(crf),
            ]
            if background_path:
                command.extend(["--segment-background", str(background_path)])
            if playlist_titles:
                command.extend(["--segment-playlist", "\n".join(playlist_titles)])
            if current_track_index is not None:
                command.extend(["--segment-current-track-index", str(current_track_index)])
            segment_paths.append((segment_mp4, command))

        if progress_callback:
            progress_callback(0.08)

        processes = []
        for segment_path, command in segment_paths:
            processes.append((segment_path, subprocess.Popen(command)))

        completed = 0
        while processes:
            remaining = []
            for segment_path, process in processes:
                code = process.poll()
                if code is None:
                    remaining.append((segment_path, process))
                    continue
                if code != 0:
                    raise subprocess.CalledProcessError(code, process.args)
                completed += 1
                if progress_callback:
                    progress_callback(0.08 + (completed / len(segment_paths)) * 0.84)
            processes = remaining
            if processes:
                time.sleep(0.2)

        if progress_callback:
            progress_callback(0.94)
        result = concat_videos([path for path, _ in segment_paths], output)
        if progress_callback:
            progress_callback(1.0)
        return result


def render_batch(
    pairs: list[tuple[Path, Path]],
    background_path: Path | None,
    output_dir: Path | None,
    resolution: tuple[int, int],
    fps: int,
    bands: int,
    rotate_image: bool,
    image_effect: str,
    artwork_equalizer: bool,
    equalizer_color: str,
    equalizer_bars: int,
    video_zoom: bool,
    overlay_enabled: bool,
    overlay_type: str,
    overlay_thickness: str,
    fast_render: bool,
    encoder_preset: str,
    threads: int,
    video_encoder: str,
    crf: int = DEFAULT_CRF,
    encoder_label: str = "Gim Studio 22",
    progress_callback=None,
) -> list[Path]:
    created = []
    for index, (mp3_path, image_path) in enumerate(pairs, start=1):
        if not mp3_path.exists():
            raise FileNotFoundError(f"MP3 file not found: {mp3_path}")
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        print(f"[{index}/{len(pairs)}] {mp3_path.name} + {image_path.name}")
        segment_start = (index - 1) / max(1, len(pairs))
        segment_span = 1 / max(1, len(pairs))
        created.append(
            render_video(
                mp3_path=mp3_path,
                image_path=image_path,
                background_path=background_path,
                output_path=output_path_for_batch(mp3_path, output_dir),
                resolution=resolution,
                fps=fps,
                bands=bands,
                rotate_image=rotate_image,
                image_effect=image_effect,
                artwork_equalizer=artwork_equalizer,
                equalizer_color=equalizer_color,
                equalizer_bars=equalizer_bars,
                video_zoom=video_zoom,
                overlay_enabled=overlay_enabled,
                overlay_type=overlay_type,
                overlay_thickness=overlay_thickness,
                fast_render=fast_render,
                encoder_preset=encoder_preset,
                threads=threads,
                video_encoder=video_encoder,
                crf=crf,
        encoder_label=encoder_label,
                progress_callback=(
                    (lambda value, start=segment_start, span=segment_span: progress_callback(start + value * span))
                    if progress_callback
                    else None
                ),
            )
        )
    return created


def render_combined_folder(
    pairs: list[tuple[Path, Path]],
    background_path: Path | None,
    output_path: Path,
    resolution: tuple[int, int],
    fps: int,
    bands: int,
    rotate_image: bool,
    image_effect: str,
    artwork_equalizer: bool,
    equalizer_color: str,
    equalizer_bars: int,
    video_zoom: bool,
    overlay_enabled: bool,
    overlay_type: str,
    overlay_thickness: str,
    fast_render: bool,
    encoder_preset: str,
    threads: int,
    video_encoder: str,
    crf: int = DEFAULT_CRF,
    encoder_label: str = "Gim Studio 22",
    progress_callback=None,
) -> Path:
    playlist_titles = [display_title(mp3_path) for mp3_path, _ in pairs]
    with tempfile.TemporaryDirectory(prefix="musik-combine-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        segments = []
        for index, (mp3_path, image_path) in enumerate(pairs, start=1):
            if not mp3_path.exists():
                raise FileNotFoundError(f"MP3 file not found: {mp3_path}")
            if not image_path.exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")
            segment_path = temp_dir / f"{index:04d}-{mp3_path.stem}.mp4"
            print(f"[{index}/{len(pairs)}] segment {mp3_path.name} + {image_path.name}")
            segment_start = (index - 1) * 0.92 / max(1, len(pairs))
            segment_span = 0.92 / max(1, len(pairs))
            segments.append(
                render_video(
                    mp3_path=mp3_path,
                    image_path=image_path,
                    background_path=background_path,
                    output_path=segment_path,
                    resolution=resolution,
                    fps=fps,
                    bands=bands,
                    rotate_image=rotate_image,
                    image_effect=image_effect,
                    artwork_equalizer=artwork_equalizer,
                    equalizer_color=equalizer_color,
                    equalizer_bars=equalizer_bars,
                    video_zoom=video_zoom,
                    overlay_enabled=overlay_enabled,
                    overlay_type=overlay_type,
                    overlay_thickness=overlay_thickness,
                    playlist_titles=playlist_titles,
                    current_track_index=index - 1,
                    fast_render=fast_render,
                    encoder_preset=encoder_preset,
                    threads=threads,
                    video_encoder=video_encoder,
                    crf=crf,
        encoder_label=encoder_label,
                    progress_callback=(
                        (lambda value, start=segment_start, span=segment_span: progress_callback(start + value * span))
                        if progress_callback
                        else None
                    ),
                )
            )
        if progress_callback:
            progress_callback(0.94)
        result = concat_videos(segments, output_path)
        if progress_callback:
            progress_callback(1.0)
        return result


def render_preview(
    mp3_path: Path,
    image_path: Path,
    background_path: Path | None,
    output_path: Path,
    resolution: tuple[int, int],
    fps: int,
    bands: int,
    rotate_image: bool,
    image_effect: str,
    artwork_equalizer: bool,
    equalizer_color: str,
    equalizer_bars: int,
    video_zoom: bool,
    overlay_enabled: bool,
    overlay_type: str,
    overlay_thickness: str,
    fast_render: bool = True,
    encoder_preset: str = DEFAULT_ENCODER_PRESET,
    threads: int = DEFAULT_THREADS,
    video_encoder: str = DEFAULT_VIDEO_ENCODER,
    crf: int = DEFAULT_CRF,
    encoder_label: str = "Gim Studio 22",
    progress_callback=None,
) -> Path:
    preview_dir = Path(tempfile.mkdtemp(prefix="gim-preview-"))
    preview_mp3 = preview_dir / "preview_segment.mp3"

    duration = probe_duration(mp3_path)
    preview_duration = min(5.0, duration)
    trim_audio_segment(mp3_path, 0.0, preview_duration, preview_mp3)

    if progress_callback:
        progress_callback(0.05)

    result = render_video(
        mp3_path=preview_mp3,
        image_path=image_path,
        background_path=background_path,
        output_path=output_path,
        resolution=resolution,
        fps=fps,
        bands=bands,
        rotate_image=rotate_image,
        image_effect=image_effect,
        artwork_equalizer=artwork_equalizer,
        equalizer_color=equalizer_color,
        equalizer_bars=equalizer_bars,
        video_zoom=video_zoom,
        overlay_enabled=overlay_enabled,
        overlay_type=overlay_type,
        overlay_thickness=overlay_thickness,
        fast_render=fast_render,
        encoder_preset=encoder_preset,
        threads=threads,
        video_encoder=video_encoder,
        crf=crf,
        encoder_label=encoder_label,
        parallelize=False,
        progress_callback=(
            (lambda value: progress_callback(0.05 + value * 0.93)) if progress_callback else None
        ),
    )

    if progress_callback:
        progress_callback(1.0)

    return result
