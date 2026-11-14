import json
import math
import re
import shutil
import subprocess
from pathlib import Path


def format_srt_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - math.floor(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def build_srt_captions(slides: list[dict], srt_path: Path, pad_sec: float = 0.4) -> None:
    """Generates an .srt subtitle file synced to each slide's audio runtime."""
    entries = []
    idx = 1
    cursor = 0.0

    for slide in slides:
        dur = float(slide["duration_sec"])
        text = re.sub(r"[*_#`~]", "", slide["narration_script"]).strip()
        words = text.split()

        if not words:
            cursor += dur + pad_sec
            continue

        chunk_size = 11
        chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]
        total_chars = sum(len(c) for c in chunks)

        chunk_start = cursor
        for chunk in chunks:
            weight = len(chunk) / max(total_chars, 1)
            chunk_dur = dur * weight
            chunk_end = chunk_start + chunk_dur

            entries.append(
                f"{idx}\n"
                f"{format_srt_time(chunk_start)} --> {format_srt_time(chunk_end)}\n"
                f"{chunk}\n"
            )
            idx += 1
            chunk_start = chunk_end

        cursor += dur + pad_sec

    srt_path.write_text("\n".join(entries), encoding="utf-8")


def detect_encoder(ffmpeg_bin: str) -> str:
    """Tests if h264_nvenc actually initializes on this GPU/driver; falls back to libx264."""
    test_cmd = [
        ffmpeg_bin,
        "-f", "lavfi",
        "-i", "color=c=black:s=256x256:d=0.1",
        "-c:v", "h264_nvenc",
        "-f", "null",
        "-",
    ]
    res = subprocess.run(test_cmd, capture_output=True)
    return "h264_nvenc" if res.returncode == 0 else "libx264"


def run_ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{proc.stderr[-1500:]}")


def render_lecture(workspace_dir: str = "workspace", output_file: str = "final_lecture.mp4") -> None:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("FFmpeg not found in PATH.")

    ws_path = Path(workspace_dir).resolve()
    timeline_path = ws_path / "timeline.json"
    slides = json.loads(timeline_path.read_text(encoding="utf-8"))

    encoder = detect_encoder(ffmpeg_bin)
    print(f"Using video encoder: {encoder}")

    pad_sec = 0.4
    temp_clips = []

    for slide in slides:
        num = slide["slide_number"]
        dur = float(slide["duration_sec"])
        total_clip_dur = dur + pad_sec
        fade_out_start = max(0.0, total_clip_dur - 0.35)

        img_path = ws_path / slide["image_path"]
        audio_path = ws_path / slide["audio_path"]
        anim_name = slide.get("animation_path")
        anim_path = (ws_path / anim_name) if anim_name else None
        clip_path = ws_path / f"clip_{num:02d}.mp4"

        if anim_path and anim_path.exists():
            print(f"[{num}/{len(slides)}] Compositing Manim animation for Slide {num}...")
            vf = (
                f"scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#0f172a,"
                f"fps=30,tpad=stop_mode=clone:stop_duration=30,"
                f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out_start:.2f}:d=0.35"
            )
            input_args = ["-i", str(anim_path)]
        else:
            print(f"[{num}/{len(slides)}] Rendering Ken Burns motion slide for Slide {num}...")
            frames = math.ceil(total_clip_dur * 30)
            vf = (
                f"scale=3840:2160,"
                f"zoompan=z='min(zoom+0.0004,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30,"
                f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out_start:.2f}:d=0.35"
            )
            # Single image input without -loop 1 since zoompan generates `frames` output frames
            input_args = ["-i", str(img_path)]

        cmd = [
            ffmpeg_bin,
            "-y",
            *input_args,
            "-i", str(audio_path),
            "-vf", vf,
            "-c:v", encoder,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-af", f"apad=pad_dur={pad_sec}",
            "-t", f"{total_clip_dur:.3f}",
            str(clip_path),
        ]
        run_ffmpeg(cmd)
        temp_clips.append(clip_path)

    # 1. Concatenate segments into an intermediate raw video
    concat_file = ws_path / "concat_list.txt"
    concat_file.write_text("\n".join(f"file '{c.as_posix()}'" for c in temp_clips), encoding="utf-8")
    raw_merged = ws_path / "raw_merged.mp4"

    run_ffmpeg([
        ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(raw_merged)
    ])

    # 2. Generate and burn synced .srt subtitles into final_lecture.mp4
    srt_local = Path("subtitles.srt")
    build_srt_captions(slides, srt_local, pad_sec=pad_sec)

    out_path = Path(output_file).resolve()
    print(f"Burning synced subtitles and encoding {out_path.name}...")

    sub_style = "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H000F172A,BorderStyle=3,Outline=1,MarginV=32"
    sub_cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(raw_merged),
        "-vf", f"subtitles={srt_local.name}:force_style='{sub_style}'",
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_path),
    ]
    run_ffmpeg(sub_cmd)

    # Move subtitles.srt into workspace and clean temp clips
    srt_local.replace(ws_path / "subtitles.srt")
    for clip in temp_clips:
        clip.unlink(missing_ok=True)
    concat_file.unlink(missing_ok=True)
    raw_merged.unlink(missing_ok=True)

    print(f"Done. Final upgraded lecture saved to {out_path}")


if __name__ == "__main__":
    render_lecture()