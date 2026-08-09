# Agentic AI Smart Workspace — Python Prototype

A software-first prototype of an **AI-native visual workspace**. It ports the core interaction from the original HTML canvas into a Python/PySide6 desktop app and adds a second mode for analyzing the active laptop screen.

## What works

- Freehand ink canvas with mouse or stylus
- Pressure-aware strokes when Qt receives tablet pressure
- Pen, eraser, color, brush size
- Region selection
- Ask a multimodal AI about only the selected canvas region
- Accept an AI response back into the canvas as a visible AI note
- Dismiss responses and retain interaction history
- Undo/redo
- Save structured stroke/session history as JSON
- Export the canvas to PNG
- Capture and analyze the current/foreground laptop window
- Local/offline text-to-speech for AI responses
- API key stored locally in `.env`, never embedded in the UI source

## AI provider

The default provider is Google's Gemini Developer API using `gemini-2.5-flash-lite` because Google currently offers a free tier for supported Gemini API models. Free-tier limits and model availability can change.

The AI layer is isolated in `src/agentic_workspace/ai/gemini_client.py`, so another provider or a fully local VLM can replace it later.

## 1. Create environment

Windows PowerShell / Anaconda Prompt:

```bash
cd agentic_ai_workspace
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

With Conda:

```bash
conda create -n smart-workspace python=3.11 -y
conda activate smart-workspace
pip install -r requirements.txt
```

## 2. Get the free API key

Create a Gemini API key in Google AI Studio.

Copy:

```text
.env.example
```

to:

```text
.env
```

and set:

```text
GEMINI_API_KEY=YOUR_REAL_KEY
```

Never commit `.env` to GitHub.

## 3. Run

```bash
python main.py
```

## Main workflow

### Canvas

1. Draw a problem, equation, diagram, or notes.
2. Click **Select** or press `S`.
3. Drag a rectangle around a region.
4. Ask a question such as `What am I missing?`.
5. The selected region is sent to Gemini Vision.
6. The response appears in the AI assistant panel.
7. **Accept on canvas**, **Dismiss**, or **Speak**.

### Laptop screen analysis

Press:

```text
Ctrl + Shift + A
```

The app captures the current foreground window on Windows (full screen fallback elsewhere), sends the image plus your question to Gemini, and returns workflow-aware analysis.

This is the beginning of the Cursor-like desktop perception path.

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
             Gemini VLM
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

## Project structure

```text
agentic_ai_workspace/
├── main.py
├── requirements.txt
├── .env.example
├── reference_canvas.html
├── data/
│   └── sessions/
└── src/agentic_workspace/
    ├── app.py
    ├── models.py
    ├── ai/
    │   ├── gemini_client.py
    │   └── worker.py
    ├── canvas/
    │   └── canvas_widget.py
    ├── screen/
    │   └── capture.py
    ├── storage/
    │   └── session.py
    ├── ui/
    │   └── ask_dialog.py
    └── voice/
        └── tts.py
```

## Important design decisions

### Structured ink, not just screenshots

Every stroke is preserved as a list of timestamped points. This gives future versions access to **how** the user writes, not only the final pixels.

### Explicit AI before proactive AI

V0 asks the AI only when the user selects a region or invokes screen analysis. Do not attempt continuous intervention until the perception and workspace-state layers are reliable.

### Provider abstraction

Do not couple the project to Gemini permanently. Later options include:

- local Qwen-VL / Gemma vision model
- Ollama-compatible multimodal model
- Hugging Face Inference Providers
- another hosted VLM

### Privacy

Screen screenshots and selected canvas images can contain sensitive information. Only analyze content the user explicitly asks to send. A future version should add local redaction and local models.

## Next milestones

### V0.2 — Desktop timeline

Track:

- foreground-window changes
- screenshots only after meaningful visual change
- timestamps
- task/session boundaries

### V0.3 — Structured screen understanding

Combine:

```text
pixels + active-window metadata + OCR/UI Automation
```

instead of relying only on screenshot pixels.

### V0.4 — Spatial desktop overlay

Ask the VLM for a target region and display arrows/highlights directly over the user's current application.

### V0.5 — Voice input

Add push-to-talk so the user can say:

> Explain this.

> Show me where.

> What changed?

### V1 — Workspace memory

Represent current task, visual objects, recent actions, accepted AI notes, and application transitions in a persistent structured state.

### Later — physical mat

Only after the desktop agent is useful should the same architecture receive:

```text
EMR pen + touch + paper-like display + physical smart mat
```

The physical device becomes another I/O surface for the same agent.

## Security

- Never hardcode API keys.
- `.env` is ignored by Git.
- Do not enable automatic clicking/typing until an explicit permission model exists.
- Treat screen capture as sensitive user data.

## Status

Research/prototype software. Not production-ready.
