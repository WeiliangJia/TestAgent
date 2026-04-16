# Test Agent v0.1

Minimal PRD-driven E2E test agent service.

The v0.1 goal is an end-to-end runnable loop:

1. Accept a PRD, target URL, and optional credentials.
2. Extract requirements and build an RTM.
3. Generate BDD-style user stories and executable test cases.
4. Execute browser tasks through a pluggable browser client.
5. Collect evidence such as screenshots, DOM, console logs, and network failures.
6. Run a pluggable assertion engine.
7. Return a JSON report with RTM mapping and evidence links.

By default the service uses `mock` execution so the architecture can run without browser binaries or model keys. Three execution modes are supported:

- `mock` (default) — deterministic stub, no browser, no API key.
- `browser_use` — LLM-driven agent via the [`browser-use`](https://github.com/browser-use/browser-use) library.
- `playwright` — scripted Playwright without an LLM (useful for debugging).

## Environment variables

| Variable | Purpose |
|---|---|
| `TEST_AGENT_EXECUTION_MODE` | `mock` \| `browser_use` \| `playwright` |
| `TEST_AGENT_BROWSER_USE_PROVIDER` | `openai` \| `anthropic` (default `openai`) |
| `TEST_AGENT_BROWSER_USE_MODEL` | e.g. `gpt-4o`, `claude-sonnet-4-5` |
| `TEST_AGENT_BROWSER_USE_MAX_STEPS` | Agent step budget (default `20`) |
| `TEST_AGENT_VLM_PROVIDER` | `mock` \| `openai` \| `anthropic` \| `glm` (default `mock`) |
| `TEST_AGENT_VLM_MODEL` | e.g. `gpt-4o-mini`, `claude-sonnet-4-5`, `glm-5v-turbo` |
| `TEST_AGENT_ASSERTION_WARNING_THRESHOLD` | Confidence floor below which a passing assertion is downgraded to `warning` (default `0.6`) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Consumed by the SDKs for both browser-use driver and VLM |
| `ZAI_API_KEY` | Z.ai / ZhipuAI API key for GLM visual assertions |
| `ZAI_BASE_URL` | Optional GLM-compatible API base URL, defaults to the SDK setting |

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Optional real-browser mode (browser-use agent with visual assertion):

```bash
pip install -e ".[browser,openai,dev]"
playwright install chromium
export OPENAI_API_KEY=sk-...
TEST_AGENT_EXECUTION_MODE=browser_use \
TEST_AGENT_VLM_PROVIDER=openai \
uvicorn app.main:app --reload
```

Optional GLM-5V-Turbo visual assertion:

```bash
pip install -e ".[dev,glm]"
export ZAI_API_KEY=your-zai-api-key
TEST_AGENT_VLM_PROVIDER=glm \
TEST_AGENT_VLM_MODEL=glm-5v-turbo \
uvicorn app.main:app --reload
```

PowerShell equivalent:

```powershell
python -m pip install -e ".[dev,glm]"
$env:ZAI_API_KEY = "your-zai-api-key"
$env:TEST_AGENT_VLM_PROVIDER = "glm"
$env:TEST_AGENT_VLM_MODEL = "glm-5v-turbo"
uvicorn app.main:app --reload
```

Scripted Playwright (no LLM) fallback:

```bash
TEST_AGENT_EXECUTION_MODE=playwright uvicorn app.main:app --reload
```

Optional API key:

```bash
TEST_AGENT_API_KEY=local-secret uvicorn app.main:app --reload
```

## Example

```bash
curl -X POST http://127.0.0.1:8000/test/run \
  -H 'content-type: application/json' \
  -d '{
    "projectId": "carsage",
    "targetUrl": "https://example.com",
    "prdContent": "- User can open the home page\n- User can see pricing",
    "sync": true
  }'
```

Then fetch the report:

```bash
curl http://127.0.0.1:8000/test/report/<test_id>?project_id=carsage
```

## v0.1 Boundaries

Implemented:

- FastAPI service
- SQLite run storage
- PRD parsing
- RTM and BDD generation
- Test case generation
- Mock browser execution
- Optional Playwright browser execution
- Evidence persistence
- Heuristic visual/function assertion
- Lightweight failure classification
- JSON report generation

Reserved for future versions:

- Full L0/L1/L2 memory with vector retrieval
- PRD semantic drift detection
- Full failure attribution chain
- Adversarial reviewer/mutation/alignment agents
- Browser self-healing and test repair
- HTML/PDF report generation
