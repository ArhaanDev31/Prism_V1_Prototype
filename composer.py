"""
Project Prism — Stage 5: FFmpeg / NVENC Hardware Video & Subtitle Mastering
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path


def _find_ffmpeg() -> str:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise FileNotFoundError("FFmpeg ('ffmpeg') not found in PATH. Install FFmpeg to master videos.")
    return ffmpeg_bin


def _can_encode_nvenc(ffmpeg_bin: str) -> bool:
    """Runs a 1-frame probe encode to verify NVENC actually initializes on the GPU driver."""
    probe_cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
        "-c:v", "h264_nvenc",
        "-f", "null", "-",
    ]
    proc = subprocess.run(probe_cmd, capture_output=True, text=True)
    return proc.returncode == 0


def _format_srt_ts(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def compose_final_video(
    workspace_dir: str = "workspace",
    output_video: str = "lecture.mp4",
) -> dict:
    t0 = time.perf_counter()
    ws_path = Path(workspace_dir).resolve()
    out_mp4 = Path(output_video).resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = _find_ffmpeg()
    use_nvenc = _can_encode_nvenc(ffmpeg_bin)
    v_codec_args = (
        ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p"]
        if use_nvenc
        else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    )
    encoder_name = "h264_nvenc" if use_nvenc else "libx264"
    print(f"   [Video Mastering] Active encoder: {encoder_name}")

    slides = json.loads((ws_path / "timeline.json").read_text(encoding="utf-8"))
    segment_files = []
    srt_entries = []
    srt_idx = 1
    global_offset = 0.0

    for slide in slides:
        num = slide["slide_number"]
        anim_name = slide.get("animation_path")
        audio_name = slide.get("audio_path")
        if not anim_name or not audio_name:
            raise RuntimeError(f"Missing animation or audio artifact for Slide {num}.")

        anim_path = ws_path / anim_name
        audio_path = ws_path / audio_name
        seg_path = ws_path / f"seg_{num:02d}.mp4"

        intro_sec = float(slide.get("anim_metrics", {}).get("board_intro_sec", 0.0))
        audio_dur = float(slide.get("audio_duration_sec", 0.0))
        total_seg_dur = round(intro_sec + audio_dur + 0.15, 3)
        pad_dur = round(total_seg_dur + 2.0, 2)
        delay_ms = int(round(intro_sec * 1000))

        filter_complex = (
            f"[0:v]tpad=stop_mode=clone:stop_duration={pad_dur},trim=duration={total_seg_dur},setpts=PTS-STARTPTS[v];"
            f"[1:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={total_seg_dur}[a]"
        )

        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(anim_path),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            *v_codec_args,
            "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            str(seg_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed on Slide {num}:\n{proc.stderr[-1000:]}")

        segment_files.append(seg_path)

        for turn in slide.get("turn_timings", []):
            start_abs = global_offset + intro_sec + float(turn["start_sec"])
            end_abs = global_offset + intro_sec + float(turn["end_sec"])
            speaker_tag = "Professor" if turn["speaker"] == "teacher" else "Student"
            srt_entries.append(
                f"{srt_idx}\n"
                f"{_format_srt_ts(start_abs)} --> {_format_srt_ts(end_abs)}\n"
                f"[{speaker_tag}] {turn['text']}\n"
            )
            srt_idx += 1

        global_offset += total_seg_dur
        print(f"[{num}/{len(slides)}] Mastered segment {seg_path.name} ({total_seg_dur:.2f}s via {encoder_name})")

    concat_list = ws_path / "concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{seg.as_posix()}'" for seg in segment_files) + "\n",
        encoding="utf-8",
    )

    concat_proc = subprocess.run(
        [
            ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(out_mp4),
        ],
        capture_output=True,
        text=True,
    )
    if concat_proc.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed:\n{concat_proc.stderr[-1000:]}")

    srt_path = out_mp4.with_suffix(".srt")
    srt_path.write_text("\n".join(srt_entries), encoding="utf-8")

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    print(f"Done in {elapsed_ms} ms. Final video saved to {out_mp4} (Total: {global_offset:.2f}s)")
    return {
        "output_video": str(out_mp4),
        "srt_subtitles": str(srt_path),
        "total_duration_sec": round(global_offset, 2),
        "encoder": encoder_name,
        "compose_ms": elapsed_ms,
    }


if __name__ == "__main__":
    compose_final_video(workspace_dir="workspace_unit2", output_video="unit2_lecture.mp4")