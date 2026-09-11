# Agentic AI Smart Workspace — Python Prototype

A software-first prototype of an **AI-native visual workspace**: a freehand ink
canvas you can draw and write on, plus AI analysis of your laptop screen.
Draw a problem, circle part of it, and ask the local vision model about it —
or capture whatever app is behind the window and get workflow-aware analysis.

Long-term, this same agent architecture is meant to run on a physical smart
laptop pad (pen + touch surface). The desktop app comes first; the mat is
another I/O surface for the same agent later.

## What works

- Freehand ink canvas with mouse or stylus (pressure-aware where Qt reports it)
- Pen, eraser, color, brush size; undo/redo
- Region selection (`S`, then drag a rectangle)
- Ask the vision model about only the selected region
- Accept an AI response back into the canvas as a visible AI note, dismiss it,
  or have it spoken aloud (local/offline TTS)
- Save structured stroke/session history as JSON; export canvas to PNG
- Capture and analyze the active laptop window (`Ctrl + Shift + A`)
- Interaction history retained across the session

## AI provider: local-first

The default path runs the vision model **locally through Ollama** — canvas
crops and screen captures go to `http://localhost:11434` and nowhere else.
No API key required.

Recommended model: `qwen3-vl:4b` (~3.3 GB download) — the best size/quality
tradeoff for this workload. `qwen3-vl:2b` (~1.9 GB) if your machine is light;
`qwen3-vl:8b` (~6.1 GB) if you have RAM/VRAM to spare.

The AI layer is isolated behind a provider interface, so a hosted model
(e.g. Gemini) or a future on-device model can replace Ollama later without
touching the UI.

## Setup

### 1. Install Ollama and pull a model

Download Ollama from <https://ollama.com>, then:

```powershell
ollama pull qwen3-vl:4b
ollama run qwen3-vl:4b
```

Type `hello`, confirm it replies, then `/bye`.

### 2. Create the Python environment

```powershell
cd AgenticAI_smart_workspace_as_laptop_pad_concept
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

(Or `conda create -n smart-workspace python=3.11 -y`.)

### 3. Configure

```powershell
copy .env.example .env
```

Defaults in `.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-vl:4b
OLLAMA_TIMEOUT=180
```

If the 4B model is too slow, `ollama pull qwen3-vl:2b` and set
`OLLAMA_MODEL=qwen3-vl:2b`.

### 4. Run

```powershell
python main.py
```

or double-click `run_windows.bat`.

Smoke-test the vision path without the UI:

```powershell
python test_vision.py
```

## Main workflow

### Canvas

1. Draw a problem, equation, diagram, or notes.
2. Press `S` and drag a rectangle around a region.
3. Ask a question (or leave it empty).
4. The selected region is sent to the local vision model.
5. **Accept on canvas**, **Dismiss**, or **Speak** the response.

### Laptop screen analysis

1. Put another app (browser, VS Code, Jupyter…) behind this window.
2. Press `Ctrl + Shift + A`.
3. The app briefly hides itself, captures the active window behind it, and the
   vision model analyzes the screenshot locally.

## Repo contents

```text
├── main.py                  # entry point (expects src/agentic_workspace)
├── src/agentic_workspace/   # the PySide6 app package (push when ready)
├── reference_canvas.html    # original HTML interaction prototype
├── test_vision.py           # Ollama vision smoke test (qwen3-vl)
├── img.jpg                  # sample image for the smoke test
├── requirements.txt
├── run_windows.bat
├── .env.example             # copy to .env; never commit .env
└── data/sessions/           # saved stroke/session history (git-ignored)
```

## Architecture

```text
                 USER
                   │
          ┌────────┴────────┐
          │                 │
      Ink Canvas       Laptop Screen
          │                 │
          └────────┬────────┘
                   ↓
             Visual Context
                   ↓
            Vision Model (local)
                   ↓
            Workspace Agent
             /           \
            ↓             ↓
      Visual response    Voice
            ↓
      Accept / Dismiss
            ↓
       Session memory
```

## Important design decisions

### Structured ink, not just screenshots

Every stroke is preserved as a list of timestamped points. Future versions get
access to **how** the user writes, not only the final pixels.

### Explicit AI before proactive AI

The app asks the model only when the user selects a region or invokes screen
analysis. No continuous intervention until perception and workspace-state
layers are reliable.

### Provider abstraction

Do not couple the project to one model host. Later options: local Qwen-VL /
Gemma vision, Ollama-compatible multimodal, hosted inference providers.

### Privacy

Screenshots and canvas crops can contain sensitive information. Only analyze
content the user explicitly sends. A future version should add local redaction.

## Next milestones

- **V0.2 — Desktop timeline:** foreground-window changes, screenshots on
  meaningful visual change, timestamps, session boundaries
- **V0.3 — Structured screen understanding:** pixels + window metadata + OCR
  instead of screenshot pixels alone
- **V0.4 — Spatial overlay:** arrows/highlights over the user's current app
- **V0.5 — Voice input:** push-to-talk ("Explain this.", "What changed?")
- **V1 — Workspace memory:** persistent structured state — current task,
  visual objects, accepted AI notes, app transitions
- **Later — physical mat:** EMR pen + touch + paper-like display; the device
  becomes another I/O surface for the same agent

## Troubleshooting

**"Ollama is not running"** — start Ollama from the Start menu, verify with
`ollama list`.

**"model is not downloaded"** — `ollama pull qwen3-vl:4b`.

**Model too slow / laptop gets hot** — drop to `qwen3-vl:2b` and update
`OLLAMA_MODEL`.

**Better quality** — `qwen3-vl:8b`, if you have the RAM/VRAM.

## Security

- Never hardcode API keys; never commit `.env` (it's git-ignored — keep it
  that way).
- Do not enable automatic clicking/typing until an explicit permission model
  exists.
- Treat screen capture as sensitive user data.

## Status

Research/prototype software. Not production-ready.
