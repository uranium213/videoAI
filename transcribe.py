#!/usr/bin/env python3
"""Speech recognition (faster-whisper). Guna: python3 transcribe.py audio.wav [--lang ms] [--model small] [--json out.json]

Audio di-decode guna ffmpeg supaya tak bergantung pada PyAV.
Keluarkan transkrip bertanda masa, per segmen dan per perkataan.
"""
import argparse, json, subprocess
import numpy as np
from faster_whisper import WhisperModel


def load_audio(path):
    raw = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le",
                                   "-ac", "1", "-ar", "16000", "-"])
    return np.frombuffer(raw, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio"); ap.add_argument("--lang", default="ms")
    ap.add_argument("--model", default="small"); ap.add_argument("--json")
    a = ap.parse_args()
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(load_audio(a.audio), language=a.lang, word_timestamps=True)
    out = []
    for s in segs:
        print(f"[{s.start:6.2f} - {s.end:6.2f}] {s.text.strip()}")
        out.append({"start": s.start, "end": s.end, "text": s.text.strip(),
                    "words": [{"w": w.word.strip(), "start": w.start, "end": w.end} for w in s.words]})
    if a.json:
        json.dump(out, open(a.json, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
