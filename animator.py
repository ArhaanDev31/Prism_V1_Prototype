"""
Project Prism — Stage 4: Neuro-Symbolic Scene Graph & Deterministic Manim Compiler
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path
import ollama

CODE_MODEL = "qwen2.5-coder:7b"

SCENE_GRAPH_PROMPT = """
You are a visual diagram planner for an engineering lecture Smartboard.
Given a slide's title, visual focus, and extracted content, output ONLY valid JSON matching this exact schema:
{
  "layout": "circuit_stack" | "equation_cards" | "concept_cards",
  "banner_title": "Short clean slide heading (max 7 words)",
  "banner_subtitle": "Optional subtitle or key equation/syntax (max 10 words)",
  "nodes": [
    {"label": "Step / Block 1", "sublabel": "Short detail", "color": "#38bdf8"},
    {"label": "Step / Block 2", "sublabel": "Short detail", "color": "#22c55e"},
    {"label": "Step / Block 3", "sublabel": "Short detail", "color": "#f59e0b"}
  ],
  "takeaways": [
    "Concise key point 1 (max 10 words)",
    "Concise key point 2 (max 10 words)"
  ]
}

Rules:
1. Use "circuit_stack" when the slide describes a sequential pipeline, memory layout, or vertical network (3 to 5 nodes).
2. Use "equation_cards" when the slide features a formula or syntax rule (put it in "banner_subtitle" and 2-3 short points in "takeaways").
3. Use "concept_cards" for bullet summaries (2 to 3 crisp items in "takeaways", leave "nodes" empty).
4. Plain ASCII text only (no LaTeX backslashes, no raw newlines). Keep labels concise so they fit cleanly inside cards.
"""

FALLBACK_BOARD_CODE = '''
from manim import *

class BoardScene(Scene):
    def construct(self):
        self.camera.background_color = "#0f172a"
        mode = __PRISM_MODE__
        max_w = 7.0 if mode == "reel" else 11.6
        max_h = 5.4 if mode == "reel" else 4.25
        target_pos = UP * 3.1 if mode == "reel" else UP * 1.05

        slide_img = ImageMobject(__PRISM_SLIDE_IMG__)
        if slide_img.width > max_w:
            slide_img.scale_to_fit_width(max_w)
        if slide_img.height > max_h:
            slide_img.scale_to_fit_height(max_h)
        slide_img.move_to(target_pos)
        self.play(FadeIn(slide_img), run_time=0.8)
'''

SCENE_WRAPPER_TEMPLATE = '''
import json
import math
import textwrap
from pathlib import Path

class PrismScene(BoardScene):
    def construct(self):
        mode = __PRISM_MODE__
        turn_timings = __PRISM_TURN_TIMINGS__
        lipsync = __PRISM_LIPSYNC__
        meta_path = Path(__PRISM_META_PATH__)
        fallback_img_path = __PRISM_SLIDE_IMG__

        if mode == "reel":
            self.camera.frame_width = 8.0
            self.camera.frame_height = 14.22

        max_w = 7.1 if mode == "reel" else 11.8
        max_h = 5.6 if mode == "reel" else 4.35
        target_pos = UP * 3.1 if mode == "reel" else UP * 1.05

        board_frame = RoundedRectangle(
            width=max_w + 0.35,
            height=max_h + 0.35,
            corner_radius=0.18,
            color="#334155",
            stroke_width=2.5,
            fill_color="#020617",
            fill_opacity=0.55,
        ).move_to(target_pos)
        self.add(board_frame)

        super().construct()
        board_intro_sec = round(float(self.renderer.time), 3)
        meta_path.write_text(json.dumps({"board_intro_sec": board_intro_sec}), encoding="utf-8")

        if len(self.mobjects) <= 1:
            slide_img = ImageMobject(fallback_img_path)
            if slide_img.width > max_w - 0.2:
                slide_img.scale_to_fit_width(max_w - 0.2)
            if slide_img.height > max_h - 0.2:
                slide_img.scale_to_fit_height(max_h - 0.2)
            slide_img.move_to(target_pos)
            self.add(slide_img)

        if turn_timings:
            self._run_synced_dialogue(mode, turn_timings, lipsync)

    def _build_character(self, role: str, name: str, accent: str, scale: float = 1.0):
        halo = Circle(
            radius=1.05,
            color=accent,
            stroke_width=4,
            stroke_opacity=0.35,
            fill_color=accent,
            fill_opacity=0.10,
        )
        torso = RoundedRectangle(
            width=1.35,
            height=0.68,
            corner_radius=0.32,
            color=accent,
            fill_color=accent,
            fill_opacity=0.88,
            stroke_width=2,
        ).move_to(DOWN * 0.56)

        head = Circle(
            radius=0.46,
            color="#fde68a" if role == "teacher" else "#fed7aa",
            fill_color="#fde68a" if role == "teacher" else "#fed7aa",
            fill_opacity=1.0,
            stroke_color=accent,
            stroke_width=3,
        ).move_to(UP * 0.14)

        if role == "teacher":
            hair = Arc(
                radius=0.48,
                start_angle=0.15 * PI,
                angle=0.7 * PI,
                color="#1e293b",
                stroke_width=11,
            ).move_to(head.get_center() + UP * 0.16)
            glass_l = RoundedRectangle(
                width=0.23, height=0.14, corner_radius=0.04, color="#0f172a", stroke_width=2.5
            ).move_to(head.get_center() + LEFT * 0.15 + UP * 0.05)
            glass_r = RoundedRectangle(
                width=0.23, height=0.14, corner_radius=0.04, color="#0f172a", stroke_width=2.5
            ).move_to(head.get_center() + RIGHT * 0.15 + UP * 0.05)
            bridge = Line(glass_l.get_right(), glass_r.get_left(), color="#0f172a", stroke_width=2.5)
            accessory = VGroup(hair, glass_l, glass_r, bridge)
        else:
            cap = Arc(
                radius=0.48,
                start_angle=0.05 * PI,
                angle=0.9 * PI,
                color="#7c3aed",
                stroke_width=12,
            ).move_to(head.get_center() + UP * 0.17)
            visor = Line(
                head.get_center() + LEFT * 0.44 + UP * 0.19,
                head.get_center() + RIGHT * 0.16 + UP * 0.19,
                color="#5b21b6",
                stroke_width=7,
            )
            accessory = VGroup(cap, visor)

        eye_l = Dot(head.get_center() + LEFT * 0.15 + UP * 0.05, radius=0.05, color="#0f172a")
        eye_r = Dot(head.get_center() + RIGHT * 0.15 + UP * 0.05, radius=0.05, color="#0f172a")

        mouth = Ellipse(
            width=0.25,
            height=0.05,
            color="#7f1d1d",
            fill_color="#450a0a",
            fill_opacity=1.0,
            stroke_width=2,
        ).move_to(head.get_center() + DOWN * 0.17)

        badge = Text(name, font_size=19, weight=BOLD, color=accent).next_to(torso, DOWN, buff=0.12)
        rig = VGroup(halo, torso, head, accessory, eye_l, eye_r, mouth, badge).scale(scale)
        return rig, halo, head, mouth, eye_l, eye_r

    def _run_synced_dialogue(self, mode: str, turn_timings: list, lipsync: list):
        t_rig, t_halo, t_head, t_mouth, t_el, t_er = self._build_character(
            "teacher", "Professor", "#38bdf8", scale=0.92 if mode == "lecture" else 1.08
        )
        s_rig, s_halo, s_head, s_mouth, s_el, s_er = self._build_character(
            "student", "Student", "#a78bfa", scale=0.92 if mode == "lecture" else 1.08
        )

        if mode == "reel":
            t_rig.move_to(DOWN * 2.1 + LEFT * 2.1)
            s_rig.move_to(DOWN * 2.1 + RIGHT * 2.1)
            cap_center = DOWN * 4.8
            wrap_cols = 34
            cap_font = 24
        else:
            t_rig.to_corner(DL, buff=0.35)
            s_rig.to_corner(DR, buff=0.35)
            cap_center = DOWN * 2.95
            wrap_cols = 62
            cap_font = 21

        self.add(t_rig, s_rig)

        clock = {"t": 0.0}
        t_base_y = t_head.get_center()[1]
        s_base_y = s_head.get_center()[1]

        def animate_characters(mob, dt):
            clock["t"] += dt
            cur_t = clock["t"]
            frame_idx = min(len(lipsync) - 1, int(cur_t * 30)) if lipsync else -1
            amp = lipsync[frame_idx] if frame_idx >= 0 else 0.0

            active = None
            for turn in turn_timings:
                if turn["start_sec"] <= cur_t <= turn["end_sec"]:
                    active = turn["speaker"]
                    break

            if active == "teacher":
                t_halo.set_stroke(opacity=0.95).set_fill(opacity=0.20)
                s_halo.set_stroke(opacity=0.20).set_fill(opacity=0.04)
                t_open = 0.045 + 0.24 * amp
                s_open = 0.04
                t_head.set_y(t_base_y + 0.025 * math.sin(cur_t * 14))
                s_head.set_y(s_base_y)
            elif active == "student":
                s_halo.set_stroke(opacity=0.95).set_fill(opacity=0.20)
                t_halo.set_stroke(opacity=0.20).set_fill(opacity=0.04)
                s_open = 0.045 + 0.24 * amp
                t_open = 0.04
                s_head.set_y(s_base_y + 0.025 * math.sin(cur_t * 15))
                t_head.set_y(t_base_y)
            else:
                t_halo.set_stroke(opacity=0.30).set_fill(opacity=0.06)
                s_halo.set_stroke(opacity=0.30).set_fill(opacity=0.06)
                t_open = 0.04
                s_open = 0.04

            t_mouth.become(
                Ellipse(
                    width=0.24 + 0.06 * (amp if active == "teacher" else 0.0),
                    height=t_open,
                    color="#7f1d1d",
                    fill_color="#450a0a",
                    fill_opacity=1.0,
                    stroke_width=2,
                ).move_to(t_head.get_center() + DOWN * 0.17)
            )
            s_mouth.become(
                Ellipse(
                    width=0.24 + 0.06 * (amp if active == "student" else 0.0),
                    height=s_open,
                    color="#7f1d1d",
                    fill_color="#450a0a",
                    fill_opacity=1.0,
                    stroke_width=2,
                ).move_to(s_head.get_center() + DOWN * 0.17)
            )

            blink = (cur_t % 3.2) < 0.12
            eye_h = 0.015 if blink else 0.10
            for eye in (t_el, t_er, s_el, s_er):
                eye.stretch_to_fit_height(eye_h)

        t_rig.add_updater(animate_characters)

        cursor = 0.0
        for turn in turn_timings:
            gap = max(0.0, turn["start_sec"] - cursor)
            if gap > 0:
                self.wait(gap)

            turn_dur = max(0.25, turn["end_sec"] - turn["start_sec"])
            is_prof = turn["speaker"] == "teacher"
            label = "Professor: " if is_prof else "Student: "
            accent = "#38bdf8" if is_prof else "#c4b5fd"
            wrapped = textwrap.fill(label + turn["text"], width=wrap_cols)

            cap_txt = Text(wrapped, font_size=cap_font, line_spacing=1.15, color=WHITE)
            pill = RoundedRectangle(
                width=cap_txt.width + 0.5,
                height=cap_txt.height + 0.32,
                corner_radius=0.16,
                color=accent,
                stroke_width=2,
                fill_color="#020617",
                fill_opacity=0.90,
            )
            cap_group = VGroup(pill, cap_txt).move_to(cap_center)

            self.add(cap_group)
            self.wait(turn_dur)
            self.remove(cap_group)
            cursor = turn["end_sec"]
'''


def _parse_sg_json(raw_text: str) -> dict:
    """Strips markdown fences and raw control chars before parsing Scene Graph JSON."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
    cleaned = re.sub(r"[\x00-\x1f]+", " ", cleaned)
    return json.loads(cleaned)


def _build_deterministic_table_scene(slide: dict, mode: str) -> str:
    title_str = slide.get("title") or "Comparison Table"
    raw_table = slide["tables"][0]
    max_cols = max(len(r) for r in raw_table)
    clean_rows = []
    for row in raw_table:
        padded = [str(c).replace("\n", " ").strip() or "-" for c in row] + ["-"] * (max_cols - len(row))
        clean_rows.append(padded)

    return f'''
from manim import *

class BoardScene(Scene):
    def construct(self):
        self.camera.background_color = "#0f172a"
        mode = {mode!r}
        max_w = 6.8 if mode == "reel" else 11.4
        max_h = 5.2 if mode == "reel" else 4.15
        target_pos = UP * 3.1 if mode == "reel" else UP * 1.05

        header = Text({title_str!r}, font_size=28, weight=BOLD, color="#38bdf8")
        table = Table(
            {clean_rows!r},
            include_outer_lines=True,
            line_config={{"stroke_width": 2, "color": "#475569"}},
            element_to_mobject=lambda s: Text(str(s), font_size=20, color=WHITE),
            h_buff=0.8,
            v_buff=0.42,
        )
        for cell in table.get_rows()[0]:
            cell.set_color("#38bdf8")
        grp = VGroup(header, table).arrange(DOWN, buff=0.35)
        if grp.width > max_w:
            grp.scale_to_fit_width(max_w)
        if grp.height > max_h:
            grp.scale_to_fit_height(max_h)
        grp.move_to(target_pos)

        self.play(FadeIn(header), run_time=0.6)
        self.play(Create(table), run_time=1.8)
'''


def _compile_scene_graph_to_manim(sg: dict, slide: dict, mode: str) -> str:
    layout = sg.get("layout", "concept_cards")
    banner_title = str(sg.get("banner_title") or slide.get("title") or "Concept Overview")[:70]
    banner_sub = str(sg.get("banner_subtitle") or "")[:90]
    nodes = sg.get("nodes", [])[:5]
    takeaways = [str(t)[:95] for t in sg.get("takeaways", [])[:3] if str(t).strip()]

    if layout == "circuit_stack" and len(nodes) >= 2:
        return f'''
from manim import *

class BoardScene(Scene):
    def construct(self):
        self.camera.background_color = "#0f172a"
        mode = {mode!r}
        max_w = 6.8 if mode == "reel" else 11.4
        max_h = 5.2 if mode == "reel" else 4.15
        target_pos = UP * 3.1 if mode == "reel" else UP * 1.05

        title = Text({banner_title!r}, font_size=26, weight=BOLD, color="#38bdf8")
        nodes_data = {nodes!r}
        blocks = VGroup()
        for item in nodes_data:
            accent = item.get("color") or "#38bdf8"
            lbl = Text(str(item.get("label", ""))[:45], font_size=21, weight=BOLD, color=WHITE)
            sub = str(item.get("sublabel", "")).strip()[:65]
            txt_grp = VGroup(lbl, Text(sub, font_size=16, color="#cbd5e1")).arrange(DOWN, buff=0.06) if sub else VGroup(lbl)
            box = RoundedRectangle(
                width=max(txt_grp.width + 0.7, 5.2),
                height=txt_grp.height + 0.30,
                corner_radius=0.14,
                color=accent,
                stroke_width=2.5,
                fill_color=accent,
                fill_opacity=0.18,
            )
            txt_grp.move_to(box.get_center())
            blocks.add(VGroup(box, txt_grp))

        blocks.arrange(DOWN, buff=0.42)
        arrows = VGroup(*[
            Arrow(
                blocks[i].get_bottom(),
                blocks[i + 1].get_top(),
                buff=0.04,
                stroke_width=3,
                max_tip_length_to_length_ratio=0.22,
                color="#94a3b8",
            )
            for i in range(len(blocks) - 1)
        ])
        diagram = VGroup(blocks, arrows)
        full = VGroup(title, diagram).arrange(DOWN, buff=0.35)

        if full.width > max_w:
            full.scale_to_fit_width(max_w)
        if full.height > max_h:
            full.scale_to_fit_height(max_h)
        full.move_to(target_pos)

        self.play(FadeIn(title), run_time=0.5)
        for idx, blk in enumerate(blocks):
            self.play(FadeIn(blk), run_time=0.32)
            if idx < len(arrows):
                self.play(Create(arrows[idx]), run_time=0.18)
'''

    return f'''
from manim import *

class BoardScene(Scene):
    def construct(self):
        self.camera.background_color = "#0f172a"
        mode = {mode!r}
        max_w = 6.8 if mode == "reel" else 11.4
        max_h = 5.2 if mode == "reel" else 4.15
        target_pos = UP * 3.1 if mode == "reel" else UP * 1.05

        t = Text({banner_title!r}, font_size=28, weight=BOLD, color="#38bdf8")
        sub_str = {banner_sub!r}.strip()
        banner_items = [t]
        if sub_str:
            banner_items.append(Text(sub_str, font_size=24, weight=BOLD, color="#f8fafc"))
        banner_txt = VGroup(*banner_items).arrange(DOWN, buff=0.16)
        banner_box = RoundedRectangle(
            width=max(banner_txt.width + 0.9, 8.2),
            height=banner_txt.height + 0.45,
            corner_radius=0.16,
            color="#38bdf8",
            stroke_width=2.5,
            fill_color="#0f172a",
            fill_opacity=0.95,
        )
        banner_txt.move_to(banner_box.get_center())
        banner = VGroup(banner_box, banner_txt)

        cards_data = {takeaways!r}
        cards = VGroup()
        for idx, line in enumerate(cards_data):
            c_txt = Text(str(line), font_size=21, color="#e2e8f0")
            c_box = RoundedRectangle(
                width=max(c_txt.width + 0.8, 8.2),
                height=c_txt.height + 0.34,
                corner_radius=0.12,
                color="#6366f1" if idx % 2 == 0 else "#0ea5e9",
                stroke_width=2,
                fill_color="#1e293b",
                fill_opacity=0.75,
            )
            c_txt.move_to(c_box.get_center())
            cards.add(VGroup(c_box, c_txt))

        if len(cards) > 0:
            cards.arrange(DOWN, buff=0.26)
            full = VGroup(banner, cards).arrange(DOWN, buff=0.40)
            if full.width > max_w:
                full.scale_to_fit_width(max_w)
            if full.height > max_h:
                full.scale_to_fit_height(max_h)
            full.move_to(target_pos)

            self.play(FadeIn(banner), run_time=0.8)
            for card in cards:
                self.play(FadeIn(card), run_time=0.45)
        else:
            if banner.width > max_w:
                banner.scale_to_fit_width(max_w)
            if banner.height > max_h:
                banner.scale_to_fit_height(max_h)
            banner.move_to(target_pos)
            self.play(FadeIn(banner), run_time=1.0)
'''


def _run_manim_compile(
    board_code: str,
    slide: dict,
    ws_path: Path,
    mode: str,
    script_file: Path,
    meta_file: Path,
    final_mp4: Path,
) -> tuple[bool, str]:
    slide_img_path = str((ws_path / slide["image_path"]).resolve())
    wrapper_code = (
        SCENE_WRAPPER_TEMPLATE
        .replace("__PRISM_MODE__", repr(mode))
        .replace("__PRISM_TURN_TIMINGS__", repr(slide.get("turn_timings", [])))
        .replace("__PRISM_LIPSYNC__", repr(slide.get("lipsync_envelope_30fps", [])))
        .replace("__PRISM_META_PATH__", repr(str(meta_file)))
        .replace("__PRISM_SLIDE_IMG__", repr(slide_img_path))
    )
    script_file.write_text(f"{board_code}\n\n{wrapper_code}\n", encoding="utf-8")

    num = slide["slide_number"]
    media_dir = ws_path / "manim_out"
    resolution_flags = ["-r", "1080,1920"] if mode == "reel" else ["-qh"]
    cmd = [
        sys.executable, "-m", "manim",
        *resolution_flags,
        "--fps", "30",
        "--media_dir", str(media_dir),
        "-o", f"anim_{num:02d}.mp4",
        str(script_file),
        "PrismScene",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        rendered = list(media_dir.rglob(f"anim_{num:02d}.mp4"))
        if rendered:
            rendered[0].replace(final_mp4)
            return True, ""
    return False, (proc.stderr or proc.stdout)[-1200:]


def _render_smartboard_png(
    slide: dict,
    ws_path: Path,
    mode: str,
    script_file: Path,
    meta_file: Path,
    final_mp4: Path,
    t0: float,
    reason: str,
) -> tuple[str | None, dict]:
    slide_img_path = str((ws_path / slide["image_path"]).resolve())
    fallback_code = (
        FALLBACK_BOARD_CODE
        .replace("__PRISM_MODE__", repr(mode))
        .replace("__PRISM_SLIDE_IMG__", repr(slide_img_path))
    )
    ok, _ = _run_manim_compile(fallback_code, slide, ws_path, mode, script_file, meta_file, final_mp4)
    if ok:
        board_intro_sec = float(json.loads(meta_file.read_text(encoding="utf-8")).get("board_intro_sec", 0.0)) if meta_file.exists() else 0.0
        return final_mp4.name, {
            "layout_type": reason,
            "compile_attempts": 1,
            "compile_success": True,
            "board_intro_sec": board_intro_sec,
            "anim_render_sec": round(time.perf_counter() - t0, 2),
        }
    return None, {"layout_type": reason, "compile_success": False, "board_intro_sec": 0.0, "anim_render_sec": round(time.perf_counter() - t0, 2)}


def generate_and_render_animation(
    slide: dict,
    ws_path: Path,
    mode: str = "lecture",
) -> tuple[str | None, dict]:
    num = slide["slide_number"]
    script_file = ws_path / f"manim_scene_{num:02d}.py"
    meta_file = ws_path / f"anim_meta_{num:02d}.json"
    final_mp4 = ws_path / f"anim_{num:02d}.mp4"
    metrics = slide.get("metrics", {})
    t0 = time.perf_counter()

    # Visual Slide Guard: preserve embedded diagrams, schematics, or code screenshots
    if metrics.get("picture_count", 0) >= 1 and metrics.get("word_count", 0) < 60:
        print(f"   [Visual Slide Guard] Preserving embedded figure on Smartboard for Slide {num}...")
        return _render_smartboard_png(slide, ws_path, mode, script_file, meta_file, final_mp4, t0, "smartboard_embedded_figure")

    # Deterministic Table Guard
    if slide.get("tables"):
        raw_table = slide["tables"][0]
        row_count = len(raw_table)
        col_count = max((len(r) for r in raw_table), default=0)
        if 1 <= row_count <= 6 and col_count <= 5:
            print(f"   [Deterministic Table] Building exact {row_count}x{col_count} Manim Table for Slide {num}...")
            table_code = _build_deterministic_table_scene(slide, mode)
            ok, _ = _run_manim_compile(table_code, slide, ws_path, mode, script_file, meta_file, final_mp4)
            if ok:
                board_intro_sec = float(json.loads(meta_file.read_text(encoding="utf-8")).get("board_intro_sec", 0.0)) if meta_file.exists() else 0.0
                return final_mp4.name, {
                    "layout_type": "deterministic_table",
                    "compile_attempts": 1,
                    "compile_success": True,
                    "board_intro_sec": board_intro_sec,
                    "anim_render_sec": round(time.perf_counter() - t0, 2),
                }
        else:
            print(f"   [Oversized Table Guard] Rendering {row_count}x{col_count} table via Smartboard PNG for Slide {num}...")
            return _render_smartboard_png(slide, ws_path, mode, script_file, meta_file, final_mp4, t0, "smartboard_large_table")

    # Sparse Title / Divider Slide Guard
    if metrics.get("word_count", 0) < 15:
        sg = {"layout": "concept_cards", "banner_title": slide.get("title") or "Overview", "banner_subtitle": "", "nodes": [], "takeaways": []}
        compiled_code = _compile_scene_graph_to_manim(sg, slide, mode)
        ok, _ = _run_manim_compile(compiled_code, slide, ws_path, mode, script_file, meta_file, final_mp4)
        if ok:
            board_intro_sec = float(json.loads(meta_file.read_text(encoding="utf-8")).get("board_intro_sec", 0.0)) if meta_file.exists() else 0.0
            return final_mp4.name, {
                "layout_type": "title_banner",
                "compile_attempts": 1,
                "compile_success": True,
                "board_intro_sec": board_intro_sec,
                "anim_render_sec": round(time.perf_counter() - t0, 2),
            }

    # Default Path: Neuro-Symbolic Scene Graph -> Deterministic Manim Layout Compiler
    print(f"   [Scene Graph] Planning visual layout with {CODE_MODEL} for Slide {num}...")
    prompt = (
        f"Slide Title: {slide['title']}\n"
        f"Visual Focus: {slide.get('visual_focus', '')}\n"
        f"Extracted Content:\n" + "\n".join(slide["content"])[:1200]
    )
    try:
        response = ollama.chat(
            model=CODE_MODEL,
            format="json",
            messages=[
                {"role": "system", "content": SCENE_GRAPH_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.1, "num_ctx": 4096, "num_predict": 550},
        )
        sg = _parse_sg_json(response["message"]["content"])
        layout_type = sg.get("layout", "concept_cards")
        compiled_code = _compile_scene_graph_to_manim(sg, slide, mode)

        ok, _ = _run_manim_compile(compiled_code, slide, ws_path, mode, script_file, meta_file, final_mp4)
        if ok:
            board_intro_sec = float(json.loads(meta_file.read_text(encoding="utf-8")).get("board_intro_sec", 0.0)) if meta_file.exists() else 0.0
            return final_mp4.name, {
                "layout_type": layout_type,
                "compile_attempts": 1,
                "compile_success": True,
                "board_intro_sec": board_intro_sec,
                "anim_render_sec": round(time.perf_counter() - t0, 2),
            }
    except Exception as err:
        print(f"   [Scene Graph Guard] Falling back to Smartboard PNG on Slide {num}: {err}")

    print(f"   [Smartboard Fallback] Rendering Slide {num} PNG on Smartboard...")
    return _render_smartboard_png(slide, ws_path, mode, script_file, meta_file, final_mp4, t0, "smartboard_slide_stage")


def build_animations(workspace_dir: str = "workspace", mode: str = "lecture") -> dict:
    ws_path = Path(workspace_dir).resolve()
    timeline_path = ws_path / "timeline.json"
    slides = json.loads(timeline_path.read_text(encoding="utf-8"))

    success_count = 0
    for slide in slides:
        num = slide["slide_number"]
        final_mp4 = ws_path / f"anim_{num:02d}.mp4"
        meta_file = ws_path / f"anim_meta_{num:02d}.json"

        # Checkpoint resume: skip already rendered slide animations if re-running
        if final_mp4.exists() and meta_file.exists() and slide.get("anim_metrics", {}).get("compile_success"):
            success_count += 1
            print(f"[{num}/{len(slides)}] Resumed {final_mp4.name} from checkpoint.")
            continue

        print(f"[{num}/{len(slides)}] Synthesizing {mode} stage for Slide {num} ({slide['title']})...")
        anim_file, metrics = generate_and_render_animation(slide, ws_path, mode=mode)
        slide["animation_path"] = anim_file
        slide["anim_metrics"] = metrics
        if anim_file:
            success_count += 1
            print(f"   -> Saved {anim_file} ({metrics['layout_type']}, {metrics['anim_render_sec']}s)")
            timeline_path.write_text(json.dumps(slides, indent=2), encoding="utf-8")

    timeline_path.write_text(json.dumps(slides, indent=2), encoding="utf-8")
    compile_rate = round((success_count / len(slides)) * 100, 1) if slides else 100.0
    print(f"Done. Stage Success Rate: {compile_rate}% ({success_count}/{len(slides)})")
    return {"animated_slides": len(slides), "compile_success_rate_pct": compile_rate}


if __name__ == "__main__":
    build_animations(mode="lecture")