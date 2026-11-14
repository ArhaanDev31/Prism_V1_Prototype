import argparse
import importlib
import inspect
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from animator import build_animations
from composer import render_lecture
from narrator import generate_scripts
from voice import build_voiceovers


def get_gpu_telemetry() -> dict:
    """Queries nvidia-smi for GPU name and current VRAM usage in MB."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"gpu": "unavailable", "vram_used_mb": None, "vram_total_mb": None}
    try:
        out = subprocess.check_output(
            [nvidia_smi, "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            text=True,
        ).strip()
        name, used, total = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"gpu": name, "vram_used_mb": int(used), "vram_total_mb": int(total)}
    except Exception:
        return {"gpu": "query_failed", "vram_used_mb": None, "vram_total_mb": None}


def run_extraction_stage(pptx_path: Path, ws_path: Path) -> None:
    """Invokes extractor.py flexibly regardless of whether it exposes a function or CLI script."""
    extractor_mod = importlib.import_module("extractor")
    for fn_name in ("extract_slides", "extract_pptx", "extract_presentation", "main"):
        fn = getattr(extractor_mod, fn_name, None)
        if callable(fn):
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if len(params) >= 2:
                fn(str(pptx_path), str(ws_path))
            elif len(params) == 1:
                fn(str(pptx_path))
            else:
                fn()
            return
    subprocess.run([sys.executable, "extractor.py", str(pptx_path)], check=True)


def run_pipeline(
    input_pptx: str,
    output_mp4: str,
    workspace_dir: str = "workspace",
    vlm_model: str = "qwen2.5vl:3b",
    voice: str = "am_michael",
    skip_animations: bool = False,
) -> None:
    pptx_path = Path(input_pptx).resolve()
    if not pptx_path.exists():
        raise FileNotFoundError(f"Input presentation not found: {pptx_path}")

    ws_path = Path(workspace_dir).resolve()
    ws_path.mkdir(parents=True, exist_ok=True)

    # Keep sample.pptx synced if extractor.py defaults to reading sample.pptx
    default_deck = Path("sample.pptx").resolve()
    if pptx_path != default_deck:
        shutil.copy2(pptx_path, default_deck)

    benchmark = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_deck": pptx_path.name,
        "output_video": Path(output_mp4).name,
        "config": {
            "vlm_model": vlm_model,
            "tts_engine": "kokoro-82m-onnx",
            "tts_voice": voice,
            "manim_enabled": not skip_animations,
        },
        "hardware_baseline": get_gpu_telemetry(),
        "stages": {},
    }

    pipeline_t0 = time.perf_counter()

    # Stage 1: Slide Extraction
    print("\n=== [Stage 1/5] Slide Extraction ===")
    t0 = time.perf_counter()
    run_extraction_stage(pptx_path, ws_path)
    benchmark["stages"]["1_extraction"] = {
        "latency_sec": round(time.perf_counter() - t0, 3),
        "telemetry": get_gpu_telemetry(),
    }

    # Stage 2: Local Multimodal Narration
    print("\n=== [Stage 2/5] Local VLM Narration ===")
    t0 = time.perf_counter()
    generate_scripts(workspace_dir=str(ws_path), model_name=vlm_model)
    benchmark["stages"]["2_narration"] = {
        "latency_sec": round(time.perf_counter() - t0, 3),
        "telemetry": get_gpu_telemetry(),
    }

    # Stage 3: Offline Neural TTS
    print("\n=== [Stage 3/5] Offline Neural TTS ===")
    t0 = time.perf_counter()
    build_voiceovers(workspace_dir=str(ws_path), voice=voice)
    benchmark["stages"]["3_voice_synthesis"] = {
        "latency_sec": round(time.perf_counter() - t0, 3),
        "telemetry": get_gpu_telemetry(),
    }

    # Stage 4: Programmatic 2D/3D Manim Animations
    print("\n=== [Stage 4/5] Programmatic Manim Animations ===")
    t0 = time.perf_counter()
    if skip_animations:
        print("Skipping Manim synthesis (--skip-animations enabled).")
        status = "skipped"
    else:
        build_animations(workspace_dir=str(ws_path))
        status = "completed"
    benchmark["stages"]["4_manim_animation"] = {
        "status": status,
        "latency_sec": round(time.perf_counter() - t0, 3),
        "telemetry": get_gpu_telemetry(),
    }

    # Stage 5: FFmpeg Video & Subtitle Compositing
    print("\n=== [Stage 5/5] Video & Subtitle Compositing ===")
    t0 = time.perf_counter()
    render_lecture(workspace_dir=str(ws_path), output_file=output_mp4)
    benchmark["stages"]["5_compositing"] = {
        "latency_sec": round(time.perf_counter() - t0, 3),
        "telemetry": get_gpu_telemetry(),
    }

    # Aggregate slide & audio statistics for paper evaluation
    timeline_path = ws_path / "timeline.json"
    if timeline_path.exists():
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        total_audio_sec = round(sum(s.get("duration_sec", 0.0) for s in timeline), 3)
        avg_rtf = round(
            sum(s.get("tts_rtf", 0.0) for s in timeline) / max(len(timeline), 1), 4
        )
        animated_count = sum(1 for s in timeline if s.get("animation_path"))
        benchmark["summary"] = {
            "slide_count": len(timeline),
            "animated_slides": animated_count,
            "total_lecture_audio_sec": total_audio_sec,
            "mean_tts_rtf": avg_rtf,
            "total_pipeline_latency_sec": round(time.perf_counter() - pipeline_t0, 3),
        }

    bench_path = ws_path / "benchmark.json"
    bench_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    print(f"\nPipeline complete. Benchmark telemetry saved to {bench_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prism: 100% Offline Multimodal Lecture Generator")
    parser.add_argument("-i", "--input", default="sample.pptx", help="Path to input .pptx deck")
    parser.add_argument("-o", "--output", default="final_lecture.mp4", help="Path to output .mp4 video")
    parser.add_argument("-w", "--workspace", default="workspace", help="Intermediate workspace directory")
    parser.add_argument("--vlm", default="qwen2.5vl:3b", help="Ollama vision model name")
    parser.add_argument("--voice", default="am_michael", help="Kokoro-82M speaker voice ID")
    parser.add_argument("--skip-animations", action="store_true", help="Run baseline ablation without Manim")
    args = parser.parse_args()

    run_pipeline(
        input_pptx=args.input,
        output_mp4=args.output,
        workspace_dir=args.workspace,
        vlm_model=args.vlm,
        voice=args.voice,
        skip_animations=args.skip_animations,
    )