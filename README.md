# AI Services

A light AI agent with a chat web interface. No framework. Works with any OpenAI-compatible API.

## Getting started (Windows + VS Code)

**0. Install the two prerequisites** (skip any you already have)
- [Git for Windows](https://git-scm.com/download/win) — keep all installer defaults
- [Python](https://www.python.org/downloads/) — on the first installer screen, **tick "Add python.exe to PATH"** before clicking Install. This is the #1 thing people forget, and without it none of the commands below will work.

Restart VS Code after installing these so it picks up the new PATH.

**1. Clone the repo**

Open VS Code → `Ctrl+Shift+P` → type **"Git: Clone"** → paste:
```
https://github.com/AbdelkaderYS/AI-services.git
```
Pick a folder, then click **Open** when VS Code asks. (Or via terminal: `git clone https://github.com/AbdelkaderYS/AI-services.git` then `cd AI-services`.)

**2. Open a terminal in VS Code**

Menu **Terminal → New Terminal** (or `` Ctrl+` ``). It opens PowerShell by default in the project folder.

**3. Create and activate a virtual environment**

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

> If PowerShell refuses with *"running scripts is disabled on this system"*, run this once, then retry the line above:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

You'll know it worked when the terminal prompt starts with `(venv)`. VS Code may also pop up "Select Python Interpreter" — pick the one inside `venv`.

**4. Install dependencies**

```powershell
pip install -r requirements.txt
```

**5. Copy the config file**

```powershell
copy .env.example .env
```
(or just right-click `.env.example` in the VS Code file explorer → Copy → Paste → rename the copy to `.env`)

It defaults to the local, no-key provider (Ollama) — no editing needed for the next step. Want to use Groq/OpenAI/OpenRouter instead? Open `.env` and see [Providers](#providers) below.

**6. Install Ollama and pull the model**

Download and install [Ollama for Windows](https://ollama.com/download/windows) (runs in the background, tray icon). Then in the terminal:
```powershell
ollama pull llama3.2
```
One-time download, ~2GB.

**7. Run it**

```powershell
python webapp.py
```

If Windows Defender Firewall pops up, click **Allow access**. Open http://localhost:8080 in your browser — that's it.

<details>
<summary><strong>macOS / Linux instructions</strong></summary>

```bash
git clone https://github.com/AbdelkaderYS/AI-services.git
cd AI-services
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # defaults to Ollama, no key needed
# install Ollama (https://ollama.com/download) then: ollama pull llama3.2
python3 webapp.py
```

> On Debian/Ubuntu, if pip refuses with `externally-managed-environment`, you skipped the venv step above — either go back and create one, or run `pip install -r requirements.txt --break-system-packages`.

</details>

## Setup reference

Full `.env` example (default, local Ollama — see [Getting started](#getting-started-windows--vs-code) above):

```
AI_AGENT_PROVIDER=ollama
AI_AGENT_KEY=
AI_AGENT_PORT=8080
```

To switch provider, change `AI_AGENT_PROVIDER` and set `AI_AGENT_KEY`, e.g.:

```
AI_AGENT_PROVIDER=groq
AI_AGENT_KEY=gsk_...
AI_AGENT_MODEL=openai/gpt-oss-120b
```

### Providers
- **Local, no key needed (default)**: install [Ollama](https://ollama.com/download) ([Windows](https://ollama.com/download/windows) runs in the background, tray icon), then in a terminal run `ollama pull llama3.2` (~2GB, one-time download). Runs fully offline after the model is downloaded. Slower than Groq on a laptop with no dedicated GPU, but free and private.
- **Groq (free, fast)**: key at https://console.groq.com → `AI_AGENT_KEY=...` + `AI_AGENT_PROVIDER=groq`
- **OpenRouter (free models)**: key at https://openrouter.ai → `AI_AGENT_KEY=...` + `AI_AGENT_PROVIDER=openrouter`
- **OpenAI**: `AI_AGENT_PROVIDER=openai` + `AI_AGENT_KEY=sk-...`

Groq models you can use in `AI_AGENT_MODEL`: `openai/gpt-oss-120b` (default), `openai/gpt-oss-20b` (fast), `qwen/qwen3.6-27b`. Check the current list at https://console.groq.com/docs/models — Groq retires older models over time.

## RAG (ask your documents)

1. In the sidebar, click **+ Upload a document** (max 5)
2. Tick **Ask my documents**
3. Questions are answered from your documents

Formats: `.txt .md .csv .json .log .py .docx .pdf`.
Documents are saved in `data/documents.json` and survive restarts (this file is gitignored, so it stays local).

## Other ways to run it

```bash
python3 agent.py          # command-line chat (Windows: python agent.py)
python3 test_system.py    # run the tests (Windows: python test_system.py)
```

## Add a tool

1. Declare its spec in `TOOLS` (JSON schema)
2. Add the handler in `call_tool()` (agent.py)

## Use as a library

```python
from agent import run
print(run("search the web for the latest AI news"))
```