# Prism (`V1_Prototype`)

**A 100% Offline, Air-Gapped Multimodal Lecture Synthesis Engine**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Ollama Local VLM](https://img.shields.io/badge/VLM-Qwen2.5--VL%203B-teal.svg)](https://ollama.com/)
[![TTS Kokoro-82M](https://img.shields.io/badge/TTS-Kokoro--82M%20ONNX-purple.svg)](https://github.com/thewh1teagle/kokoro-onnx)
[![Manim CE](https://img.shields.io/badge/Animations-Manim%20CE-orange.svg)](https://www.manim.community/)
[![Hardware NVENC](https://img.shields.io/badge/GPU-RTX%20NVENC%20Accelerated-76b900.svg)](https://developer.nvidia.com/nvidia-video-codec-sdk)

**Prism** converts static presentation decks (`.pptx`) into fully narrated, animated, and captioned video lectures (`.mp4`) **completely offline**. Designed for privacy-sensitive academic environments and low-connectivity edge hardware, Prism eliminates cloud API dependencies by orchestrating local Vision-Language Models (VLMs), neural ONNX speech synthesis, self-healing programmatic animations, and GPU-accelerated video compositing.

---

## System Architecture

Prism decouples lecture generation into five deterministic, reproducible stages orchestrated via a unified CLI (`prism.py`) with automated telemetry logging (`benchmark.json`):

```text
  [.pptx Deck]
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 1: Slide Extraction (extractor.py)                             │
│  • LibreOffice Headless -> PDF -> 1080p PNG rasterization (PyMuPDF)  │
│  • Structured XML text & table parsing (python-pptx)                 │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 2: Multimodal Narration (narrator.py)                          │
│  • Local Qwen2.5-VL (3B) inspects both slide PNG + extracted text    │
│  • Generates natural, pedagogical lecture scripts in timeline.json   │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 3: Offline Neural TTS (voice.py)                               │
│  • Kokoro-82M (ONNX Runtime) synthesizes 24 kHz WAV narration        │
│  • Records exact audio durations & Real-Time Factor (RTF)            │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 4: Programmatic 2D/3D Animations (animator.py)                 │
│  • Local Qwen2.5-Coder (7B) synthesizes Manim CE scenes              │
│  • Zero-LaTeX rendering + auto-scaling bounding guardrails           │
│  • Self-healing subprocess error-feedback loop (up to 3 retries)     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 5: Video & Subtitle Compositing (composer.py)                  │
│  • Hybrid routing: Manim MP4s + Ken Burns motion on static slides    │
│  • Auto-generated lower-third .srt captions + RTX NVENC encoding     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
                     [final_lecture.mp4 + benchmark.json]
```

---

## Core Engineering Highlights

* **100% Air-Gapped Execution:** Zero external API calls. All VLM inference, code generation, neural TTS, vector rendering, and H.264 encoding execute locally on consumer GPU hardware (tested on NVIDIA RTX 5050 Laptop GPU, 8 GB VRAM).
* **Zero-LaTeX Collision-Free Manim Engine:** Bypasses multi-gigabyte MiKTeX/TeX Live dependencies on Windows by enforcing native Cairo text/table primitives and programmatic canvas bounding checks (`scale_to_fit_width` / `scale_to_fit_height`) to prevent text overlap.
* **Self-Healing Code Synthesis:** `animator.py` executes generated Manim scripts in an isolated subprocess and automatically feeds stack traces back to the local LLM for autonomous patching.
* **Built-In Ablation & Benchmarking:** `prism.py` captures per-stage latency, VRAM consumption (`nvidia-smi`), and TTS Real-Time Factor (RTF) into `workspace/benchmark.json`, supporting both full multimodal runs and static baseline ablations (`--skip-animations`).

---

## Repository Structure

```text
Prism_V1_Prototype/
├── prism.py          # Unified CLI orchestrator & empirical benchmark logger
├── extractor.py      # Stage 1: .pptx to 1080p PNG + structured text extraction
├── narrator.py       # Stage 2: Local VLM pedagogical script generation
├── voice.py          # Stage 3: Kokoro-82M ONNX offline neural speech synthesis
├── animator.py       # Stage 4: Self-healing, collision-free Manim scene generator
├── composer.py       # Stage 5: FFmpeg hybrid compositing, .srt captions & NVENC
├── sample.pptx       # Sample engineering presentation deck for testing
└── .gitignore        # Excludes venv/, models/, workspace/, and rendered .mp4s
```

---

## Prerequisites & Setup

### 1. System Dependencies
* **Python 3.10+**
* **LibreOffice** (for headless `.pptx` $\rightarrow$ `.pdf` slide rendering)
* **FFmpeg** (with `h264_nvenc` support recommended; falls back to `libx264` automatically)
* **Ollama** running locally with the required models pulled:
  ```bash
  ollama pull qwen2.5vl:3b
  ollama pull qwen2.5-coder:7b
  ```

### 2. Python Environment
```bash
git clone https://github.com/ArhaanDev31/Prism_V1_Prototype.git
cd Prism_V1_Prototype

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

pip install python-pptx pymupdf ollama kokoro-onnx soundfile manim
```
*(Note: `voice.py` automatically downloads the `kokoro-v1.0.onnx` and `voices-v1.0.bin` weights into `models/` on its first run, after which the pipeline operates completely offline.)*

---

## Usage

### Full Multimodal Pipeline (with Manim 2D/3D Animations)
```bash
python prism.py --input sample.pptx --output prism_full.mp4
```

### Baseline Ablation Mode (Ken Burns Slides Only, No Manim)
```bash
python prism.py --input sample.pptx --output prism_baseline.mp4 --skip-animations
```

### CLI Options
| Flag | Default | Description |
| :--- | :--- | :--- |
| `-i`, `--input` | `sample.pptx` | Path to the input PowerPoint (`.pptx`) deck |
| `-o`, `--output` | `final_lecture.mp4` | Output video filename |
| `-w`, `--workspace` | `workspace` | Directory for intermediate frames, audio, scripts, and `benchmark.json` |
| `--vlm` | `qwen2.5vl:3b` | Local Ollama vision-language model for narration |
| `--voice` | `am_michael` | Kokoro-82M speaker voice ID |
| `--skip-animations` | `False` | Bypass Stage 4 Manim synthesis for baseline comparison |

---

## Research Roadmap (`V1_Prototype` $\rightarrow$ Publication)
- [x] Decoupled 5-stage offline multimodal pipeline
- [x] Collision-free, zero-LaTeX Manim animation engine with self-healing retries
- [x] Synced `.srt` caption generation and RTX NVENC compositing
- [x] Automated `benchmark.json` telemetry (stage latency, VRAM, TTS RTF)
- [ ] Quantitative visual-layout & OCR fidelity evaluation across multi-domain lecture decks
- [ ] IEEE / Scopus manuscript preparation
