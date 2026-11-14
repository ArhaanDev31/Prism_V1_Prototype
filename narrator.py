import json
from pathlib import Path
import ollama

SYSTEM_PROMPT = """
You are an engaging, clear university engineering professor delivering a recorded video lecture.
Given a slide's image, extracted text, and optional speaker notes, write the exact spoken narration for this single slide.

Rules:
1. Speak naturally and conversationally—explain concepts, equations, and tables clearly instead of reading bullet points verbatim.
2. Reference visual elements naturally (e.g., "Looking at the comparison table here...", "Notice the dynamic power equation...").
3. Do NOT include stage directions, markdown formatting, asterisks, or labels like "Professor:" or "[pause]". Output ONLY the raw spoken words ready for a Text-to-Speech engine.
4. Keep transitions smooth assuming slides play sequentially.
5. Target 60 to 110 words per slide so the pacing stays crisp and focused.
6. Make your videos more engaging cause your students may mostly be GEN-Z's
"""


def generate_scripts(workspace_dir: str = "workspace", model_name: str = "qwen2.5vl:3b") -> None:
    ws_path = Path(workspace_dir).resolve()
    slides_json_path = ws_path / "slides.json"
    slides = json.loads(slides_json_path.read_text(encoding="utf-8"))

    narrated_slides = []

    for slide in slides:
        num = slide["slide_number"]
        img_path = ws_path / slide["image_path"]

        prompt = (
            f"Slide {num} of {len(slides)}\n"
            f"Title: {slide['title']}\n"
            f"Extracted Text/Tables:\n" + "\n".join(slide["content"]) + "\n"
            f"Speaker Notes: {slide['speaker_notes']}\n\n"
            "Write the spoken lecture narration for this slide:"
        )

        print(f"[{num}/{len(slides)}] Generating local lecture script for Slide {num}...")
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [str(img_path)],
                },
            ],
            options={"temperature": 0.6},
        )

        script_text = response["message"]["content"].strip()
        slide["narration_script"] = script_text
        narrated_slides.append(slide)

    out_path = ws_path / "scripts.json"
    out_path.write_text(json.dumps(narrated_slides, indent=2), encoding="utf-8")
    print(f"Done. Narration scripts saved to {out_path}")


if __name__ == "__main__":
    generate_scripts()