#!/usr/bin/env python3
"""GIM RENDER — Web-based GUI."""
from __future__ import annotations

import email.parser
import email.policy
import html
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, unquote

from constants import (
    DEFAULT_BANDS,
    DEFAULT_CRF,
    DEFAULT_ENCODER_PRESET,
    DEFAULT_FPS,
    DEFAULT_OVERLAY_THICKNESS,
    DEFAULT_OVERLAY_TYPE,
    DEFAULT_THREADS,
    DEFAULT_VIDEO_ENCODER,
)
from render import render_batch, render_combined_folder, render_preview, render_video
from utils import find_batch_pairs, parse_resolution


def launch_gui() -> int:
    work_dir = Path.cwd()
    upload_dir = Path(tempfile.mkdtemp(prefix="musik-gui-"))
    jobs = {}
    jobs_lock = threading.Lock()

    def set_job(job_id: str, **updates) -> None:
        with jobs_lock:
            jobs.setdefault(job_id, {}).update(updates)

    def get_job(job_id: str) -> dict:
        with jobs_lock:
            return dict(jobs.get(job_id, {"status": "missing", "progress": 0, "message": "Job not found"}))

    def new_job(label: str) -> str:
        job_id = uuid.uuid4().hex
        set_job(job_id, status="queued", progress=0.0, message=label)
        return job_id

    class ReusableServer(ThreadingHTTPServer):
        allow_reuse_address = True

    def find_server() -> ReusableServer:
        for port in range(8765, 8786):
            try:
                return ReusableServer(("127.0.0.1", port), Handler)
            except OSError:
                continue
        raise RuntimeError("No available GUI port from 8765 to 8785")

    def page(message: str = "", is_error: bool = False) -> bytes:
        escaped_message = html.escape(message)
        message_block = ""
        if message:
            kind = "error" if is_error else "success"
            message_block = f'<div class="message {kind}">{escaped_message}</div>'
        alert_script = ""
        if message:
            title = "Render failed" if is_error else "Render complete"
            alert_script = f"<script>window.addEventListener('load', () => alert({title!r} + '\\n\\n' + {message!r}));</script>"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/png" href="/assets/GIM_RENDER.png">
  <title>GIM RENDER</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #101418;
      color: #edf2f7;
    }}
    main {{
      width: min(760px, calc(100vw - 32px));
      margin: 32px auto;
    }}
    h1 {{
      margin: 0 0 18px;
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    form {{
      display: grid;
      gap: 16px;
      padding: 20px;
      border: 1px solid #2a333d;
      border-radius: 8px;
      background: #171d23;
    }}
    label {{
      display: grid;
      gap: 8px;
      color: #b7c2ce;
      font-size: 14px;
    }}
    input, select, button {{
      width: 100%;
      min-height: 40px;
      border-radius: 6px;
      border: 1px solid #33404c;
      background: #0f1419;
      color: #edf2f7;
      padding: 8px 10px;
      font: inherit;
    }}
    input[type="checkbox"] {{
      width: 18px;
      min-height: 18px;
      padding: 0;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    button {{
      cursor: pointer;
      border: 0;
      background: #2dd4bf;
      color: #061412;
      font-weight: 700;
    }}
    .message {{
      margin-bottom: 16px;
      padding: 12px 14px;
      border-radius: 6px;
      white-space: pre-wrap;
    }}
    .success {{ background: #12352f; color: #b9fff4; }}
    .error {{ background: #3a151a; color: #ffd0d6; }}
    .processing {{
      display: none;
      position: fixed;
      inset: 0;
      z-index: 10;
      align-items: center;
      justify-content: center;
      background: rgba(5, 8, 12, 0.72);
      backdrop-filter: blur(3px);
    }}
    .processing-box {{
      width: min(360px, calc(100vw - 48px));
      border: 1px solid #33404c;
      border-radius: 8px;
      background: #171d23;
      padding: 20px;
      box-shadow: 0 16px 46px rgba(0, 0, 0, 0.45);
    }}
    .processing-title {{
      margin: 0 0 10px;
      font-size: 18px;
      font-weight: 700;
    }}
    .processing-bar {{
      height: 8px;
      overflow: hidden;
      border-radius: 999px;
      background: #0f1419;
    }}
    .processing-fill {{
      display: block;
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: #2dd4bf;
      transition: width 0.25s ease;
    }}
    button[disabled] {{
      cursor: wait;
      opacity: 0.72;
    }}
    p {{ color: #9facba; line-height: 1.5; }}
    .render-bar {{
      position: sticky;
      bottom: 0;
      z-index: 5;
      display: flex;
      gap: 10px;
      align-items: center;
      padding: 12px 20px;
      margin: 24px auto 0;
      width: min(760px, calc(100vw - 32px));
      border: 1px solid #2a333d;
      border-radius: 8px 8px 0 0;
      background: #171d23;
      box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.35);
    }}
    .render-bar button {{
      width: auto;
      padding: 8px 18px;
    }}
    .render-time {{
      color: #5eead4;
      font-size: 13px;
      font-weight: 600;
      margin-left: auto;
      white-space: nowrap;
    }}
    .footer {{
      text-align: center;
      padding: 12px;
      color: #4a5568;
      font-size: 12px;
    }}
    @media (max-width: 620px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    body.light {{
      background: #f4f6f8;
      color: #1a202c;
    }}
    body.light main {{
      color: #1a202c;
    }}
    body.light form {{
      background: #ffffff;
      border-color: #e2e8f0;
    }}
    body.light input, body.light select {{
      background: #ffffff;
      color: #1a202c;
      border-color: #cbd5e1;
    }}
    body.light p {{ color: #4a5568; }}
    body.light .render-bar {{
      background: #ffffff;
      border-color: #e2e8f0;
      box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.1);
    }}
    body.light .footer {{ color: #a0aec0; }}
    body.light .processing-box {{
      background: #ffffff;
      border-color: #e2e8f0;
    }}
    body.light .processing-title {{ color: #1a202c; }}
    .theme-toggle {{
      position: fixed;
      top: 12px;
      right: 16px;
      z-index: 20;
      cursor: pointer;
      background: none;
      border: 0;
      font-size: 18px;
      width: auto;
      min-height: auto;
      padding: 4px 8px;
    }}
  </style>
</head>
<body>
  <button class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">🌙</button>
  <div id="processing" class="processing">
    <div class="processing-box">
      <p class="processing-title">Processing render...</p>
      <p id="processingText">Please keep this window open.</p>
      <div class="processing-bar"><div id="processingFill" class="processing-fill"></div></div>
      <p id="processingPercent">0%</p>
    </div>
  </div>
  <main>
    <h1>GIM RENDER</h1>
    <p>Choose one MP3 and image, or render a folder where each MP3 matches an image with the same filename.</p>
    {message_block}
    <h2>Single Render</h2>
    <form method="post" action="/render" enctype="multipart/form-data">
      <label>MP3 file
        <input name="mp3" type="file" accept=".mp3,.wav,.flac,.ogg,.m4a,audio/*" required>
      </label>
      <label>Cover image
        <input name="image" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tif,.tiff,image/*" required>
      </label>
      <label>Background image
        <input name="background_image" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tif,.tiff,.mp4,.m4v,.mov,.mkv,.webm,.avi,.mpg,.mpeg,image/*,video/*">
      </label>
      <label>Output name (saved to output/ folder)
        <input name="output" type="text" value="output_gim_video">
      </label>
      <label class="check">
        <input name="use_mp3_name" type="checkbox" value="true">
        Use MP3 filename as output name
      </label>
      <div class="grid">
        <label>Resolution
          <select name="resolution">
            <option>1280x720</option>
            <option>1920x1080</option>
            <option>854x480</option>
            <option>426x240</option>
          </select>
        </label>
        <label>FPS
          <select name="fps">
            <option>24</option>
            <option>30</option>
            <option>60</option>
          </select>
        </label>
        <label>Upscale
          <select name="internal_scale">
            <option value="0.5" selected>Fast (0.5x)</option>
            <option value="0.75">Balanced (0.75x)</option>
            <option value="1.0">Quality (1.0x)</option>
          </select>
        </label>
        <label>Bands
          <input name="bands" type="number" min="16" max="96" value="{DEFAULT_BANDS}">
        </label>
      </div>
      <label class="check" style="margin-top:4px;">
        <input name="fast_render" type="checkbox" value="true" checked>
        Fast render mode
      </label>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Equalizer (Ring)</h3>
      <div class="grid">
        <label>Equalizer
          <select name="image_effect">
            <option value="flex">flex</option>
            <option value="bars">bars</option>
            <option value="wave">wave</option>
            <option value="dots">dots</option>
            <option value="none">none</option>
          </select>
        </label>
        <label class="check" style="align-self:end;">
          <input name="rotate_image" type="checkbox" value="true">
          Rotate circular image
        </label>
        <label>Video zoom
          <select name="video_zoom">
            <option value="false" selected>false</option>
            <option value="true">true</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Spectrum Bars</h3>
      <div class="grid">
        <label>Spectrum equalizer
          <select name="artwork_equalizer">
            <option value="false" selected>false</option>
            <option value="true">true</option>
          </select>
        </label>
        <label>Equalizer color
          <select name="equalizer_color">
            <option value="default" selected>default</option>
            <option value="cyan">cyan</option>
            <option value="pink">pink</option>
            <option value="amber">amber</option>
            <option value="green">green</option>
            <option value="purple">purple</option>
            <option value="white">white</option>
            <option value="blue">blue</option>
            <option value="red">red</option>
            <option value="orange">orange</option>
            <option value="teal">teal</option>
            <option value="violet">violet</option>
            <option value="lime">lime</option>
          </select>
        </label>
        <label>Equalizer bars
          <input name="equalizer_bars" type="number" min="8" max="128" value="{DEFAULT_BANDS}">
        </label>
        <label>Spectrum bars
          <select name="equalizer_style">
            <option>rounded</option>
            <option>sharp</option>
            <option>upward</option>
            <option>line</option>
            <option>mirror</option>
            <option>waveform</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Overlay</h3>
      <div class="grid">
        <label class="check" style="align-self:end;">
          <input name="overlay_enabled" type="checkbox" value="true">
          Overlay effect
        </label>
        <label>Overlay type
          <select name="overlay_type">
            <option value="rain" selected>rain</option>
            <option value="snow">snow</option>
          </select>
        </label>
        <label>Overlay thickness
          <select name="overlay_thickness">
            <option value="thin">thin</option>
            <option value="medium" selected>medium</option>
            <option value="thick">thick</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Encoding</h3>
      <div class="grid">
        <label>Encoder preset
          <select name="encoder_preset">
            <option>ultrafast</option>
            <option>superfast</option>
            <option>veryfast</option>
            <option>faster</option>
            <option>fast</option>
            <option>medium</option>
          </select>
        </label>
        <label>Video encoder
          <select name="video_encoder">
            <option>libx264</option>
            <option>auto</option>
            <option>h264_videotoolbox</option>
            <option>h264_nvenc</option>
            <option>h264_qsv</option>
            <option>h264_amf</option>
            <option>h264_vaapi</option>
          </select>
        </label>
        <label>Threads
          <input name="threads" type="number" min="1" max="128" value="{DEFAULT_THREADS}">
        </label>
      </div>
      <div class="grid">
        <label>CRF (libx264 only, 0-51)
          <input name="crf" type="number" min="0" max="51" value="{DEFAULT_CRF}">
        </label>
        <label class="check" style="align-self:end;">
          <input name="normalize" type="checkbox" value="true">
          Normalize audio
        </label>
        <label>Encoder label
          <input name="encoder_label" type="text" value="Gim Studio 22">
        </label>
        <label>Watermark image
          <input name="watermark_image" type="file" accept=".png,.jpg,.jpeg,image/*">
        </label>
        <label>Lyrics (.lrc)
          <input name="lrc" type="file" accept=".lrc,.txt">
        </label>
        <label>Slide interval (s)
          <input name="image_duration" type="number" min="0" max="120" value="0" placeholder="0 = off">
        </label>
      </div>
      <button type="submit">Render MP4</button>
      <button type="button" onclick="submitPreview()" style="background:#1a2332;color:#b7c2ce;margin-top:4px;">Preview 5s</button>
      <div id="previewPlayer" style="display:none;margin-top:8px;">
        <video id="previewVideo" controls width="100%" style="border-radius:6px;"></video>
      </div>
    </form>
    <h2>Multi Render</h2>
    <form method="post" action="/render-folder" enctype="multipart/form-data">
      <label>Choose folder files
        <input name="folder_files" type="file" webkitdirectory directory multiple>
      </label>
      <label>Folder path
        <input name="folder" type="text" value="assets">
      </label>
      <label>Output dir
        <input name="output_dir" type="text" value="output">
      </label>
      <label>Background image
        <input name="background_image" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tif,.tiff,.mp4,.m4v,.mov,.mkv,.webm,.avi,.mpg,.mpeg,image/*,video/*">
      </label>
        <label>Combined output name
          <input name="combined_output" type="text" value="combined_gim_video">
        </label>
        <label>Crossfade (s)
          <input name="fade_duration" type="number" min="0" max="10" step="0.5" value="0" placeholder="0 = no crossfade">
        </label>
        <div class="grid">
        <label>Resolution
          <select name="resolution">
            <option>1280x720</option>
            <option>1920x1080</option>
            <option>854x480</option>
            <option>426x240</option>
          </select>
        </label>
        <label>FPS
          <select name="fps">
            <option>24</option>
            <option>30</option>
            <option>60</option>
          </select>
        </label>
        <label>Upscale
          <select name="internal_scale">
            <option value="0.5" selected>Fast (0.5x)</option>
            <option value="0.75">Balanced (0.75x)</option>
            <option value="1.0">Quality (1.0x)</option>
          </select>
        </label>
        <label>Bands
          <input name="bands" type="number" min="16" max="96" value="{DEFAULT_BANDS}">
        </label>
      </div>
      <label class="check" style="margin-top:4px;">
        <input name="fast_render" type="checkbox" value="true" checked>
        Fast render mode
      </label>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Equalizer (Ring)</h3>
      <div class="grid">
        <label>Equalizer
          <select name="image_effect">
            <option value="flex">flex</option>
            <option value="bars">bars</option>
            <option value="wave">wave</option>
            <option value="dots">dots</option>
            <option value="none">none</option>
          </select>
        </label>
        <label class="check" style="align-self:end;">
          <input name="rotate_image" type="checkbox" value="true">
          Rotate circular image
        </label>
        <label>Video zoom
          <select name="video_zoom">
            <option value="false" selected>false</option>
            <option value="true">true</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Spectrum Bars</h3>
      <div class="grid">
        <label>Spectrum equalizer
          <select name="artwork_equalizer">
            <option value="false" selected>false</option>
            <option value="true">true</option>
          </select>
        </label>
        <label>Equalizer color
          <select name="equalizer_color">
            <option value="default" selected>default</option>
            <option value="cyan">cyan</option>
            <option value="pink">pink</option>
            <option value="amber">amber</option>
            <option value="green">green</option>
            <option value="purple">purple</option>
            <option value="white">white</option>
            <option value="blue">blue</option>
            <option value="red">red</option>
            <option value="orange">orange</option>
            <option value="teal">teal</option>
            <option value="violet">violet</option>
            <option value="lime">lime</option>
          </select>
        </label>
        <label>Equalizer bars
          <input name="equalizer_bars" type="number" min="8" max="128" value="{DEFAULT_BANDS}">
        </label>
        <label>Spectrum bars
          <select name="equalizer_style">
            <option>rounded</option>
            <option>sharp</option>
            <option>upward</option>
            <option>line</option>
            <option>mirror</option>
            <option>waveform</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Overlay</h3>
      <div class="grid">
        <label class="check" style="align-self:end;">
          <input name="overlay_enabled" type="checkbox" value="true">
          Overlay effect
        </label>
        <label>Overlay type
          <select name="overlay_type">
            <option value="rain" selected>rain</option>
            <option value="snow">snow</option>
          </select>
        </label>
        <label>Overlay thickness
          <select name="overlay_thickness">
            <option value="thin">thin</option>
            <option value="medium" selected>medium</option>
            <option value="thick">thick</option>
          </select>
        </label>
      </div>
      <h3 style="color:#2dd4bf;margin:12px 0 6px;font-size:13px;">Encoding</h3>
      <div class="grid">
        <label>Encoder preset
          <select name="encoder_preset">
            <option>ultrafast</option>
            <option>superfast</option>
            <option>veryfast</option>
            <option>faster</option>
            <option>fast</option>
            <option>medium</option>
          </select>
        </label>
        <label>Video encoder
          <select name="video_encoder">
            <option>libx264</option>
            <option>auto</option>
            <option>h264_videotoolbox</option>
            <option>h264_nvenc</option>
            <option>h264_qsv</option>
            <option>h264_amf</option>
            <option>h264_vaapi</option>
          </select>
        </label>
        <label>Threads
          <input name="threads" type="number" min="1" max="128" value="{DEFAULT_THREADS}">
        </label>
      </div>
      <div class="grid">
        <label>CRF (libx264 only, 0-51)
          <input name="crf" type="number" min="0" max="51" value="{DEFAULT_CRF}">
        </label>
        <label class="check" style="align-self:end;">
          <input name="normalize" type="checkbox" value="true">
          Normalize audio
        </label>
        <label>Encoder label
          <input name="encoder_label" type="text" value="Gim Studio 22">
        </label>
        <label>Watermark image
          <input name="watermark_image" type="file" accept=".png,.jpg,.jpeg,image/*">
        </label>
        <label>Lyrics (.lrc)
          <input name="lrc" type="file" accept=".lrc,.txt">
        </label>
        <label>Slide interval (s)
          <input name="image_duration" type="number" min="0" max="120" value="0" placeholder="0 = off">
        </label>
      </div>
      <label class="check">
        <input name="random_images" type="checkbox" value="true">
        Random image when no same-name image exists
      </label>
      <label class="check">
        <input name="combine" type="checkbox" value="true">
        Combine all songs into one video
      </label>
      <button type="submit">Render Multi</button>
    </form>
    <h2>Queue</h2>
    <form method="post" action="/render-queue" enctype="multipart/form-data">
      <p>Add MP3 + image logo + background one by one, then render all at once.</p>
      <label>Background (optional)
        <input name="background_image" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tif,.tiff,.mp4,.m4v,.mov,.mkv,.webm,.avi,.mpg,.mpeg,image/*,video/*">
      </label>
      <div id="queueList" style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px;"></div>
      <div style="display:flex;gap:8px;">
        <input type="file" id="queueMp3" accept=".mp3,.wav,.flac,.ogg,.m4a,audio/*" style="flex:1;">
        <input type="file" id="queueImg" accept=".jpg,.jpeg,.png,.webp,.bmp,image/*" style="flex:1;">
        <button type="button" onclick="addQueueItem()" style="width:auto;padding:6px 14px;">Add</button>
      </div>
      <input type="hidden" name="queue_pairs" id="queuePairs" value="">
      <label class="check" style="margin-top:8px;">
        <input name="queue_combine" type="checkbox" value="true">
        Combine all into one video
      </label>
      <button type="submit">Render Queue</button>
    </form>
    <h2>Download</h2>
    <form method="post" action="/download-yt" enctype="multipart/form-data">
      <label>YouTube URL
        <input name="yt_url" type="text" placeholder="https://youtube.com/watch?v=..." required>
      </label>
      <label>Output folder
        <input name="yt_folder" type="text" value="bahan/mp3">
      </label>
      <label class="check">
        <input name="yt_tempo" type="checkbox" value="true">
        Tempo 6x (output to bahan/suno)
      </label>
      <button type="submit">Download</button>
      <p id="ytStatus" style="margin-top:8px;"></p>
    </form>
  </main>
  <div class="render-bar">
    <button onclick="triggerRender()">Render MP4</button>
    <button onclick="submitPreview()" style="background:#1a2332;color:#b7c2ce;">Preview 5s</button>
    <span id="renderTime" class="render-time"></span>
  </div>
  <footer class="footer">
    <p>© GIMBLONG</p>
  </footer>
  <script>
    let renderStartTime = 0;
    const queueData = [];

    function toggleTheme() {{
      const body = document.body;
      const btn = document.querySelector(".theme-toggle");
      body.classList.toggle("light");
      const isLight = body.classList.contains("light");
      btn.textContent = isLight ? "☀️" : "🌙";
      localStorage.setItem("theme", isLight ? "light" : "dark");
    }}
    (function() {{
      if (localStorage.getItem("theme") === "light") {{
        document.body.classList.add("light");
        document.querySelector(".theme-toggle").textContent = "☀️";
      }}
    }})();

    function addQueueItem() {{
      const mp3 = document.getElementById("queueMp3").files[0];
      const img = document.getElementById("queueImg").files[0];
      if (!mp3 || !img) {{ alert("Select both MP3 and image."); return; }}
      queueData.push({{ mp3, img }});
      const item = document.createElement("div");
      item.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 10px;background:#1a2332;border-radius:6px;";
      item.innerHTML = `<span style='flex:1;color:#edf2f7;'>${{mp3.name}}  +  ${{img.name}}</span>
        <button type='button' onclick='this.parentElement.remove();queueData.splice(${{queueData.length-1}},1);updateQueueField();' style='width:auto;padding:2px 10px;background:#3a151a;color:#ffd0d6;font-size:12px;'>Remove</button>`;
      document.getElementById("queueList").appendChild(item);
      updateQueueField();
      document.getElementById("queueMp3").value = "";
      document.getElementById("queueImg").value = "";
    }}
    function updateQueueField() {{
      const pairs = queueData.map(p => p.mp3.name + "::" + p.img.name).join("||");
      document.getElementById("queuePairs").value = pairs;
    }}

    function setProgress(progress, message) {{
      const overlay = document.getElementById("processing");
      const text = document.getElementById("processingText");
      const fill = document.getElementById("processingFill");
      const percent = document.getElementById("processingPercent");
      const value = Math.max(0, Math.min(100, Math.round(progress * 100)));
      if (overlay) overlay.style.display = "flex";
      if (text && message) text.textContent = message;
      if (fill) fill.style.width = value + "%";
      if (percent) percent.textContent = value + "%";
    }}

    async function pollJob(jobId) {{
      while (true) {{
        const response = await fetch("/status/" + jobId);
        const status = await response.json();
        setProgress(status.progress || 0, status.message || "Rendering...");
        if (renderStartTime && status.progress > 0) {{
          const elapsed = ((Date.now() - renderStartTime) / 1000).toFixed(1);
          document.getElementById("renderTime").textContent = elapsed + "s";
        }}
        if (status.status === "done") {{
          const elapsed = renderStartTime ?  " in " + ((Date.now() - renderStartTime) / 1000).toFixed(1) + "s" : "";
          alert("Render complete" + elapsed + "\\n\\n" + status.message);
          window.location.href = "/";
          return;
        }}
        if (status.status === "error" || status.status === "missing") {{
          alert("Render failed\\n\\n" + status.message);
          document.getElementById("renderTime").textContent = "";
          window.location.href = "/";
          return;
        }}
        await new Promise(resolve => setTimeout(resolve, 900));
      }}
    }}

    for (const form of document.querySelectorAll("form")) {{
      form.addEventListener("submit", async event => {{
        event.preventDefault();
        renderStartTime = Date.now();
        const overlay = document.getElementById("processing");
        const text = document.getElementById("processingText");
        const button = form.querySelector("button[type='submit']");
        if (button) {{
          button.disabled = true;
          button.textContent = "Processing...";
        }}
        if (text) {{
          text.textContent = form.action.endsWith("/render-folder")
            ? "Rendering folder. This can take a while for many songs."
            : "Rendering video. This can take a while for long audio.";
        }}
        if (overlay) overlay.style.display = "flex";
        setProgress(0.01, text ? text.textContent : "Starting render...");
        try {{
          const hasFileInput = Boolean(form.querySelector("input[type='file']"));
          const body = hasFileInput ? new FormData(form) : new URLSearchParams(new FormData(form));
          const response = await fetch(form.action, {{ method: "POST", body }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.message || "Failed to start render");
          pollJob(payload.job_id);
        }} catch (error) {{
          alert("Render failed\\n\\n" + error.message);
          window.location.href = "/";
        }}
      }});
    }}

    function triggerRender() {{
      const forms = document.querySelectorAll("form");
      const visible = Array.from(forms).find(f => f.offsetParent !== null) || forms[0];
      if (visible) visible.requestSubmit();
    }}

    async function submitPreview() {{
      const form = document.querySelector("form[action='/render']");
      renderStartTime = Date.now();
      const overlay = document.getElementById("processing");
      const text = document.getElementById("processingText");
      if (text) text.textContent = "Rendering 5s preview...";
      if (overlay) overlay.style.display = "flex";
      setProgress(0.01, "Starting preview...");
      try {{
        const response = await fetch("/preview", {{ method: "POST", body: new FormData(form) }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.message || "Failed to start preview");
        pollPreview(payload.job_id);
      }} catch (error) {{
        alert("Preview failed\\n\\n" + error.message);
        window.location.href = "/";
      }}
    }}

    async function pollPreview(jobId) {{
      while (true) {{
        const response = await fetch("/status/" + jobId);
        const status = await response.json();
        setProgress(status.progress || 0, status.message || "Rendering preview...");
        if (renderStartTime && status.progress > 0) {{
          const elapsed = ((Date.now() - renderStartTime) / 1000).toFixed(1);
          document.getElementById("renderTime").textContent = elapsed + "s";
        }}
        if (status.status === "done") {{
          const video = document.getElementById("previewVideo");
          const player = document.getElementById("previewPlayer");
          const msg = status.message || "";
          const match = msg.match(/Preview: (.+)/);
          if (match && player && video) {{
            player.style.display = "block";
            video.src = "/download/" + encodeURIComponent(match[1]);
            video.play();
          }}
          document.getElementById("processing").style.display = "none";
          return;
        }}
        if (status.status === "error" || status.status === "missing") {{
          alert("Preview failed\\n\\n" + status.message);
          document.getElementById("renderTime").textContent = "";
          window.location.href = "/";
          return;
        }}
        await new Promise(resolve => setTimeout(resolve, 900));
      }}
    }}
  </script>
  {alert_script}
</body>
</html>""".encode()

    def parse_form(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, list[tuple[str, bytes]]]]:
        headers = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(headers + body)
        fields: dict[str, str] = {}
        files: dict[str, list[tuple[str, bytes]]] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                files.setdefault(name, []).append((Path(filename).name, payload))
            else:
                fields[name] = payload.decode(errors="replace").strip()
        return fields, files

    def output_from_form(value: str, mp3_name: str, use_mp3_name: bool = False) -> Path:
        if use_mp3_name:
            name = Path(mp3_name).stem
        else:
            name = value.strip()
            if not name:
                name = Path(mp3_name).stem
        return work_dir / "output" / f"{Path(name).stem}.mp4"

    def path_from_field(value: str) -> Path:
        candidate = Path(value.strip())
        if not candidate.is_absolute():
            candidate = work_dir / candidate
        return candidate

    def parse_urlencoded(body: bytes) -> dict[str, str]:
        parsed = parse_qs(body.decode(errors="replace"), keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def yt_worker(url: str, out_dir: Path, tempo: bool, job_id: str) -> None:
        try:
            set_job(job_id, status="running", progress=0.1, message="Downloading audio...")
            result = subprocess.run(
                ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
                 "-o", str(out_dir / "%(title)s.%(ext)s"), url],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                subprocess.run(
                    [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
                     "-o", str(out_dir / "%(title)s.%(ext)s"), url],
                    capture_output=True, text=True, check=True,
                )

            if tempo:
                set_job(job_id, status="running", progress=0.8, message="Applying tempo 6x...")
                mp3_files = sorted(out_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
                if mp3_files:
                    out_tempo = Path("bahan/suno")
                    out_tempo.mkdir(parents=True, exist_ok=True)
                    output = out_tempo / f"{mp3_files[0].stem} - Tempo 6x.mp3"
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(mp3_files[0]),
                        "-filter:a", "atempo=2.0,atempo=2.0,atempo=1.5",
                        "-vn", str(output),
                    ], check=True)
                    set_job(job_id, status="done", progress=1.0, message=f"Saved: {output}")
                    return

            set_job(job_id, status="done", progress=1.0, message="Download complete")
        except Exception as exc:
            set_job(job_id, status="error", progress=0, message=str(exc))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self.respond(page())
                return
            if self.path.startswith("/status/"):
                job_id = self.path.removeprefix("/status/")
                self.respond_json(get_job(job_id))
                return
            if self.path.startswith("/assets/"):
                asset = work_dir / unquote(self.path.removeprefix("/"))
                if asset.exists() and asset.is_file():
                    content_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
                    ext = asset.suffix.lower()
                    self.send_response(200)
                    self.send_header("Content-Type", content_types.get(ext, "application/octet-stream"))
                    self.send_header("Content-Length", str(asset.stat().st_size))
                    self.end_headers()
                    with asset.open("rb") as handle:
                        self.wfile.write(handle.read())
                    return
            if self.path.startswith("/download/"):
                target = work_dir / unquote(self.path.removeprefix("/download/"))
                if target.exists() and target.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(target.stat().st_size))
                    self.end_headers()
                    with target.open("rb") as handle:
                        self.wfile.write(handle.read())
                    return
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path == "/preview":
                self.render_preview_route()
                return
            if self.path == "/render-queue":
                self.render_queue()
                return
            if self.path == "/render-folder":
                self.render_folder()
                return
            if self.path == "/download-yt":
                self.download_yt()
                return
            if self.path != "/render":
                self.send_error(404)
                return
            self.render_single()

        def download_yt(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                fields = parse_urlencoded(body)
                url = fields.get("yt_url", "").strip()
                if not url:
                    self.respond_json({"job_id": "", "message": "URL is required"}, 400)
                    return
                out_dir = Path(fields.get("yt_folder", "bahan/mp3").strip() or "bahan/mp3")
                out_dir.mkdir(parents=True, exist_ok=True)
                tempo = fields.get("yt_tempo") == "true"

                job_id = new_job(f"Download: {url[:60]}")
                threading.Thread(target=lambda: yt_worker(url, out_dir, tempo, job_id), daemon=True).start()
                self.respond_json({"job_id": job_id})
            except Exception as exc:
                self.respond_json({"job_id": "", "message": str(exc)}, 500)

        def render_queue(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "")
                body = self.rfile.read(length)
                if content_type.startswith("multipart/form-data"):
                    fields, files = parse_form(content_type, body)
                else:
                    fields = parse_urlencoded(body)
                    files = {}
                queue_pairs_raw = fields.get("queue_pairs", "")
                pairs = []
                for part in queue_pairs_raw.split("||"):
                    if "::" not in part:
                        continue
                    mp3_name, img_name = part.split("::", 1)
                    mp3_path = upload_dir / mp3_name
                    img_path = upload_dir / img_name
                    if mp3_path.exists() and img_path.exists():
                        pairs.append((mp3_path, img_path))
                if not pairs:
                    raise ValueError("No queue items. Add at least one MP3 + image pair.")
                bg_path = None
                if files.get("background_image"):
                    bg_name, bg_bytes = files["background_image"][0]
                    bg_path = upload_dir / bg_name
                    bg_path.write_bytes(bg_bytes)
                combine = fields.get("queue_combine") == "true"
                resolution = parse_resolution(fields.get("resolution", "1280x720"))
                fps = int(fields.get("fps", DEFAULT_FPS))
                bands = max(16, min(96, int(fields.get("bands", DEFAULT_BANDS))))
                rotate_image = fields.get("rotate_image") == "true"
                image_effect = fields.get("image_effect", "flex")
                artwork_equalizer = fields.get("artwork_equalizer", "false") == "true"
                equalizer_color = fields.get("equalizer_color", "default")
                equalizer_bars = max(8, min(128, int(fields.get("equalizer_bars", str(DEFAULT_BANDS)))))
                equalizer_style = fields.get("equalizer_style", "rounded")
                video_zoom = fields.get("video_zoom", "false") == "true"
                overlay_enabled = fields.get("overlay_enabled", "false") == "true"
                overlay_type = fields.get("overlay_type", DEFAULT_OVERLAY_TYPE)
                overlay_thickness = fields.get("overlay_thickness", DEFAULT_OVERLAY_THICKNESS)
                fast_render = fields.get("fast_render") == "true"
                internal_scale = float(fields.get("internal_scale", "0.5"))
                encoder_preset = fields.get("encoder_preset", DEFAULT_ENCODER_PRESET)
                threads = max(1, int(fields.get("threads", DEFAULT_THREADS)))
                video_encoder = fields.get("video_encoder", DEFAULT_VIDEO_ENCODER)
                crf = max(0, min(51, int(fields.get("crf", str(DEFAULT_CRF)))))
                encoder_label = fields.get("encoder_label", "Gim Studio 22").strip() or "Gim Studio 22"
                normalize = fields.get("normalize") == "true"
                watermark_path = None
                if files.get("watermark_image"):
                    wm_name, wm_bytes = files["watermark_image"][0]
                    watermark_path = upload_dir / wm_name
                    watermark_path.write_bytes(wm_bytes)
                image_duration = float(fields.get("image_duration", "0") or 0)
                lrc_path = None
                if files.get("lrc"):
                    lrc_name, lrc_bytes = files["lrc"][0]
                    lrc_path = upload_dir / lrc_name
                    lrc_path.write_bytes(lrc_bytes)
                fade_duration = float(fields.get("fade_duration", "0") or 0)
                job_id = new_job("Queued queue render")

                def worker() -> None:
                    try:
                        set_job(job_id, status="running", progress=0.01, message="Rendering queue...")
                        if combine:
                            combined_out = work_dir / "output" / "combined_queue.mp4"
                            created = render_combined_folder(
                                pairs=pairs, background_path=bg_path, output_path=combined_out,
                                resolution=resolution, fps=fps, bands=bands,
                                rotate_image=rotate_image, image_effect=image_effect,
                                artwork_equalizer=artwork_equalizer, equalizer_color=equalizer_color,
                                equalizer_bars=equalizer_bars,
                                equalizer_style=equalizer_style, video_zoom=video_zoom,
                                overlay_enabled=overlay_enabled, overlay_type=overlay_type,
                                overlay_thickness=overlay_thickness, fast_render=fast_render,
                                encoder_preset=encoder_preset, threads=threads,
                                video_encoder=video_encoder, crf=crf,
                                encoder_label=encoder_label, normalize=normalize,
                                progress_callback=lambda value: set_job(
                                    job_id, status="running", progress=value, message="Rendering queue...",
                                ),
                            )
                        else:
                            created_list = render_batch(
                                pairs=pairs, background_path=bg_path, output_dir=work_dir / "output",
                                resolution=resolution, fps=fps, bands=bands,
                                rotate_image=rotate_image, image_effect=image_effect,
                                artwork_equalizer=artwork_equalizer, equalizer_color=equalizer_color,
                                equalizer_bars=equalizer_bars,
                                equalizer_style=equalizer_style, video_zoom=video_zoom,
                                overlay_enabled=overlay_enabled, overlay_type=overlay_type,
                                overlay_thickness=overlay_thickness, fast_render=fast_render,
                                encoder_preset=encoder_preset, threads=threads,
                                video_encoder=video_encoder, crf=crf,
                                encoder_label=encoder_label, normalize=normalize,
                                progress_callback=lambda value: set_job(
                                    job_id, status="running", progress=value, message="Rendering queue...",
                                ),
                            )
                            created = "Created:\n" + "\n".join(str(p) for p in created_list)
                        set_job(job_id, status="done", progress=1.0, message=str(created))
                    except Exception as exc:
                        set_job(job_id, status="error", progress=0.0, message=str(exc))

                threading.Thread(target=worker, daemon=True).start()
                self.respond_json({"job_id": job_id})
            except Exception as exc:
                self.respond_json({"message": str(exc)}, status=400)

        def render_single(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "")
                fields, files = parse_form(content_type, self.rfile.read(length))
                if "mp3" not in files or "image" not in files:
                    raise ValueError("MP3 and image files are required.")

                mp3_name, mp3_bytes = files["mp3"][0]
                image_name, image_bytes = files["image"][0]
                mp3_path = upload_dir / mp3_name
                image_path = upload_dir / image_name
                mp3_path.write_bytes(mp3_bytes)
                image_path.write_bytes(image_bytes)
                background_path = None
                if files.get("background_image"):
                    background_name, background_bytes = files["background_image"][0]
                    background_path = upload_dir / background_name
                    background_path.write_bytes(background_bytes)

                output_path = output_from_form(fields.get("output", ""), mp3_name, fields.get("use_mp3_name") == "true")
                resolution = parse_resolution(fields.get("resolution", "1280x720"))
                fps = int(fields.get("fps", DEFAULT_FPS))
                bands = max(16, min(96, int(fields.get("bands", DEFAULT_BANDS))))
                rotate_image = fields.get("rotate_image") == "true"
                image_effect = fields.get("image_effect", "flex")
                artwork_equalizer = fields.get("artwork_equalizer", "false") == "true"
                equalizer_color = fields.get("equalizer_color", "default")
                equalizer_bars = max(8, min(128, int(fields.get("equalizer_bars", str(DEFAULT_BANDS)))))
                equalizer_style = fields.get("equalizer_style", "rounded")
                video_zoom = fields.get("video_zoom", "false") == "true"
                overlay_enabled = fields.get("overlay_enabled", "false") == "true"
                overlay_type = fields.get("overlay_type", DEFAULT_OVERLAY_TYPE)
                overlay_thickness = fields.get("overlay_thickness", DEFAULT_OVERLAY_THICKNESS)
                fast_render = fields.get("fast_render") == "true"
                internal_scale = float(fields.get("internal_scale", "0.5"))
                encoder_preset = fields.get("encoder_preset", DEFAULT_ENCODER_PRESET)
                threads = max(1, int(fields.get("threads", DEFAULT_THREADS)))
                video_encoder = fields.get("video_encoder", DEFAULT_VIDEO_ENCODER)
                crf = max(0, min(51, int(fields.get("crf", str(DEFAULT_CRF)))))
                encoder_label = fields.get("encoder_label", "Gim Studio 22").strip() or "Gim Studio 22"
                normalize = fields.get("normalize") == "true"
                job_id = new_job("Queued single render")

                def worker(preview: bool = False) -> None:
                    try:
                        set_job(job_id, status="running", progress=0.01, message="Loading dependencies")
                        if preview:
                            preview_path = output_path.parent / f"{output_path.stem}_preview.mp4"
                            created = render_preview(
                                mp3_path=mp3_path,
                                image_path=image_path,
                                background_path=background_path,
                                output_path=preview_path,
                                resolution=resolution,
                                fps=fps,
                                bands=bands,
                                rotate_image=rotate_image,
                                image_effect=image_effect,
                                artwork_equalizer=artwork_equalizer,
                                equalizer_color=equalizer_color,
                                equalizer_bars=equalizer_bars,
                                equalizer_style=equalizer_style,
                                video_zoom=video_zoom,
                                overlay_enabled=overlay_enabled,
                                overlay_type=overlay_type,
                                overlay_thickness=overlay_thickness,
                                fast_render=True,
                                encoder_preset=encoder_preset,
                                threads=threads,
                                video_encoder=video_encoder,
                                crf=crf,
                                encoder_label=encoder_label,
                                normalize=normalize,
                                watermark_path=watermark_path,
                                image_duration=image_duration,
                                lrc_path=lrc_path,
                                fade_duration=fade_duration,
                                progress_callback=lambda value: set_job(
                                    job_id, status="running", progress=value, message="Rendering preview...",
                                ),
                            )
                        else:
                            created = render_video(
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
                                equalizer_style=equalizer_style,
                                video_zoom=video_zoom,
                                overlay_enabled=overlay_enabled,
                                overlay_type=overlay_type,
                                overlay_thickness=overlay_thickness,
                                fast_render=fast_render,
                                internal_scale=internal_scale,
                                encoder_preset=encoder_preset,
                                threads=threads,
                                video_encoder=video_encoder,
                                crf=crf,
                                encoder_label=encoder_label,
                                normalize=normalize,
                                watermark_path=watermark_path,
                                image_duration=image_duration,
                                lrc_path=lrc_path,
                                fade_duration=fade_duration,
                                progress_callback=lambda value: set_job(
                                    job_id, status="running", progress=value, message=f"Rendering {mp3_path.name}",
                                ),
                            )
                        set_job(job_id, status="done", progress=1.0, message=f"Created: {created}")
                    except Exception as exc:
                        set_job(job_id, status="error", progress=0.0, message=str(exc))

                threading.Thread(target=worker, daemon=True).start()
                self.respond_json({"job_id": job_id})
            except Exception as exc:
                self.respond_json({"message": str(exc)}, status=400)

        def render_preview_route(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "")
                fields, files = parse_form(content_type, self.rfile.read(length))
                if "mp3" not in files or "image" not in files:
                    raise ValueError("MP3 and image files are required.")

                mp3_name, mp3_bytes = files["mp3"][0]
                image_name, image_bytes = files["image"][0]
                mp3_path = upload_dir / mp3_name
                image_path = upload_dir / image_name
                mp3_path.write_bytes(mp3_bytes)
                image_path.write_bytes(image_bytes)
                background_path = None
                if files.get("background_image"):
                    background_name, background_bytes = files["background_image"][0]
                    background_path = upload_dir / background_name
                    background_path.write_bytes(background_bytes)

                output_path = output_from_form(fields.get("output", ""), mp3_name, fields.get("use_mp3_name") == "true")
                preview_path = output_path.parent / f"{output_path.stem}_preview.mp4"
                resolution = parse_resolution(fields.get("resolution", "1280x720"))
                fps = int(fields.get("fps", DEFAULT_FPS))
                bands = max(16, min(96, int(fields.get("bands", DEFAULT_BANDS))))
                rotate_image = fields.get("rotate_image") == "true"
                image_effect = fields.get("image_effect", "flex")
                artwork_equalizer = fields.get("artwork_equalizer", "false") == "true"
                equalizer_color = fields.get("equalizer_color", "default")
                equalizer_bars = max(8, min(128, int(fields.get("equalizer_bars", str(DEFAULT_BANDS)))))
                equalizer_style = fields.get("equalizer_style", "rounded")
                video_zoom = fields.get("video_zoom", "false") == "true"
                overlay_enabled = fields.get("overlay_enabled", "false") == "true"
                overlay_type = fields.get("overlay_type", DEFAULT_OVERLAY_TYPE)
                overlay_thickness = fields.get("overlay_thickness", DEFAULT_OVERLAY_THICKNESS)
                encoder_preset = fields.get("encoder_preset", DEFAULT_ENCODER_PRESET)
                threads = max(1, int(fields.get("threads", DEFAULT_THREADS)))
                video_encoder = fields.get("video_encoder", DEFAULT_VIDEO_ENCODER)
                crf = max(0, min(51, int(fields.get("crf", str(DEFAULT_CRF)))))
                encoder_label = fields.get("encoder_label", "Gim Studio 22").strip() or "Gim Studio 22"
                normalize = fields.get("normalize") == "true"
                job_id = new_job("Queued preview")

                def worker() -> None:
                    try:
                        set_job(job_id, status="running", progress=0.01, message="Rendering preview...")
                        created = render_preview(
                            mp3_path=mp3_path,
                            image_path=image_path,
                            background_path=background_path,
                            output_path=preview_path,
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
                            fast_render=True,
                            encoder_preset=encoder_preset,
                            threads=threads,
                            video_encoder=video_encoder,
                            crf=crf,
                            progress_callback=lambda value: set_job(
                                job_id, status="running", progress=value, message="Rendering preview...",
                            ),
                        )
                        set_job(job_id, status="done", progress=1.0, message=f"Preview: {created}")
                    except Exception as exc:
                        set_job(job_id, status="error", progress=0.0, message=str(exc))

                threading.Thread(target=worker, daemon=True).start()
                self.respond_json({"job_id": job_id})
            except Exception as exc:
                self.respond_json({"message": str(exc)}, status=400)

        def render_folder(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "")
                body = self.rfile.read(length)
                if content_type.startswith("multipart/form-data"):
                    fields, files = parse_form(content_type, body)
                else:
                    fields = parse_urlencoded(body)
                    files = {}
                folder = path_from_field(fields.get("folder", ""))
                output_dir = path_from_field(fields.get("output_dir", "output"))
                background_path = None
                if files.get("background_image"):
                    background_name, background_bytes = files["background_image"][0]
                    background_path = upload_dir / background_name
                    background_path.write_bytes(background_bytes)
                uploaded_files = files.get("folder_files", [])
                if uploaded_files:
                    folder = upload_dir / f"folder-{uuid.uuid4().hex}"
                    folder.mkdir(parents=True, exist_ok=True)
                    for filename, payload in uploaded_files:
                        if payload:
                            (folder / Path(filename).name).write_bytes(payload)
                if not folder.exists() or not folder.is_dir():
                    raise ValueError(f"Folder not found: {folder}")
                pairs = find_batch_pairs(folder, random_images=fields.get("random_images") == "true")
                combine = fields.get("combine") == "true"
                combined_name = fields.get("combined_output", "").strip() or "combined_gim_video"
                combined_output = work_dir / "output" / f"{combined_name}.mp4"
                resolution = parse_resolution(fields.get("resolution", "1280x720"))
                fps = int(fields.get("fps", DEFAULT_FPS))
                bands = max(16, min(96, int(fields.get("bands", DEFAULT_BANDS))))
                rotate_image = fields.get("rotate_image") == "true"
                image_effect = fields.get("image_effect", "flex")
                artwork_equalizer = fields.get("artwork_equalizer", "false") == "true"
                equalizer_color = fields.get("equalizer_color", "default")
                equalizer_bars = max(8, min(128, int(fields.get("equalizer_bars", str(DEFAULT_BANDS)))))
                equalizer_style = fields.get("equalizer_style", "rounded")
                video_zoom = fields.get("video_zoom", "false") == "true"
                overlay_enabled = fields.get("overlay_enabled", "false") == "true"
                overlay_type = fields.get("overlay_type", DEFAULT_OVERLAY_TYPE)
                overlay_thickness = fields.get("overlay_thickness", DEFAULT_OVERLAY_THICKNESS)
                fast_render = fields.get("fast_render") == "true"
                internal_scale = float(fields.get("internal_scale", "0.5"))
                encoder_preset = fields.get("encoder_preset", DEFAULT_ENCODER_PRESET)
                threads = max(1, int(fields.get("threads", DEFAULT_THREADS)))
                video_encoder = fields.get("video_encoder", DEFAULT_VIDEO_ENCODER)
                crf = max(0, min(51, int(fields.get("crf", str(DEFAULT_CRF)))))
                encoder_label = fields.get("encoder_label", "Gim Studio 22").strip() or "Gim Studio 22"
                normalize = fields.get("normalize") == "true"
                job_id = new_job("Queued folder render")

                def worker() -> None:
                    try:
                        set_job(job_id, status="running", progress=0.01, message="Loading dependencies")
                        if combine:
                            created_video = render_combined_folder(
                                pairs=pairs,
                                background_path=background_path,
                                output_path=combined_output,
                                resolution=resolution,
                                fps=fps,
                                bands=bands,
                                rotate_image=rotate_image,
                                image_effect=image_effect,
                                artwork_equalizer=artwork_equalizer,
                                equalizer_color=equalizer_color,
                                equalizer_bars=equalizer_bars,
                                equalizer_style=equalizer_style,
                                video_zoom=video_zoom,
                                overlay_enabled=overlay_enabled,
                                overlay_type=overlay_type,
                                overlay_thickness=overlay_thickness,
                                fast_render=fast_render,
                                internal_scale=internal_scale,
                                encoder_preset=encoder_preset,
                                threads=threads,
                                video_encoder=video_encoder,
                                crf=crf,
                                encoder_label=encoder_label,
                                normalize=normalize,
                                watermark_path=watermark_path,
                                image_duration=image_duration,
                                lrc_path=lrc_path,
                                fade_duration=fade_duration,
                                progress_callback=lambda value: set_job(
                                    job_id,
                                    status="running",
                                    progress=value,
                                    message="Rendering combined video",
                                ),
                            )
                            set_job(job_id, status="done", progress=1.0, message=f"Created: {created_video}")
                            return
                        created = render_batch(
                            pairs=pairs,
                            background_path=background_path,
                            output_dir=output_dir,
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
                            progress_callback=lambda value: set_job(
                                job_id,
                                status="running",
                                progress=value,
                                message="Rendering folder",
                            ),
                        )
                        message = "Created:\n" + "\n".join(str(path) for path in created)
                        set_job(job_id, status="done", progress=1.0, message=message)
                    except Exception as exc:
                        set_job(job_id, status="error", progress=0.0, message=str(exc))

                threading.Thread(target=worker, daemon=True).start()
                self.respond_json({"job_id": job_id})
            except Exception as exc:
                self.respond_json({"message": str(exc)}, status=400)

        def log_message(self, format: str, *args: object) -> None:
            return

        def respond(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def respond_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    TCPServer.allow_reuse_address = True
    server = find_server()
    url = f"http://{server.server_address[0]}:{server.server_address[1]}"
    print(f"GUI running at {url}")
    print("Press Ctrl+C to stop.")
    if not os.environ.get("MUSIK_NO_BROWSER"):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGUI stopped.")
    finally:
        server.server_close()
    return 0
