# GifteQChat

A light AI agent with a chat web interface. No framework. Works with any OpenAI-compatible API.

Features: chat, web search, RAG on your documents, long-term memory, a sandboxed Python
code interpreter, specialist sub-agents with task delegation, and MCP tool servers.

## Getting started (Windows + VS Code)

**0. Install the two prerequisites** (skip any you already have)
- [Git for Windows](https://git-scm.com/download/win): keep all installer defaults
- [Python](https://www.python.org/downloads/): on the first installer screen, **tick "Add python.exe to PATH"** before clicking Install. This is the #1 thing people forget, and without it none of the commands below will work.

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

You'll know it worked when the terminal prompt starts with `(venv)`. VS Code may also pop up "Select Python Interpreter"; pick the one inside `venv`.

**4. Install dependencies**

```powershell
pip install -r requirements.txt
```

**5. Copy the config file**

```powershell
copy .env.example .env
```
(or just right-click `.env.example` in the VS Code file explorer → Copy → Paste → rename the copy to `.env`)

It defaults to the local, no-key provider (Ollama), so no editing is needed for the next step. Want to use Groq/OpenAI/OpenRouter instead? Open `.env` and see [Providers](#providers) below.

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

If Windows Defender Firewall pops up, click **Allow access**. Open http://localhost:8080 in your browser. That's it.

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

> On Debian/Ubuntu, if pip refuses with `externally-managed-environment`, you skipped the venv step above; either go back and create one, or run `pip install -r requirements.txt --break-system-packages`.

</details>

## Setup reference

Full `.env` example (default, local Ollama; see [Getting started](#getting-started-windows--vs-code) above):

```
AI_AGENT_PROVIDER=ollama
AI_AGENT_KEY=
AI_AGENT_PORT=8080
```

To switch provider, change `AI_AGENT_PROVIDER` and set `AI_AGENT_KEY`, e.g.:

```
AI_AGENT_PROVIDER=groq
AI_AGENT_KEY=gsk_...
AI_AGENT_MODEL=qwen/qwen3.6-27b
```

### Providers
- **Local, no key needed (default)**: install [Ollama](https://ollama.com/download) ([Windows](https://ollama.com/download/windows) runs in the background, tray icon), then in a terminal run `ollama pull llama3.2` (~2GB, one-time download). Runs fully offline after the model is downloaded. Slower than Groq on a laptop with no dedicated GPU, but free and private.
- **Groq (free, fast)**: key at https://console.groq.com → `AI_AGENT_KEY=...` + `AI_AGENT_PROVIDER=groq`
- **OpenRouter (free models)**: key at https://openrouter.ai → `AI_AGENT_KEY=...` + `AI_AGENT_PROVIDER=openrouter`
- **OpenAI**: `AI_AGENT_PROVIDER=openai` + `AI_AGENT_KEY=sk-...`

Groq models you can use in `AI_AGENT_MODEL`: `qwen/qwen3.6-27b` (default), `openai/gpt-oss-20b`, `openai/gpt-oss-120b`. Check the current list at https://console.groq.com/docs/models. Groq retires older models over time.

## RAG (ask your documents)

1. In the sidebar, click **+ Upload a document** (max 5)
2. Tick **Ask my documents**
3. Questions are answered from your documents

Formats: `.txt .md .csv .json .log .py .docx .pdf`.
Documents are saved in `data/documents.json` and survive restarts (this file is gitignored, so it stays local).

## Code interpreter (`run_python`)

The agent can write and execute Python in an isolated sandbox: math, data processing,
text analysis, verifying logic. Each run gets a throwaway interpreter outside the project
directory with a timeout (default 15 s, max 60 s) and, on Linux/macOS, CPU + memory limits.
Results come back as stdout/stderr; runaway code is killed automatically.

**Charts are displayed in the chat**: ask for a plot and the agent saves it as PNG
(matplotlib, headless Agg backend); images appear inside the answer bubble.

> The sandbox is best-effort (no network isolation). Don't point it at hostile code in production.

## Markdown & LaTeX rendering

Replies are rendered as Markdown (bold, italics, inline code, code blocks, headings,
bullet lists), and math as LaTeX via KaTeX (`$f'(x) = 2x$` inline, `$$...$$` display).
All content is HTML-escaped before rendering, so neither model nor user input can inject XSS.
KaTeX loads from a CDN; offline it simply shows the raw notation.

## Sub-agents (`delegate_task`)

For complex multi-part requests the orchestrator delegates to specialists:

| Role | Tools | Purpose |
|---|---|---|
| `researcher` | web_search | web research, summarized report |
| `doc_analyst` | search_documents | answers strictly from your documents |
| `analyst` | run_python | calculations and code execution |

Each sub-agent has its own system prompt, a restricted tool allow-list, and its own step
budget. Sub-agents cannot delegate themselves, so recursion is impossible by construction.

## MCP tool servers

The agent can load external tools from [MCP](https://modelcontextprotocol.io) servers over stdio.
Copy the example config and restart:

```bash
cp mcp.example.json data/mcp.json   # then edit to taste
python3 webapp.py                   # connected servers appear in the sidebar
```

Config format (`data/mcp.json`):

```json
{
  "servers": {
    "fetch": { "command": "uvx", "args": ["mcp-server-fetch"], "call_timeout": 30 }
  }
}
```

- Every tool a server exposes becomes available to the agent as `mcp_<server>_<tool>`
- A server that fails to start is skipped and shown in red in the sidebar; it never crashes the app
- No `data/mcp.json`? The feature simply stays off

## Other ways to run it

```bash
python3 agent.py          # command-line chat (Windows: python agent.py)
python3 test_system.py    # run the tests (Windows: python test_system.py)
```

## Troubleshooting

- **Code changes don't appear**: the web UI lives in memory, so **restart `webapp.py`**
  (Ctrl+C, then relaunch) after editing any project file.
- **"Chart created" but nothing displayed**: check matplotlib is installed in the *same*
  Python environment you launch the server with (`python3 -m pip show matplotlib`),
  then ask again: "show me the plot".

## Add a tool

1. Declare its spec in `BASE_TOOLS` (JSON schema, agent.py)
2. Add the handler in `call_tool()` (agent.py)

MCP servers add tools without touching the code. See [MCP tool servers](#mcp-tool-servers).

## Use as a library

```python
from agent import run
print(run("search the web for the latest AI news"))
```