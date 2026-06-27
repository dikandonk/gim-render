#!/usr/bin/env bash
# Universal setup — jalan di mana pun folder ini dipindahkan
# Usage: source setup.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── Bersihkan venv usang dari environment ──────────────────────────
if [ -n "$VIRTUAL_ENV" ]; then
    deactivate 2>/dev/null || true
    unset VIRTUAL_ENV
fi
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '/.venv/bin' | tr '\n' ':' | sed 's/:$//')

# ── Cari python3 paling baru ───────────────────────────────────────
PYTHON=""
for py in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    found=$(command -v "$py" 2>/dev/null) || continue
    if [ -n "$found" ] && ! echo "$found" | grep -q '/.venv/'; then
        PYTHON="$found"
        break
    fi
done
PYTHON="${PYTHON:-python3}"

# ── Cek apakah venv masih cocok dengan lokasi saat ini ─────────────
NEED_RECREATE=false
if [ -f "$VENV_DIR/bin/activate" ]; then
    if ! grep -q "export VIRTUAL_ENV=$VENV_DIR" "$VENV_DIR/bin/activate" 2>/dev/null; then
        NEED_RECREATE=true
    fi
else
    NEED_RECREATE=true
fi

# ── Buat ulang venv jika perlu ─────────────────────────────────────
if $NEED_RECREATE; then
    echo "📦 Creating venv at $VENV_DIR (python: $PYTHON)"
    rm -rf "$VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR" || { echo "❌ Failed to create venv"; return 1; }
    source "$VENV_DIR/bin/activate"
    pip install -r "$SCRIPT_DIR/requirements.txt" -q || { echo "❌ Failed to install"; return 1; }
    echo "✅ Setup complete"
else
    echo "✅ venv ready"
    source "$VENV_DIR/bin/activate"
fi
