import json
import subprocess
import shutil
from pathlib import Path
import fitz  # PyMuPDF
from pptx import Presentation


def extract_slide_text(pptx_path: Path) -> list[dict]:
    """Extracts titles, bullet points, tables, and speaker notes per slide."""
    prs = Presentation(str(pptx_path))
    slides_data = []

    for idx, slide in enumerate(prs.slides, start=1):
        title = ""
        body_items = []

        if slide.shapes.title and slide.shapes.title.text.strip():
            title = slide.shapes.title.text.strip()

        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame:
                text = "\n".join(
                    p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()
                )
                if text:
                    body_items.append(text)
            elif shape.has_table:
                rows = [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in shape.table.rows
                ]
                body_items.append("\n".join(rows))

        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()

        slides_data.append({
            "slide_number": idx,
            "title": title,
            "content": body_items,
            "speaker_notes": notes,
            "image_path": f"slide_{idx:02d}.png"
        })

    return slides_data


def render_slide_images(pptx_path: Path, out_dir: Path) -> None:
    """Converts PPTX to PDF via LibreOffice headless, then renders 1080p PNGs."""
    soffice_bin = (
        shutil.which("soffice")
        or shutil.which("libreoffice")
        or (r"C:\Program Files\LibreOffice\program\soffice.exe" if Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() else None)
    )

    subprocess.run(
        [soffice_bin, "--headless", "--convert-to", "pdf", str(pptx_path), "--outdir", str(out_dir)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    pdf_path = out_dir / f"{pptx_path.stem}.pdf"
    doc = fitz.open(str(pdf_path))

    for idx, page in enumerate(doc, start=1):
        # Scale to ~1920px width for clean 1080p output
        zoom = 1920 / page.rect.width
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(out_dir / f"slide_{idx:02d}.png"))

    doc.close()
    pdf_path.unlink(missing_ok=True)


def run_extraction(pptx_file: str, output_dir: str = "workspace") -> None:
    pptx_path = Path(pptx_file).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/2] Extracting text and notes from {pptx_path.name}...")
    slides_data = extract_slide_text(pptx_path)

    print(f"[2/2] Rendering {len(slides_data)} slides to 1080p PNGs...")
    render_slide_images(pptx_path, out_dir)

    manifest_path = out_dir / "slides.json"
    manifest_path.write_text(json.dumps(slides_data, indent=2), encoding="utf-8")
    print(f"Done. Output saved to {out_dir}")


if __name__ == "__main__":
    # Drop any sample .pptx file in your folder to test
    run_extraction("sample.pptx")