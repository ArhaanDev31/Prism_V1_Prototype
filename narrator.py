"""
Project Prism — Stage 2: Socratic VLM Dialogue Synthesis (Fault-Tolerant Batch Edition)
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import json
import re
import time
from pathlib import Path
import ollama

LECTURE_PROMPT = """
You are scripting a natural, human-sounding engineering conversation between two characters:
- "teacher": A warm, sharp university professor explaining concepts intuitively (uses natural transitions like "Right, so...", "Think of it this way...", "Good catch—").
- "student": A curious first-year student asking genuine, concise clarifying questions (uses natural openers like "Wait—so why...", "Hold on, does that mean...", "Oh, so if...").

Output ONLY valid JSON matching this schema:
{
  "slide_summary": "One sentence summarizing this slide.",
  "visual_focus": "What diagram, table, code block, or equation should be highlighted on the board.",
  "dialogue": [
    {"speaker": "teacher", "emotion": "explaining", "text": "..."},
    {"speaker": "student", "emotion": "curious", "text": "..."},
    {"speaker": "teacher", "emotion": "aha", "text": "..."}
  ]
}

STRICT RULES:
1. NEVER make the teacher ask a question and then have the student repeat it. Each turn must move the conversation forward.
2. Stay 100% faithful to the slide facts—never invent contradictory claims.
3. Write for the ear: use contractions ("it's", "that's", "doesn't", "we're") and short, spoken clauses.
4. Plain spoken words ONLY inside "text" (no markdown, no asterisks, no stage directions, no underscores, no code brackets, no raw newlines).
5. Total words across all turns: 65 to 105 words (3 to 4 crisp turns).
"""

REEL_PROMPT = """
You are scripting a fast, engaging 35-second vertical educational Reel between:
- "student": Curious student opening with a punchy, relatable doubt.
- "teacher": Sharp professor giving a clear visual explanation and memorable takeaway.

Output ONLY valid JSON matching this schema:
{
  "slide_summary": "One sentence summary.",
  "visual_focus": "Key circuit, code snippet, table, or formula to highlight.",
  "dialogue": [
    {"speaker": "student", "emotion": "curious", "text": "..."},
    {"speaker": "teacher", "emotion": "explaining", "text": "..."},
    {"speaker": "teacher", "emotion": "aha", "text": "..."}
  ]
}

STRICT RULES:
1. Use natural contractions ("why's", "doesn't", "here's") and plain spoken words ONLY.
2. Total words across all turns: 45 to 70 words.
"""

SPARSE_SLIDE_PROMPT = """
This slide is a brief title, section divider, or closing slide.
Output ONLY valid JSON with a single crisp 12-to-22 word spoken line from the "teacher" introducing or wrapping up the topic naturally:
{
  "slide_summary": "One sentence summary.",
  "visual_focus": "Slide title banner",
  "dialogue": [
    {"speaker": "teacher", "emotion": "explaining", "text": "..."}
  ]
}
"""

UNICODE_REPLACEMENTS = {
    "→": " leads to ",
    "⇒": " implies ",
    "≤": " less than or equal to ",
    "≥": " greater than or equal to ",
    "≠": " not equal to ",
    "×": " times ",
    "Ω": " ohms ",
    "μ": " micro ",
    "–": "-",
    "—": ", ",
}


def _sanitize_for_tts(text: str) -> str:
    for sym, word in UNICODE_REPLACEMENTS.items():
        text = text.replace(sym, word)
    text = re.sub(r"\*+|_+|`+", "", text)
    text = re.sub(r"\[.*?\]|\(.*?\)", "", text)
    text = text.replace("->", " leads to ").replace("=>", " means ")
    return " ".join(text.split()).strip()


def _parse_vlm_json(raw_text: str) -> dict:
    """Strips markdown fences and control characters before parsing JSON."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
    # Replace raw unescaped control chars inside strings
    cleaned = re.sub(r"[\x00-\x1f]+", " ", cleaned)
    return json.loads(cleaned)


def _fallback_dialogue(slide: dict) -> dict:
    """Deterministic backup script if the VLM fails JSON formatting after 3 retries."""
    title = _sanitize_for_tts(slide.get("title") or "this topic")
    bullets = " ".join(slide.get("content", [])[:2])
    snippet = _sanitize_for_tts(bullets)[:220]
    line = (
        f"Let's look closely at {title}. {snippet}"
        if snippet
        else f"Now let's examine {title} shown here on the board."
    )
    return {
        "slide_summary": title,
        "visual_focus": title,
        "dialogue": [{"speaker": "teacher", "emotion": "explaining", "text": line}],
    }


def generate_scripts(
    workspace_dir: str = "workspace",
    model_name: str = "qwen2.5vl:3b",
    mode: str = "lecture",
) -> dict:
    t0 = time.perf_counter()
    ws_path = Path(workspace_dir).resolve()
    slides = json.loads((ws_path / "slides.json").read_text(encoding="utf-8"))
    out_path = ws_path / "scripts.json"

    # Resume from checkpoint if scripts.json already has completed slides
    completed_map = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            for item in existing:
                if item.get("dialogue"):
                    completed_map[item["slide_number"]] = item
        except Exception:
            completed_map = {}

    narrated_slides = []
    prev_summary = "None (opening slide)."

    for slide in slides:
        num = slide["slide_number"]
        if num in completed_map:
            saved = completed_map[num]
            narrated_slides.append(saved)
            prev_summary = saved.get("title", prev_summary)
            print(f"[{num}/{len(slides)}] Resumed Slide {num} from checkpoint.")
            continue

        img_path = ws_path / slide["image_path"]
        metrics = slide.get("metrics", {})
        is_sparse = (
            metrics.get("word_count", 0) < 15
            and metrics.get("picture_count", 0) == 0
            and metrics.get("table_count", 0) == 0
        )

        if is_sparse:
            system_prompt = SPARSE_SLIDE_PROMPT
        else:
            system_prompt = REEL_PROMPT if mode == "reel" else LECTURE_PROMPT

        # Cap extracted text passed to VLM to 1,200 chars so dense slides never bloat context
        body_blob = "\n".join(slide["content"])[:1200]
        prompt = (
            f"Slide {num} of {len(slides)}\n"
            f"Previous Slide Context: {prev_summary}\n"
            f"Title: {slide['title']}\n"
            f"Extracted Text/Tables:\n{body_blob}\n"
            f"Speaker Notes: {slide['speaker_notes'][:400]}\n"
        )

        tag = "divider/title" if is_sparse else mode
        print(f"[{num}/{len(slides)}] Generating {tag} script for Slide {num}...")

        parsed = None
        for attempt in range(1, 4):
            try:
                response = ollama.chat(
                    model=model_name,
                    format="json",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt, "images": [str(img_path)]},
                    ],
                    options={
                        "temperature": 0.35 if attempt == 1 else 0.15,
                        "num_ctx": 4096,
                        "num_predict": 650,
                    },
                )
                parsed = _parse_vlm_json(response["message"]["content"])
                if parsed.get("dialogue"):
                    break
            except Exception as err:
                print(f"   [Retry {attempt}/3] JSON glitch on Slide {num}: {err}")

        if not parsed or not parsed.get("dialogue"):
            print(f"   [Fallback] Using deterministic slide narration for Slide {num}.")
            parsed = _fallback_dialogue(slide)

        cleaned_dialogue = []
        for turn in parsed.get("dialogue", []):
            clean_text = _sanitize_for_tts(turn.get("text", ""))
            if clean_text:
                cleaned_dialogue.append({
                    "speaker": turn.get("speaker", "teacher").lower(),
                    "emotion": turn.get("emotion", "explaining").lower(),
                    "text": clean_text,
                })

        if not cleaned_dialogue:
            cleaned_dialogue = _fallback_dialogue(slide)["dialogue"]

        prev_summary = parsed.get("slide_summary", slide["title"])
        slide["visual_focus"] = parsed.get("visual_focus", "")
        slide["dialogue"] = cleaned_dialogue
        slide["narration_script"] = " ".join(t["text"] for t in cleaned_dialogue)
        narrated_slides.append(slide)

        # Save incremental checkpoint after every slide
        out_path.write_text(json.dumps(narrated_slides, indent=2), encoding="utf-8")

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    print(f"Done in {elapsed_ms} ms. Dialogue scripts saved to {out_path}")
    return {"mode": mode, "slides_narrated": len(narrated_slides), "narration_ms": elapsed_ms}


if __name__ == "__main__":
    generate_scripts(mode="lecture")