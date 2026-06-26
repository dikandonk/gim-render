# GIM RENDER

Generate professional music visualizer videos from MP3 + cover image. Audio-reactive spectrum equalizer, overlay effects, and automatic AI metadata cleanup.

## Installation

### macOS

```bash
# 1. Install Python 3.12+ (if not installed)
brew install python@3.14

# 2. Install FFmpeg
brew install ffmpeg

# 3. Clone or copy the project
cd musik

# 4. Create virtual environment
python3 -m venv .venv

# 5. Activate venv
source .venv/bin/activate

# 6. Install dependencies
pip install -r requirements.txt

# 7. Run
python3 main.py --gui-tk        # Native desktop GUI
python3 main.py --gui           # Web GUI (open browser)
python3 main.py song.mp3 cover.jpg   # CLI
```

### Windows

```powershell
# 1. Install Python 3.12+ from https://python.org
#    CHECK: "Add Python to PATH" during installation

# 2. Install FFmpeg
winget install ffmpeg

# 3. Open Command Prompt or PowerShell, go to project folder
cd musik

# 4. Create virtual environment
python -m venv .venv

# 5. Activate venv
.venv\Scripts\activate

# 6. Install dependencies
pip install -r requirements.txt

# 7. Run
python main.py --gui-tk         # Native desktop GUI
python main.py --gui            # Web GUI (open browser)
python main.py song.mp3 cover.jpg    # CLI
```

## Usage

```bash
# Single render
python3 main.py song.mp3 cover.jpg

# With options
python3 main.py song.mp3 cover.jpg --fps 24 --resolution 1280x720 --crf 25

# Render folder (auto-match MP3 with same-name image)
python3 main.py --folder assets

# Combine folder into one video
python3 main.py --folder assets --combine -o output/mix.mp4

# Preview 10 seconds (via GUI button or CLI)
# (use GUI for preview feature)
```

## Quick Options

| Flag | Default | Description |
|---|---|---|
| `--fps` | 30 | 24, 30, or 60 |
| `--resolution` | 1280x720 | 1920x1080, 854x480, etc |
| `--crf` | 25 | 0 (lossless) - 51 (worst) |
| `--fast-render` | off | Skip heavy effects |
| `--overlay true` | off | Rain/snow effect |
| `--normalize` | off | EBU R128 loudness norm |
| `--video-encoder` | auto | libx264, h264_videotoolbox, etc |

## Features

- Audio-reactive spectrum equalizer (circular + bars)
- Rain/snow overlay effects
- Video background support
- Automatic AI metadata cleanup (Suno/Udio)
- Queue/batch/combined rendering
- Web GUI + native Tkinter GUI
- Hardware encoder auto-detection

## Requirements

- Python 3.12+
- FFmpeg
- pip packages: see `requirements.txt`
