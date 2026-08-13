# AI Services

A light AI agent with a chat web interface. No framework. Works with any OpenAI-compatible API.

## Getting started

Clone the repo:

```bash
git clone https://github.com/AbdelkaderYS/AI-services.git
cd AI-services
```

**1. Create a virtual environment (recommended)**

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

> On Debian/Ubuntu, if pip refuses with `externally-managed-environment`, you skipped the venv step above — either go back and create one, or run `pip install -r requirements.txt --break-system-packages`.

**3. Configure your API key**

```bash
cp .env.example .env
```

Edit `.env` and set `AI_AGENT_KEY` (a free key from [Groq](https://console.groq.com) takes a minute — it's the default provider). No key at all? Use `AI_AGENT_PROVIDER=ollama` instead to run fully local. See [Providers](#providers) below for all options.

**4. Run it**

```bash
python3 webapp.py
```

Open http://localhost:8080 — that's it.

## Setup reference

Full `.env` example:

```
AI_AGENT_PROVIDER=groq
AI_AGENT_KEY=gsk_...
AI_AGENT_MODEL=llama-3.3-70b-versatile
AI_AGENT_PORT=8080
```

### Providers
- **Local (recommended)**: install [Ollama](https://ollama.com), then `ollama pull llama3.2`, then `AI_AGENT_PROVIDER=ollama` (no key needed)
- **Groq (free, fast)**: key at https://console.groq.com → `AI_AGENT_KEY=...`
- **OpenRouter (free models)**: key at https://openrouter.ai → `AI_AGENT_KEY=...` + `AI_AGENT_PROVIDER=openrouter`
- **OpenAI**: `AI_AGENT_PROVIDER=openai` + `AI_AGENT_KEY=sk-...`

Groq models you can use in `AI_AGENT_MODEL`: `llama-3.3-70b-versatile` (default), `llama-3.1-8b-instant` (fast), `openai/gpt-oss-120b`, `qwen/qwen3.6-27b`.

## RAG (ask your documents)

1. In the sidebar, click **+ Upload a document** (max 5)
2. Tick **Ask my documents**
3. Questions are answered from your documents

Formats: `.txt .md .csv .json .log .py .docx .pdf`.
Documents are saved in `data/documents.json` and survive restarts (this file is gitignored, so it stays local).

## Other ways to run it

```bash
python3 agent.py          # command-line chat
python3 test_system.py    # run the tests
```

## Add a tool

1. Declare its spec in `TOOLS` (JSON schema)
2. Add the handler in `call_tool()` (agent.py)

## Use as a library

```python
from agent import run
print(run("search the web for the latest AI news"))
```