"""
Project Prism — End-to-End 5-Stage Offline Multimodal Lecture Synthesis Pipeline
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import argparse
import json
import time
from pathlib import Path

from extractor import run_extraction
from narrator import generate_scripts
from voice import synthesize_audio
from animator import build_animations
from composer import compose_final_video


def run_pipeline(
    input_file: str,
    mode: str = "lecture",
    workspace_dir: str = "workspace",
    output_video: str = "lecture.mp4",
    vlm_model: str = "qwen2.5vl:3b",
) -> dict:
    t0 = time.perf_counter()
    pptx_path = Path(input_file).resolve()
    ws_path = Path(workspace_dir).resolve()
    ws_path.mkdir(parents=True, exist_ok=True)

    print(f"=== Project Prism ({mode.upper()} mode) ===")
    print(f"Input Deck : {pptx_path}")
    print(f"Workspace  : {ws_path}")
    print(f"VLM Model  : {vlm_model}\n")

    print("--- Stage 1/5: Slide Ingestion & Telemetry ---")
    ext_stats = run_extraction(str(pptx_path), str(ws_path))

    print("\n--- Stage 2/5: Socratic VLM Dialogue Synthesis ---")
    nar_stats = generate_scripts(str(ws_path), model_name=vlm_model, mode=mode)

    print("\n--- Stage 3/5: CPU Neural Speech & Lip-Sync Envelope ---")
    voice_stats = synthesize_audio(str(ws_path))

    print("\n--- Stage 4/5: Neuro-Symbolic Smartboard Rendering ---")
    anim_stats = build_animations(str(ws_path), mode=mode)

    print("\n--- Stage 5/5: Hardware Video & Subtitle Mastering ---")
    comp_stats = compose_final_video(str(ws_path), output_video)

    total_sec = round(time.perf_counter() - t0, 2)
    benchmark = {
        "input_file": pptx_path.name,
        "mode": mode,
        "vlm_model": vlm_model,
        "api_cost_usd": 0.0,
        "total_pipeline_sec": total_sec,
        "stage_1_extraction": ext_stats,
        "stage_2_narration": nar_stats,
        "stage_3_voice": voice_stats,
        "stage_4_animation": anim_stats,
        "stage_5_composition": comp_stats,
    }

    bench_path = ws_path / "benchmark.json"
    bench_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    print("\n=== Prism Pipeline Complete ===")
    print(f"Output Video : {comp_stats['output_video']} ({comp_stats['total_duration_sec']}s)")
    print(f"Subtitles    : {comp_stats['srt_subtitles']}")
    print(f"Benchmark    : {bench_path} (Total Wall Time: {total_sec}s, API Cost: $0.00)")
    return benchmark


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Project Prism Offline Lecture Synthesizer")
    parser.add_argument("-i", "--input", required=True, help="Path to .pptx, .ppt, or .pdf lecture deck")
    parser.add_argument("-m", "--mode", default="lecture", choices=["lecture", "reel"], help="Output format")
    parser.add_argument("-w", "--workspace", default="workspace", help="Working directory for intermediate artifacts")
    parser.add_argument("-o", "--output", default="lecture.mp4", help="Output MP4 filename")
    parser.add_argument("--model", default="qwen2.5vl:3b", help="Ollama VLM model name")
    args = parser.parse_args()

    run_pipeline(
        input_file=args.input,
        mode=args.mode,
        workspace_dir=args.workspace,
        output_video=args.output,
        vlm_model=args.model,
    )