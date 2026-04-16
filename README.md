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

By default the service runs with real GLM-powered PRD extraction, browser-use
planning, and visual assertions. Runtime commands reject simulated execution so
the agent does not silently skip real browser or model calls.

- `browser_use` — LLM-driven agent via the [`browser-use`](https://github.com/browser-use/browser-use) library.

## Environment variables

| Variable | Purpose |
|---|---|
| `TEST_AGENT_EXECUTION_MODE` | `browser_use` |
| `TEST_AGENT_PROJECT_ID` | Default project id for `test-agent run` |
| `TEST_AGENT_TARGET_URL` | Default target URL for `test-agent run`, e.g. `http://127.0.0.1:3000` |
| `TEST_AGENT_PRD_PATH` | Default PRD path relative to the TestAgent directory, e.g. `prd.docx` |
| `TEST_AGENT_LOG_LEVEL` | `INFO` by default; use `DEBUG` for more terminal detail |
| `ANONYMIZED_TELEMETRY` | Set `False` to disable browser-use telemetry in local runs |
| `TEST_AGENT_PRD_PROVIDER` | `openai` \| `glm`; use `glm` for real LLM PRD extraction |
| `TEST_AGENT_PRD_MODEL` | e.g. `gpt-4o`, `glm-5.1` |
| `TEST_AGENT_PRD_MAX_REQUIREMENTS` | Maximum requirements to extract from the PRD (default `12`) |
| `TEST_AGENT_PRD_MAX_CHARS` | Maximum PRD characters sent to the LLM (default `60000`) |
| `TEST_AGENT_BROWSER_USE_PROVIDER` | `openai` \| `anthropic` \| `glm` (default `glm`) |
| `TEST_AGENT_BROWSER_USE_MODEL` | e.g. `gpt-4o`, `claude-sonnet-4-5`, `glm-5.1` |
| `TEST_AGENT_BROWSER_USE_MAX_STEPS` | Agent step budget (default `20`) |
| `TEST_AGENT_VLM_PROVIDER` | `openai` \| `anthropic` \| `glm` (default `glm`) |
| `TEST_AGENT_VLM_MODEL` | e.g. `gpt-4o-mini`, `claude-sonnet-4-5`, `glm-5v-turbo` |
| `TEST_AGENT_ASSERTION_WARNING_THRESHOLD` | Confidence floor below which a passing assertion is downgraded to `warning` (default `0.6`) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Consumed by the SDKs for both browser-use driver and VLM |
| `ZAI_API_KEY` | Z.ai / ZhipuAI API key for GLM PRD extraction, browser-use planning, and visual assertions |
| `ZAI_BASE_URL` | Optional GLM OpenAI-compatible API base URL, defaults to `https://api.z.ai/api/paas/v4/` |

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,browser,glm]"
cp .env.example .env
```

Edit `.env`, then start the API service:

```bash
python -m app.cli serve
```

Run one local PRD test without curl:

```bash
python -m app.cli run
```

After reinstalling the editable package, the shorter console script is also
available:

```bash
test-agent serve
test-agent run
```

Put `prd.md`, `prd.txt`, or `prd.docx` in the TestAgent directory. If
`TEST_AGENT_PRD_PATH` is not set, `test-agent run` will look for those filenames
automatically. Override the target URL or PRD from the terminal when needed:

```bash
test-agent run --target-url http://127.0.0.1:3000 --prd prd.docx
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

Optional browser-use with GLM through the Z.ai OpenAI-compatible API:

```bash
pip install -e ".[browser,glm,dev]"
playwright install chromium
export ZAI_API_KEY=your-zai-api-key
TEST_AGENT_EXECUTION_MODE=browser_use \
TEST_AGENT_PRD_PROVIDER=glm \
TEST_AGENT_PRD_MODEL=glm-5.1 \
TEST_AGENT_BROWSER_USE_PROVIDER=glm \
TEST_AGENT_BROWSER_USE_MODEL=glm-5.1 \
TEST_AGENT_VLM_PROVIDER=glm \
TEST_AGENT_VLM_MODEL=glm-5v-turbo \
test-agent run
```

If GLM struggles with browser-use action planning, switch only the browser driver
back to OpenAI/Anthropic or use `--mode playwright`. GLM can still remain as the
visual assertion model through `TEST_AGENT_VLM_PROVIDER=glm`.

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
test-agent run --mode playwright --target-url http://127.0.0.1:3000 --prd prd.docx
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
- Markdown/text/DOCX PRD loading
- RTM and BDD generation
- Test case generation
- Browser-use browser execution
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
