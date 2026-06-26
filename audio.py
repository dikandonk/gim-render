#!/usr/bin/env python3
"""GIM RENDER — Audio analysis: FFT spectrum extraction from MP3 files."""
from __future__ import annotations

import math
from pathlib import Path

import librosa
import numpy as np

from constants import ANALYSIS_SAMPLE_RATE, FFT_SIZE
from utils import smooth


class AudioAnalysis:
    def __init__(self, mp3_path: Path, fps: int, bands: int) -> None:
        self.y, self.sr = librosa.load(mp3_path, sr=ANALYSIS_SAMPLE_RATE, mono=True)
        self.duration = librosa.get_duration(y=self.y, sr=self.sr)
        self.fps = fps
        self.bands = bands
        self.frame_count = max(1, int(math.ceil(self.duration * fps)))
        self.rms = self._rms_energy()
        self.spectrum = self._spectrum()

    def _rms_energy(self) -> np.ndarray:
        hop_length = max(1, int(self.sr / self.fps))
        frame_length = max(FFT_SIZE, hop_length * 2)
        rms = librosa.feature.rms(
            y=self.y,
            frame_length=frame_length,
            hop_length=hop_length,
            center=True,
        )[0]
        rms = self._fit_frames(rms)
        if rms.max() > 0:
            rms = rms / rms.max()
        return smooth(rms.astype(np.float32), 3)

    def _spectrum(self) -> np.ndarray:
        hop_length = max(1, int(self.sr / self.fps))
        stft = np.abs(librosa.stft(self.y, n_fft=FFT_SIZE, hop_length=hop_length))
        freqs = librosa.fft_frequencies(sr=self.sr, n_fft=FFT_SIZE)
        band_edges = np.geomspace(40, min(16000, self.sr / 2), self.bands + 1)
        frames = []

        for lower, upper in zip(band_edges[:-1], band_edges[1:]):
            mask = (freqs >= lower) & (freqs < upper)
            if not np.any(mask):
                frames.append(np.zeros(stft.shape[1], dtype=np.float32))
                continue
            frames.append(stft[mask].mean(axis=0).astype(np.float32))

        spectrum = np.vstack(frames).T
        spectrum = librosa.amplitude_to_db(spectrum, ref=np.max)
        spectrum = np.clip((spectrum + 70.0) / 70.0, 0.0, 1.0)
        fitted = np.vstack([self._fit_frames(spectrum[:, idx]) for idx in range(self.bands)]).T
        for idx in range(self.bands):
            fitted[:, idx] = smooth(fitted[:, idx], 4)
        return fitted.astype(np.float32)

    def _fit_frames(self, values: np.ndarray) -> np.ndarray:
        x_old = np.linspace(0.0, 1.0, num=len(values), endpoint=True)
        x_new = np.linspace(0.0, 1.0, num=self.frame_count, endpoint=True)
        return np.interp(x_new, x_old, values)

    def at(self, time_seconds: float) -> tuple[float, np.ndarray]:
        index = min(self.frame_count - 1, max(0, int(time_seconds * self.fps)))
        return float(self.rms[index]), self.spectrum[index]
