# Architecture — AI Services

Agent IA conversationnel **sans framework** : boucle tool-calling maison, multi-provider,
RAG sur documents, mémoire long terme, interpréteur de code sandboxé avec affichage de
graphiques dans le chat, sous-agents spécialisés et outils externes MCP.

---

## 1. Vue d'ensemble

```mermaid
flowchart TB
    subgraph CLIENT["Navigateur - interface vanilla JS servie par webapp.py"]
        UI["Bulle de chat<br/>Markdown echappe + KaTeX + images"]
        SIDE["Barre laterale<br/>Conversations (localStorage)<br/>Documents - Memoires - Statut MCP"]
    end

    subgraph SERVER["Processus Python unique"]
        HTTP["webapp.py<br/>routes HTTP + rendu serveur"]
        AGENT["agent.py<br/>orchestrateur + boucle d'outils"]
    end

    subgraph TOOLS["Outils exposes au modele"]
        WS["web_search"]
        RD["search_documents"]
        MM["remember / recall_memory"]
        PY["run_python"]
        DK["delegate_task"]
        MP["mcp_*"]
    end

    subgraph MODULES["Modules metier"]
        RAGM["rag.py<br/>index TF-IDF"]
        MEMM["memory.py"]
        SBX["sandbox.py"]
        MED["media.py"]
        MCPC["mcp_client.py"]
    end

    subgraph STORE["Persistance - dossier data/"]
        F1[("documents.json")]
        F2[("memory.json")]
        F3[("mcp.json")]
    end

    UI -- "POST /chat" --> HTTP
    SIDE -- "upload / docs / memories / mcp" --> HTTP
    HTTP --> AGENT
    AGENT --> TOOLS
    RD --> RAGM --> F1
    MM --> MEMM --> F2
    PY --> SBX --> MED
    DK -.-> AGENT
    MP --> MCPC --> F3
    MED -- "GET /image/IMG:x" --> UI
```

Un seul processus Python héberge tout : le serveur web, l'agent, les modules métier et
les connexions MCP. C'est ce qui permet le pipeline d'images sans stockage externe.

---

## 2. Flux d'une requête de chat

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant W as Navigateur
    participant H as webapp.py
    participant A as Orchestrateur
    participant T as Outils

    U->>W: message
    W->>H: POST /chat (historique)
    H->>A: run_with_messages()
    loop max 8 etapes
        A->>A: appel LLM (tools = JSON Schema)
        alt tool_calls presentes
            A->>T: call_tool(nom, args)
            T-->>A: resultat JSON (+ tokens [[IMG:x]])
        end
    end
    A-->>H: reponse finale + agent.pop_images()
    H->>H: injection des tokens manquants
    H-->>W: reply, images[], model
    W->>W: rendu Markdown + KaTeX + img
```

Point clé : les images produites par la sandbox sont captées **à la source** (buffer
thread-local) puis réinjectées dans la réponse même si le modèle oublie de mentionner
le token. L'affichage ne dépend pas de la discipline du modèle.

---

## 3. L'orchestrateur (`agent.py`)

- **Multi-provider** : Ollama, Groq, OpenRouter, OpenAI — toute API compatible OpenAI
  (`/chat/completions`), sélection par variables d'environnement.
- **Boucle d'outils** (`run_loop`) : jusqu'à `max_steps` allers-retours ; chaque
  `tool_call` est exécuté puis renvoyé au modèle au format `role: tool`.
- **Robustesse** : retry avec backoff exponentiel sur 408/429/5xx, timeout global,
  messages d'erreur traduits pour l'utilisateur (plus de jargon provider).
- **Anti-hallucination** : le prompt système impose de ne rapporter que ce que les
  outils confirment.

## 4. Les outils

| Outil | Module | Rôle |
|---|---|---|
| `web_search` | DuckDuckGo (optionnel) | recherche web, top 3 résultats |
| `search_documents` | `rag.py` | recherche TF-IDF cosinus dans les documents uploadés |
| `remember` / `recall_memory` | `memory.py` | mémoire long terme par recouvrement de mots-clés |
| `run_python` | `sandbox.py` | exécution Python isolée, graphiques affichables |
| `delegate_task` | `agent.py` | délégation à un sous-agent spécialisé |
| `mcp_<serveur>_<outil>` | `mcp_client.py` | outils externes découverts dynamiquement |

### RAG (`rag.py`)

```mermaid
flowchart LR
    A["Document brut<br/>PDF / DOCX / TXT / CSV"] --> B["Extraction texte<br/>pypdf - zip XML docx"]
    B --> C["Chunking<br/>paragraphes, 1200 car.<br/>chevauchement 150"]
    C --> D["Index TF-IDF<br/>cosinus + IDF lisse"]
    D --> E["retrieve(query, top_k=3)<br/>scores + noms de fichiers"]
```

- Max 5 documents, déduplication par nom, persistance JSON, rechargement à chaud.
- Sanitisation des noms de fichiers (anti path traversal).

<!-- PART2 -->
