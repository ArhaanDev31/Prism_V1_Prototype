import json
import re
import subprocess
import sys
from pathlib import Path
import ollama

CODE_MODEL = "qwen2.5-coder:7b"

MANIM_SYSTEM_PROMPT = """
You are an expert mathematical and engineering animator using Manim Community Edition (v0.18+).
Given a lecture slide's title, content/tables, narration script, and target duration in seconds, write a complete, runnable Python script using Manim.

CHOOSE THE RIGHT VISUAL LAYOUT:
1. Comparison Table / Matrix (qualitative text across categories, e.g., Logic Families):
   - Use Manim's built-in Table class with element_to_mobject=lambda s: Text(str(s), font_size=22) and include_outer_lines=True.
   - Keep cell strings concise (max 3-4 words per cell; summarize long parentheticals cleanly).
   - Animate row-by-row (FadeIn each row sequentially) paced across the target duration.
2. Numerical Data / Benchmarks:
   - Use BarChart(..., axis_config={"include_numbers": False}) with short 1-2 word x-axis labels and Text value labels above each bar.
3. Equations, Waveforms, or Block Diagrams:
   - Use Axes(..., axis_config={"include_numbers": False}), Arrow, Rectangle, and Text arranged strictly via VGroup(...).arrange(RIGHT, buff=0.6) or .next_to().

STRICT ANTI-COLLISION & NO-LATEX RULES:
1. Output ONLY valid Python code inside a single triple-backtick python block.
2. Define ONE scene class named PrismScene(Scene).
3. NEVER use Tex, MathTex, or DecimalNumber (LaTeX is NOT installed). Always use Text(...).
4. NEVER position multiple text elements using hardcoded (x, y) coordinates. Always use Table, VGroup.arrange(), or .next_to().
5. MANDATORY SCALING GUARDRAIL: Before animating your main content group (main_group), ALWAYS run:
   if main_group.width > 12.5:
       main_group.scale_to_fit_width(12.5)
   if main_group.height > 5.8:
       main_group.scale_to_fit_height(5.8)
   main_group.move_to(DOWN * 0.3)
6. Place the slide title at the top (title.to_edge(UP, buff=0.4)), scaling it if title.width > 12.5.
7. Set self.camera.background_color = "#0f172a" and pace animations with self.wait(...) steps so the total runtime roughly matches the target duration.
"""


def extract_python_code(raw: str) -> str:
    match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
    return match.group(1).strip() if match else raw.strip()


def generate_and_render_animation(slide: dict, ws_path: Path, max_retries: int = 3) -> str | None:
    num = slide["slide_number"]
    target_sec = slide.get("duration_sec", 10.0)
    script_file = ws_path / f"manim_scene_{num:02d}.py"
    final_mp4 = ws_path / f"anim_{num:02d}.mp4"

    user_prompt = (
        f"Slide Title: {slide['title']}\n"
        f"Slide Content: {' | '.join(slide['content'])}\n"
        f"Spoken Narration: {slide['narration_script']}\n"
        f"Target Animation Duration: ~{target_sec} seconds.\n\n"
        "Write the collision-free Manim PrismScene script:"
    )

    messages = [
        {"role": "system", "content": MANIM_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(1, max_retries + 1):
        print(f"   [Attempt {attempt}/{max_retries}] Generating Manim script for Slide {num}...")
        response = ollama.chat(
            model=CODE_MODEL,
            messages=messages,
            options={"temperature": 0.2},
        )
        code = extract_python_code(response["message"]["content"])
        script_file.write_text(code, encoding="utf-8")

        media_dir = ws_path / "manim_out"
        cmd = [
            sys.executable,
            "-m",
            "manim",
            "-qh",
            "--fps",
            "30",
            "--media_dir",
            str(media_dir),
            "-o",
            f"anim_{num:02d}.mp4",
            str(script_file),
            "PrismScene",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            rendered_files = list(media_dir.rglob(f"anim_{num:02d}.mp4"))
            if rendered_files:
                rendered_files[0].replace(final_mp4)
                return final_mp4.name

        error_tail = (proc.stderr or proc.stdout)[-1200:]
        print(f"   [Render Error] Feeding traceback back to {CODE_MODEL}...")
        messages.append({"role": "assistant", "content": f"```python\n{code}\n```"})
        messages.append({
            "role": "user",
            "content": f"Manim failed with this error:\n{error_tail}\nFix the Python code and output the full corrected script:",
        })

    print(f"   [Fallback] Could not render animation for Slide {num}; will keep original slide.")
    return None


def build_animations(workspace_dir: str = "workspace") -> None:
    ws_path = Path(workspace_dir).resolve()
    timeline_path = ws_path / "timeline.json"
    slides = json.loads(timeline_path.read_text(encoding="utf-8"))

    for slide in slides:
        num = slide["slide_number"]
        if num == 1:
            slide["animation_path"] = None
            continue

        print(f"[{num}/{len(slides)}] Synthesizing 2D/3D animation for Slide {num} ({slide['title']})...")
        anim_file = generate_and_render_animation(slide, ws_path)
        slide["animation_path"] = anim_file
        if anim_file:
            print(f"   -> Saved {anim_file}")

    timeline_path.write_text(json.dumps(slides, indent=2), encoding="utf-8")
    print(f"Done. Updated {timeline_path} with animation tracks.")


if __name__ == "__main__":
    build_animations()