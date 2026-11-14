import json
import re
import time
from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL_PATH = "models/kokoro-v1.0.onnx"
VOICES_PATH = "models/voices-v1.0.bin"

# Clear academic voices in Kokoro v1.0:
# "am_michael" / "am_fenrir" (US Male) | "bm_george" (UK Male) | "af_heart" (US Female)
DEFAULT_VOICE = "am_michael"


def clean_for_tts(text: str) -> str:
    """Strips markdown symbols or formatting artifacts before synthesis."""
    text = re.sub(r"[*_#`~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_voiceovers(workspace_dir: str = "workspace", voice: str = DEFAULT_VOICE) -> None:
    ws_path = Path(workspace_dir).resolve()
    scripts_path = ws_path / "scripts.json"
    slides = json.loads(scripts_path.read_text(encoding="utf-8"))

    print("Loading local Kokoro-82M ONNX model...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)

    timeline = []

    for slide in slides:
        num = slide["slide_number"]
        clean_script = clean_for_tts(slide["narration_script"])
        audio_filename = f"audio_{num:02d}.wav"
        audio_path = ws_path / audio_filename

        print(f"[{num}/{len(slides)}] Synthesizing offline audio for Slide {num}...")
        t0 = time.perf_counter()
        samples, sample_rate = kokoro.create(clean_script, voice=voice, speed=1.0, lang="en-us")
        synth_time = round(time.perf_counter() - t0, 3)

        sf.write(str(audio_path), samples, sample_rate)
        duration = round(len(samples) / sample_rate, 3)
        rtf = round(synth_time / duration, 4) if duration > 0 else 0.0

        slide["audio_path"] = audio_filename
        slide["duration_sec"] = duration
        slide["tts_engine"] = "kokoro-82m-onnx"
        slide["tts_synth_sec"] = synth_time
        slide["tts_rtf"] = rtf
        timeline.append(slide)

        print(f"   -> Saved {audio_filename} ({duration}s audio in {synth_time}s | RTF: {rtf})")

    out_path = ws_path / "timeline.json"
    out_path.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    print(f"Done. Offline timeline manifest saved to {out_path}")


if __name__ == "__main__":
    build_voiceovers()