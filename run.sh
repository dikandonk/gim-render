#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "========================="
echo "  GIM RENDER"
echo "========================="
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    echo "Python: $(python3 --version 2>&1)"
elif command -v python &>/dev/null; then
    echo "Python: $(python --version 2>&1)"
else
    echo "[ERROR] Python not found."
    echo "Install Python 3.10+: https://python.org/downloads/"
    exit 1
fi

# Check FFmpeg
if command -v ffmpeg &>/dev/null; then
    echo "FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo ""
    echo "[WARNING] FFmpeg not found. Attempting auto-install..."
    if command -v brew &>/dev/null; then
        brew install ffmpeg && echo "Done. Please restart." && exit 0
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y ffmpeg && echo "Done." || true
    else
        echo "Please install FFmpeg manually: https://ffmpeg.org/download.html"
        echo "The app will start but rendering may fail."
    fi
fi

echo ""
# Setup venv
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Running setup..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

case "${1:-}" in
    web) echo "Starting GIM RENDER Web GUI..."
         echo "Open http://127.0.0.1:8765 in your browser"
         python main.py --gui ;;
    tk)  echo "Starting GIM RENDER Desktop GUI..."
         python main.py --gui-tk ;;
    cli) python main.py --help ;;
    *)   echo "Starting GIM RENDER Desktop GUI..."
         python main.py --gui-tk ;;
esac
