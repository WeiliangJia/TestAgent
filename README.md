# Test Agent v0.2

PRD-driven E2E test agent. Each run consumes a single user story from a JSON
PRD and executes its acceptance criteria against a target URL.

The v0.2 loop is:

1. Accept a sage-loop PRD (JSON), a target URL, a user story id, and optional credentials.
2. Select the requested user story from the PRD and build a per-run RTM.
3. Generate one BDD story and one executable test case per acceptance criterion.
4. Execute browser tasks through the browser-use driver.
5. Collect evidence (screenshots, DOM, console, network).
6. Run the two-layer assertion engine (functional + VLM visual).
7. Return a JSON report with RTM mapping and evidence links.

Design-image input (Figma exports / screenshots) is tracked via the story's
`designImages` / `designFallbackStories` / `designReviewRequired` fields but
the agent does **not** yet upload or evaluate those images — that stage is
reserved for a later version.

## PRD input shape

The PRD must follow the sage-loop schema. See `docs/` for the full contract;
the minimal per-run shape the agent parses is:

```json
{
  "$schema": "sage-loop-prd-v1",
  "project": "CarSage",
  "version": "1.0.0",
  "pipelineConfig": { "branchPattern": "feature/{requirementId}" },
  "designReviewPolicy": { "reviewMode": "design_conformance" },
  "requirements": [
    {
      "id": "R-01",
      "name": "双语对话 — 核心对话流",
      "feature": "F1",
      "description": "用户用中文/英文聊天说需求。",
      "securityFlags": [],
      "userStories": [
        {
          "id": "R-01.US-01",
          "title": "Chat API 流式对话端点",
          "description": "作为用户，我希望与 AI 对话时获得流式响应。",
          "priority": 1,
          "dependsOn": [],
          "contextHints": ["使用 Vercel AI SDK streamText"],
          "designImages": [],
          "designFallbackStories": [],
          "designReviewRequired": false,
          "notes": "后端故事，不涉及前端 UI。",
          "acceptanceCriteria": [
            {
              "id": "R-01.US-01.AC-01",
              "description": "POST /api/chat 返回 SSE 流，Content-Type 正确",
              "testType": "integration"
            }
          ]
        }
      ]
    }
  ]
}
```

Every run targets exactly one user story, identified by its id
(e.g. `R-01.US-01`). One test case is generated per acceptance criterion.

## Environment variables

| Variable | Purpose |
|---|---|
| `TEST_AGENT_EXECUTION_MODE` | `browser_use` |
| `TEST_AGENT_PROJECT_ID` | Default project id for `test-agent run` |
| `TEST_AGENT_TARGET_URL` | Default target URL for `test-agent run` |
| `TEST_AGENT_PRD_PATH` | Default PRD JSON path (defaults to `prd.json`) |
| `TEST_AGENT_USER_STORY_ID` | Default user story id for `test-agent run` |
| `TEST_AGENT_PROJECT_CONCURRENCY` | Per-project test case concurrency (`1` is safest for rate-limited LLM providers) |
| `TEST_AGENT_LOG_LEVEL` | `INFO` by default; use `DEBUG` for more terminal detail |
| `ANONYMIZED_TELEMETRY` | Set `False` to disable browser-use telemetry in local runs |
| `TEST_AGENT_BROWSER_USE_PROVIDER` | `openai` \| `anthropic` \| `glm` (default `glm`) |
| `TEST_AGENT_BROWSER_USE_MODEL` | e.g. `gpt-4o`, `claude-sonnet-4-5`, `glm-5.1` |
| `TEST_AGENT_BROWSER_USE_MAX_STEPS` | Agent step budget (default `20`) |
| `TEST_AGENT_VLM_PROVIDER` | `openai` \| `anthropic` \| `glm` (default `glm`) |
| `TEST_AGENT_VLM_MODEL` | e.g. `gpt-4o-mini`, `claude-sonnet-4-5`, `glm-5v-turbo` |
| `TEST_AGENT_ASSERTION_WARNING_THRESHOLD` | Confidence floor below which a passing assertion is downgraded to `warning` (default `0.6`) |
| `TEST_AGENT_ANALYZER_LOW_CONFIDENCE` | Failure analyzer: confidence below this boosts `test_fragility` (default `0.5`) |
| `TEST_AGENT_ANALYZER_AGGREGATION_MIN_CASES` | Failure analyzer: min number of cases sharing a signal before cross-case escalation kicks in (default `2`) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Consumed by the SDKs for both browser-use driver and VLM |
| `ZAI_API_KEY` | Z.ai / ZhipuAI API key for GLM browser-use planning and visual assertions |
| `ZAI_BASE_URL` | Optional GLM OpenAI-compatible API base URL, defaults to `https://api.z.ai/api/paas/v4/` |

## Run

PowerShell setup on Windows:

```powershell
cd "D:\Star X\TestAgent\TestAgent"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,browser,glm]"
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m patchright install chromium
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Run unit tests from PowerShell:

```powershell
cd "D:\Star X\TestAgent\TestAgent"
.\.venv\Scripts\python.exe -m pytest
```

Run one real browser-use story from PowerShell:

```powershell
cd "D:\Star X\TestAgent\TestAgent"
.\.venv\Scripts\python.exe -m app.cli run --json
```

`--json` prints a terminal-safe summary. The full report is still written to
`data/reports`; use `--full-json` only when you explicitly want the complete
report, including requirement, user story, and generated test case JSON.

`app.config` loads `.env` automatically from the TestAgent directory. Set
`TEST_AGENT_TARGET_URL`, `TEST_AGENT_PRD_PATH`, `TEST_AGENT_USER_STORY_ID`, and
the provider API key there before running a real browser-use story.

Unix/macOS setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,browser,glm]"
python -m playwright install chromium
python -m patchright install chromium
[ -f .env ] || cp .env.example .env
```

Start the API service:

```bash
python -m app.cli serve
```

Run one local user story:

```bash
test-agent run \
  --prd prd.json \
  --user-story R-01.US-01 \
  --target-url http://127.0.0.1:3000
```

Put `prd.json` in the TestAgent directory; if `TEST_AGENT_PRD_PATH` is not
set, `test-agent run` will look for that file automatically.

Scripted Playwright fallback (no LLM) is still selectable through
`TEST_AGENT_EXECUTION_MODE=playwright` at your own risk; the default path is
`browser_use`.

## HTTP example

```bash
curl -X POST http://127.0.0.1:8000/test/run \
  -H 'content-type: application/json' \
  -d '{
    "projectId": "carsage",
    "targetUrl": "https://staging.carsage.com.au",
    "userStoryId": "R-01.US-01",
    "prdJson": { "...": "sage-loop PRD object" },
    "sync": true
  }'
```

Then fetch the report:

```bash
curl http://127.0.0.1:8000/test/report/<test_id>?project_id=carsage
```

## v0.2 Boundaries

Implemented:

- FastAPI service
- SQLite run storage
- sage-loop JSON PRD parsing
- Single-user-story selection per run
- RTM and BDD generation
- Test case per acceptance criterion
- Browser-use browser execution
- Evidence persistence
- Heuristic visual/function assertion
- Lightweight failure classification
- JSON report generation

Reserved for future versions:

- Design image ingestion (Figma exports / screenshot bundles) and VLM design-conformance review
- Full L0/L1/L2 memory with vector retrieval
- PRD semantic drift detection
- Full failure attribution chain
- Adversarial reviewer/mutation/alignment agents
- Browser self-healing and test repair
- HTML/PDF report generation

---

# Test Agent v0.2（中文版）

PRD 驱动的端到端测试 Agent。每次运行只消费 JSON PRD 中的**一个** user story，并针对目标 URL 执行该 story 的全部验收标准（Acceptance Criteria）。

v0.2 的主流程：

1. 接收 sage-loop 规范的 PRD（JSON）、目标 URL、要跑的 user story id，以及可选的登录凭证。
2. 从 PRD 中选出目标 user story，按本次运行生成 RTM（需求追溯矩阵）。
3. 针对每一条 acceptance criterion 生成一条 BDD story 和一个可执行的测试用例。
4. 通过 browser-use driver 驱动浏览器执行测试任务。
5. 收集执行证据（截图、DOM、console 日志、网络失败）。
6. 运行两层断言引擎（功能层 + VLM 视觉层）。
7. 输出一份包含 RTM 映射和证据链接的 JSON 报告。

设计图输入（Figma 导出图 / 截图包）目前**只被解析和记录**在 story 的 `designImages` / `designFallbackStories` / `designReviewRequired` 字段里，Agent **暂不**上传或评审这些图片——这部分功能保留给后续版本。

## PRD 输入格式

PRD 必须遵循 sage-loop 规范。完整协议见 `docs/`，Agent 解析时关注的最小 per-run 结构如下：

```json
{
  "$schema": "sage-loop-prd-v1",
  "project": "CarSage",
  "version": "1.0.0",
  "pipelineConfig": { "branchPattern": "feature/{requirementId}" },
  "designReviewPolicy": { "reviewMode": "design_conformance" },
  "requirements": [
    {
      "id": "R-01",
      "name": "双语对话 — 核心对话流",
      "feature": "F1",
      "description": "用户用中文/英文聊天说需求。",
      "securityFlags": [],
      "userStories": [
        {
          "id": "R-01.US-01",
          "title": "Chat API 流式对话端点",
          "description": "作为用户，我希望与 AI 对话时获得流式响应。",
          "priority": 1,
          "dependsOn": [],
          "contextHints": ["使用 Vercel AI SDK streamText"],
          "designImages": [],
          "designFallbackStories": [],
          "designReviewRequired": false,
          "notes": "后端故事，不涉及前端 UI。",
          "acceptanceCriteria": [
            {
              "id": "R-01.US-01.AC-01",
              "description": "POST /api/chat 返回 SSE 流，Content-Type 正确",
              "testType": "integration"
            }
          ]
        }
      ]
    }
  ]
}
```

每次运行只针对一条 user story（用 id 标识，例如 `R-01.US-01`）；该 story 下有几条 acceptance criteria，就生成几个测试用例。

## 环境变量

| 变量 | 作用 |
|---|---|
| `TEST_AGENT_EXECUTION_MODE` | 执行模式，`browser_use` |
| `TEST_AGENT_PROJECT_ID` | `test-agent run` 的默认 project id |
| `TEST_AGENT_TARGET_URL` | `test-agent run` 的默认目标 URL |
| `TEST_AGENT_PRD_PATH` | 默认 PRD JSON 路径（默认 `prd.json`） |
| `TEST_AGENT_USER_STORY_ID` | `test-agent run` 的默认 user story id |
| `TEST_AGENT_PROJECT_CONCURRENCY` | 每个 project 的 test case 并发数；限流明显时建议 `1` |
| `TEST_AGENT_LOG_LEVEL` | 日志级别，默认 `INFO`；想看更多细节改 `DEBUG` |
| `ANONYMIZED_TELEMETRY` | 设为 `False` 关闭 browser-use 本地遥测 |
| `TEST_AGENT_BROWSER_USE_PROVIDER` | `openai` \| `anthropic` \| `glm`（默认 `glm`） |
| `TEST_AGENT_BROWSER_USE_MODEL` | 如 `gpt-4o`、`claude-sonnet-4-5`、`glm-5.1` |
| `TEST_AGENT_BROWSER_USE_MAX_STEPS` | Agent 步数预算（默认 `20`） |
| `TEST_AGENT_VLM_PROVIDER` | `openai` \| `anthropic` \| `glm`（默认 `glm`） |
| `TEST_AGENT_VLM_MODEL` | 如 `gpt-4o-mini`、`claude-sonnet-4-5`、`glm-5v-turbo` |
| `TEST_AGENT_ASSERTION_WARNING_THRESHOLD` | 置信度阈值，低于此值的 passing 会降级为 `warning`（默认 `0.6`） |
| `TEST_AGENT_ANALYZER_LOW_CONFIDENCE` | 失败归因：低于此置信度会为 `test_fragility` 加权（默认 `0.5`） |
| `TEST_AGENT_ANALYZER_AGGREGATION_MIN_CASES` | 失败归因：共享同一信号的用例达到此数量才触发跨用例升级（默认 `2`） |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | browser-use driver 和 VLM 的 SDK 使用 |
| `ZAI_API_KEY` | Z.ai / 智谱的 API key，用于 GLM 的 browser-use 规划和视觉断言 |
| `ZAI_BASE_URL` | 可选的 GLM OpenAI 兼容 API base URL，默认 `https://api.z.ai/api/paas/v4/` |

## 运行

Windows PowerShell 初始化：

```powershell
cd "D:\Star X\TestAgent\TestAgent"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,browser,glm]"
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m patchright install chromium
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

PowerShell 跑单元测试：

```powershell
cd "D:\Star X\TestAgent\TestAgent"
.\.venv\Scripts\python.exe -m pytest
```

PowerShell 跑一条真实 browser-use user story：

```powershell
cd "D:\Star X\TestAgent\TestAgent"
.\.venv\Scripts\python.exe -m app.cli run --json
```

`--json` 只打印适合终端查看的摘要。完整报告仍会写入 `data/reports`；只有你明确需要
包含 requirement、user story、生成测试用例等完整 JSON 时，才使用 `--full-json`。

`app.config` 会自动读取 TestAgent 目录下的 `.env`。真实测试前确认
`TEST_AGENT_TARGET_URL`、`TEST_AGENT_PRD_PATH`、`TEST_AGENT_USER_STORY_ID` 和
provider API key 已经设置好。

Unix/macOS 初始化：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,browser,glm]"
python -m playwright install chromium
python -m patchright install chromium
[ -f .env ] || cp .env.example .env
```

启动 API 服务：

```bash
python -m app.cli serve
```

本地跑一条 user story：

```bash
test-agent run \
  --prd prd.json \
  --user-story R-01.US-01 \
  --target-url http://127.0.0.1:3000
```

把 `prd.json` 放在 TestAgent 目录下；如果没设 `TEST_AGENT_PRD_PATH`，`test-agent run` 会自动查找该文件。

脚本式 Playwright 回退模式（无 LLM）可以通过 `TEST_AGENT_EXECUTION_MODE=playwright` 切换，自行承担风险；默认路径是 `browser_use`。

## HTTP 调用示例

```bash
curl -X POST http://127.0.0.1:8000/test/run \
  -H 'content-type: application/json' \
  -d '{
    "projectId": "carsage",
    "targetUrl": "https://staging.carsage.com.au",
    "userStoryId": "R-01.US-01",
    "prdJson": { "...": "完整的 sage-loop PRD 对象" },
    "sync": true
  }'
```

之后拉取报告：

```bash
curl http://127.0.0.1:8000/test/report/<test_id>?project_id=carsage
```

## v0.2 边界

已实现：

- FastAPI 服务
- SQLite 运行态存储
- sage-loop JSON PRD 解析
- 每次运行选一条 user story
- RTM 和 BDD 生成
- 每条 acceptance criterion 一个测试用例
- browser-use 浏览器执行
- 证据持久化
- 启发式功能/视觉断言
- 轻量失败分类
- JSON 报告生成

留给后续版本：

- 设计图输入（Figma 导出 / 截图包）及 VLM 设计一致性评审
- 完整的 L0/L1/L2 三级记忆 + 向量检索
- PRD 语义漂移检测
- 完整的失败归因链
- 对抗式 reviewer / mutation / alignment agents
- 浏览器自愈和测试自动修复
- HTML/PDF 报告生成
