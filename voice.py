"""
Project Prism — Stage 3: CPU Neural TTS & 30-FPS Lip-Sync Envelope Extraction
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import json
import re
import time
import wave
from pathlib import Path
import numpy as np
from kokoro_onnx import Kokoro

TECH_PRONUNCIATIONS = [
    (r"\bVLSI\b", "V L S I"),
    (r"\bCMOS\b", "C MOS"),
    (r"\bNMOS\b", "N MOS"),
    (r"\bPMOS\b", "P MOS"),
    (r"\bFPGA\b", "F P G A"),
    (r"\bALU\b", "A L U"),
    (r"\bCPU\b", "C P U"),
    (r"\bGPU\b", "G P U"),
    (r"\bVRAM\b", "V RAM"),
    (r"\bANSI\b", "AN-see"),
    (r"\bASCII\b", "ASK-ee"),
    (r"\bNULL\b", "null"),
    (r"\bstrlen\b", "string length"),
    (r"\bstrcat\b", "string cat"),
    (r"\bstrcpy\b", "string copy"),
    (r"\bstrcmp\b", "string compare"),
    (r"\bprintf\b", "print f"),
    (r"\bscanf\b", "scan f"),
    (r"#define\b", "hash define"),
    (r"#include\b", "hash include"),
    (r"\b0x([0-9A-Fa-f]+)\b", r"hex \1"),
]


def _normalize_pronunciation(text: str) -> str:
    for pattern, repl in TECH_PRONUNCIATIONS:
        text = re.sub(pattern, repl, text)
    return text


def _resolve_asset(filename: str) -> str:
    p = Path(filename)
    if p.exists():
        return str(p.resolve())
    local = Path(__file__).resolve().parent / filename
    if local.exists():
        return str(local)
    raise FileNotFoundError(
        f"Kokoro asset '{filename}' not found in current folder or {Path(__file__).resolve().parent}."
    )


def _compute_30fps_lipsync(audio_f32: np.ndarray, sample_rate: int) -> list[float]:
    """Extracts a normalized [0.0, 1.0] 30-Hz RMS amplitude envelope for mouth animation."""
    if len(audio_f32) == 0:
        return []
    samples_per_frame = max(1, int(sample_rate / 30.0))
    total_frames = int(np.ceil(len(audio_f32) / samples_per_frame))
    rms_vals = []
    for i in range(total_frames):
        chunk = audio_f32[i * samples_per_frame : (i + 1) * samples_per_frame]
        rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) > 0 else 0.0
        rms_vals.append(rms)

    peak = max(rms_vals) if rms_vals else 0.0
    if peak > 1e-6:
        rms_vals = [round(min(1.0, (v / peak) ** 0.75), 3) for v in rms_vals]
    else:
        rms_vals = [0.0] * len(rms_vals)
    return rms_vals


def _write_wav_16bit(out_path: Path, samples_f32: np.ndarray, sample_rate: int) -> None:
    clipped = np.clip(samples_f32, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())


def synthesize_audio(
    workspace_dir: str = "workspace",
    model_file: str = "kokoro-v1.0.onnx",
    voices_file: str = "voices-v1.0.bin",
) -> dict:
    t0 = time.perf_counter()
    ws_path = Path(workspace_dir).resolve()
    slides = json.loads((ws_path / "scripts.json").read_text(encoding="utf-8"))

    kokoro = Kokoro(_resolve_asset(model_file), _resolve_asset(voices_file))
    sample_rate = 24000
    turn_gap_samples = int(0.28 * sample_rate)
    tail_pad_samples = int(0.35 * sample_rate)

    total_audio_sec = 0.0

    for slide in slides:
        num = slide["slide_number"]
        dialogue = slide.get("dialogue", [])
        if not dialogue:
            dialogue = [{"speaker": "teacher", "emotion": "explaining", "text": slide.get("title") or "Next slide."}]

        chunks = []
        turn_timings = []
        cursor_samples = 0

        for idx, turn in enumerate(dialogue):
            speaker = turn.get("speaker", "teacher").lower()
            raw_text = turn.get("text", "").strip()
            spoken_text = _normalize_pronunciation(raw_text)

            voice_id = "am_michael" if speaker == "teacher" else "af_heart"
            speed = 1.02 if speaker == "teacher" else 1.06

            wav_samples, sr = kokoro.create(spoken_text, voice=voice_id, speed=speed, lang="en-us")
            sample_rate = sr
            wav_samples = np.asarray(wav_samples, dtype=np.float32)

            start_sec = round(cursor_samples / sample_rate, 3)
            cursor_samples += len(wav_samples)
            end_sec = round(cursor_samples / sample_rate, 3)

            turn_timings.append({
                "speaker": speaker,
                "text": raw_text,
                "start_sec": start_sec,
                "end_sec": end_sec,
            })
            chunks.append(wav_samples)

            if idx < len(dialogue) - 1:
                chunks.append(np.zeros(turn_gap_samples, dtype=np.float32))
                cursor_samples += turn_gap_samples

        chunks.append(np.zeros(tail_pad_samples, dtype=np.float32))
        full_audio = np.concatenate(chunks) if chunks else np.zeros(sample_rate, dtype=np.float32)

        wav_name = f"slide_{num:02d}.wav"
        _write_wav_16bit(ws_path / wav_name, full_audio, sample_rate)

        dur_sec = round(len(full_audio) / sample_rate, 3)
        total_audio_sec += dur_sec

        slide["audio_path"] = wav_name
        slide["audio_duration_sec"] = dur_sec
        slide["turn_timings"] = turn_timings
        slide["lipsync_envelope_30fps"] = _compute_30fps_lipsync(full_audio, sample_rate)
        print(f"[{num}/{len(slides)}] Synthesized {wav_name} ({dur_sec:.2f}s, {len(turn_timings)} turns)")

    elapsed_sec = max(1e-3, time.perf_counter() - t0)
    elapsed_ms = round(elapsed_sec * 1000, 2)
    rtf = round(elapsed_sec / max(1e-3, total_audio_sec), 3)

    timeline_path = ws_path / "timeline.json"
    timeline_path.write_text(json.dumps(slides, indent=2), encoding="utf-8")
    print(f"Done in {elapsed_ms} ms (Total Audio: {total_audio_sec:.2f}s, RTF: {rtf}x).")
    return {
        "slides_voiced": len(slides),
        "total_audio_sec": round(total_audio_sec, 2),
        "voice_ms": elapsed_ms,
        "rtf": rtf,
    }


if __name__ == "__main__":
    synthesize_audio()