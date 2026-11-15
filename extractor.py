"""
Project Prism — Stage 1: Multi-Format Lecture Ingestion (.pptx, .ppt, .pdf)
Copyright (c) 2026 Arhaan Sajeed Sayed. All rights reserved.
"""

import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
import fitz  # PyMuPDF
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def _find_soffice() -> str:
    soffice_bin = (
        shutil.which("soffice")
        or shutil.which("libreoffice")
        or (
            r"C:\Program Files\LibreOffice\program\soffice.exe"
            if Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists()
            else None
        )
    )
    if not soffice_bin:
        raise FileNotFoundError(
            "LibreOffice ('soffice') not found. Install LibreOffice or add it to PATH."
        )
    return soffice_bin


def _is_pdf_bytes(file_path: Path) -> bool:
    """Checks the raw file header for %PDF regardless of file extension."""
    with file_path.open("rb") as f:
        header = f.read(16)
    return b"%PDF" in header


def _iter_shapes_sorted(shapes):
    """Recursively yields non-group shapes sorted top-to-bottom, left-to-right."""
    ordered = sorted(shapes, key=lambda s: (getattr(s, "top", 0) or 0, getattr(s, "left", 0) or 0))
    for shape in ordered:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes_sorted(shape.shapes)
        else:
            yield shape


def extract_from_pdf(pdf_path: Path, out_dir: Path) -> list[dict]:
    """Extracts reading-order text, image counts, and 1080p PNGs directly from a PDF deck."""
    slides_data = []
    with fitz.open(str(pdf_path)) as doc:
        for idx, page in enumerate(doc, start=1):
            zoom = min(1920 / page.rect.width, 1080 / page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(str(out_dir / f"slide_{idx:02d}.png"))

            blocks = page.get_text("blocks", sort=True)
            text_blocks = [
                " ".join(b[4].split())
                for b in blocks
                if b[6] == 0 and b[4].strip()
            ]
            title = text_blocks[0][:120] if text_blocks else f"Slide {idx}"
            body_items = text_blocks[1:] if len(text_blocks) > 1 else []
            picture_count = len(page.get_images(full=False))
            word_count = len((title + " " + " ".join(body_items)).split())

            slides_data.append({
                "slide_number": idx,
                "title": title,
                "content": body_items,
                "tables": [],
                "speaker_notes": "",
                "image_path": f"slide_{idx:02d}.png",
                "metrics": {
                    "word_count": word_count,
                    "table_count": 0,
                    "picture_count": picture_count,
                },
            })

    return slides_data


def extract_slide_text(pptx_path: Path) -> list[dict]:
    """Extracts titles, reading-order text, structured tables, notes, and slide telemetry."""
    prs = Presentation(str(pptx_path))
    slides_data = []

    for idx, slide in enumerate(prs.slides, start=1):
        title = ""
        body_items = []
        tables = []
        picture_count = 0

        title_shape = slide.shapes.title
        if title_shape and title_shape.text.strip():
            title = title_shape.text.strip()

        for shape in _iter_shapes_sorted(slide.shapes):
            if shape == title_shape:
                continue

            if shape.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT):
                picture_count += 1

            if shape.has_text_frame:
                text = "\n".join(
                    p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()
                )
                if text:
                    body_items.append(text)
            elif shape.has_table:
                matrix = [
                    [cell.text.strip() for cell in row.cells]
                    for row in shape.table.rows
                ]
                tables.append(matrix)
                rows_str = [" | ".join(r) for r in matrix]
                body_items.append("\n".join(rows_str))

        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()

        word_count = len((title + " " + " ".join(body_items) + " " + notes).split())

        slides_data.append({
            "slide_number": idx,
            "title": title,
            "content": body_items,
            "tables": tables,
            "speaker_notes": notes,
            "image_path": f"slide_{idx:02d}.png",
            "metrics": {
                "word_count": word_count,
                "table_count": len(tables),
                "picture_count": picture_count,
            },
        })

    return slides_data


def render_slide_images(pptx_path: Path, out_dir: Path, soffice_bin: str) -> None:
    """Converts PPTX to PDF via LibreOffice headless, then renders 1080p-bounded PNGs."""
    subprocess.run(
        [soffice_bin, "--headless", "--convert-to", "pdf", str(pptx_path), "--outdir", str(out_dir)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    pdf_path = out_dir / f"{pptx_path.stem}.pdf"
    try:
        with fitz.open(str(pdf_path)) as doc:
            for idx, page in enumerate(doc, start=1):
                zoom = min(1920 / page.rect.width, 1080 / page.rect.height)
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pix.save(str(out_dir / f"slide_{idx:02d}.png"))
    finally:
        pdf_path.unlink(missing_ok=True)


def run_extraction(pptx_file: str, output_dir: str = "workspace") -> dict:
    t0 = time.perf_counter()
    input_path = Path(pptx_file).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if input_path.stat().st_size == 0:
        raise ValueError(f"'{input_path.name}' is 0 bytes (check OneDrive sync or re-download the file).")

    if input_path.suffix.lower() == ".pdf" or _is_pdf_bytes(input_path):
        print(f"[1/1] Extracting text & rendering 1080p PNGs from PDF ({input_path.name})...")
        slides_data = extract_from_pdf(input_path, out_dir)
    else:
        soffice_bin = _find_soffice()
        if not zipfile.is_zipfile(input_path):
            print(f"[0/2] Upgrading legacy {input_path.name} to .pptx via LibreOffice...")
            conv_dir = out_dir / "_converted_pptx"
            conv_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [soffice_bin, "--headless", "--convert-to", "pptx", str(input_path), "--outdir", str(conv_dir)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            input_path = conv_dir / f"{input_path.stem}.pptx"

        print(f"[1/2] Extracting text, tables, and notes from {input_path.name}...")
        slides_data = extract_slide_text(input_path)

        print(f"[2/2] Rendering {len(slides_data)} slides to PNGs...")
        render_slide_images(input_path, out_dir, soffice_bin)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    manifest_path = out_dir / "slides.json"
    manifest_path.write_text(json.dumps(slides_data, indent=2), encoding="utf-8")
    print(f"Done in {elapsed_ms} ms. Output saved to {out_dir}")

    return {"slide_count": len(slides_data), "extraction_ms": elapsed_ms}


if __name__ == "__main__":
    run_extraction("arrays.pptx")