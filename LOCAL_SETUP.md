# Local AI Setup (Windows)

This version runs the vision-language model locally through Ollama. Canvas crops and screen captures are sent only to the Ollama server on your own machine (`localhost`) unless you deliberately change `OLLAMA_BASE_URL`.

## 1. Install Ollama

Download and install Ollama for Windows from:

https://ollama.com/download/windows

After installation, open **PowerShell** or **Command Prompt**.

## 2. Download a local vision model

Recommended starting point:

```powershell
ollama pull qwen3-vl:4b
```

Approximate model download sizes in Ollama:

- `qwen3-vl:2b` — about 1.9 GB — lowest hardware requirement
- `qwen3-vl:4b` — about 3.3 GB — recommended starting point
- `qwen3-vl:8b` — about 6.1 GB — better quality if your laptop has enough RAM/VRAM

Test it:

```powershell
ollama run qwen3-vl:4b
```

Type `hello`, confirm it replies, then enter `/bye`.

Ollama normally serves its local API at `http://localhost:11434` automatically.

## 3. Create the Python environment

From this project folder:

```powershell
conda create -n circle-ask python=3.11 -y
conda activate circle-ask
pip install -r requirements.txt
```

You can use `python -m venv .venv` instead of Conda if you prefer.

## 4. Configure the model

Copy `.env.example` to `.env`:

```powershell
copy .env.example .env
```

Default:

```env
OLLAMA_MODEL=qwen3-vl:4b
```

If the 4B model is too slow, change it to:

```env
OLLAMA_MODEL=qwen3-vl:2b
```

If your laptop is powerful enough:

```env
OLLAMA_MODEL=qwen3-vl:8b
```

Then download the matching model with `ollama pull ...`.

## 5. Run Circle & Ask

```powershell
python main.py
```

Or double-click:

```text
run_windows.bat
```

## Basic workflow

### Canvas

1. Draw/write with the Pen tool.
2. Choose Select (`S`).
3. Drag a rectangle around the region you want analyzed.
4. Ask a question or leave the prompt empty.
5. The selected region is sent to your local Qwen vision model.
6. Accept, dismiss, or speak the response.

### Laptop screen analysis

1. Put another application behind Circle & Ask (Jupyter, browser, VS Code, etc.).
2. Press `Ctrl + Shift + A`.
3. Circle & Ask briefly hides itself and captures the active window behind it.
4. Ask what you want the agent to analyze.
5. Qwen3-VL analyzes the screenshot locally.

## Troubleshooting

### "Ollama is not running"

Open Ollama from the Start menu, then verify:

```powershell
ollama list
```

### "model is not downloaded"

```powershell
ollama pull qwen3-vl:4b
```

### Model is too slow / laptop gets hot

Use:

```powershell
ollama pull qwen3-vl:2b
```

and set:

```env
OLLAMA_MODEL=qwen3-vl:2b
```

### Better quality

If you have enough GPU/RAM:

```powershell
ollama pull qwen3-vl:8b
```

Then change `.env` to `OLLAMA_MODEL=qwen3-vl:8b`.

## Privacy note

The application uses the local Ollama HTTP endpoint by default. No Gemini/Claude/OpenAI API key is required for this version. Screen captures can still contain sensitive information, so only analyze windows you are comfortable processing locally and be careful if you later configure Ollama to use a non-local URL.
