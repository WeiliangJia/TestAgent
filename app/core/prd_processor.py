from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.config import Settings
from app.models.test_case import Requirement

LOGGER = logging.getLogger(__name__)
_DEFAULT_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"


class PRDProcessor:
    """Parses Markdown PRDs.

    PRD input is expected to be text content, a Markdown/text file, or a
    lightweight ``.docx`` file via ``prd_path``. PDF is not supported.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_content(self, prd_content: str | None, prd_path: str | None) -> str:
        if prd_content and prd_content.strip():
            return prd_content.strip()
        if not prd_path:
            raise ValueError("Either prd_content or prd_path is required.")

        path = Path(prd_path)
        if not path.is_absolute():
            path = self.settings.workspace_root / path
        path = path.resolve()

        if self.settings.workspace_root not in path.parents and path != self.settings.workspace_root:
            raise ValueError("prd_path must be inside the configured workspace.")
        if not path.exists():
            raise FileNotFoundError(f"PRD file not found: {path}")
        LOGGER.info("Loading PRD from %s", path)
        if path.suffix.lower() == ".docx":
            return _read_docx_text(path)
        return path.read_text(encoding="utf-8").strip()

    def extract_requirements(self, prd_content: str) -> list[Requirement]:
        if self.settings.prd_llm_provider not in {"", "heuristic", "mock", "rules"}:
            return self._extract_requirements_with_llm(prd_content)
        return self._extract_requirements_heuristic(prd_content)

    def _extract_requirements_with_llm(self, prd_content: str) -> list[Requirement]:
        provider = self.settings.prd_llm_provider
        model = self.settings.prd_llm_model
        client_kwargs = _client_kwargs_for_provider(provider)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for LLM PRD extraction. "
                'Install with `pip install -e ".[glm,browser,dev]"`.'
            ) from exc

        prompt = _build_prd_extraction_prompt(
            prd_content[: self.settings.prd_llm_max_chars],
            max_requirements=self.settings.prd_llm_max_requirements,
        )
        client = OpenAI(**client_kwargs)
        LOGGER.info(
            "Extracting PRD requirements with LLM provider=%s model=%s",
            provider,
            model,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You extract actionable, UI-testable E2E requirements "
                    "from product requirements documents. Return strict JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        completion = _create_chat_completion(
            client=client,
            model=model,
            messages=messages,
            max_tokens=2500,
        )
        text = _extract_completion_text(completion)
        try:
            requirements = _requirements_from_llm_text(text)
        except (json.JSONDecodeError, ValueError) as exc:
            LOGGER.warning(
                "LLM PRD extraction returned invalid JSON; requesting one repair pass: %s",
                exc,
            )
            repair_completion = _create_chat_completion(
                client=client,
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You repair malformed JSON. Return valid JSON only, "
                            "with no markdown or commentary."
                        ),
                    },
                    {
                        "role": "user",
                        "content": _build_json_repair_prompt(
                            text,
                            error=str(exc),
                            max_requirements=self.settings.prd_llm_max_requirements,
                        ),
                    },
                ],
                max_tokens=2500,
            )
            repaired_text = _extract_completion_text(repair_completion)
            try:
                requirements = _requirements_from_llm_text(repaired_text)
            except (json.JSONDecodeError, ValueError) as repair_exc:
                raise ValueError(
                    "LLM PRD extraction returned invalid JSON after repair: "
                    f"{repair_exc}"
                ) from repair_exc

        requirements = requirements[: self.settings.prd_llm_max_requirements]
        if not requirements:
            raise ValueError("LLM returned no actionable requirements from PRD.")
        LOGGER.info("Extracted %s requirements from PRD with LLM", len(requirements))
        return requirements

    def _extract_requirements_heuristic(self, prd_content: str) -> list[Requirement]:
        candidates = _extract_candidate_lines(prd_content)
        if not candidates:
            candidates = [_first_meaningful_paragraph(prd_content)]

        requirements: list[Requirement] = []
        for index, line in enumerate(candidates, start=1):
            description = _clean_requirement_text(line)
            if not description:
                continue
            priority = _infer_priority(description)
            criteria = _infer_acceptance_criteria(description)
            requirements.append(
                Requirement(
                    req_id=f"REQ-{index:03d}",
                    description=description,
                    priority=priority,
                    acceptance_criteria=criteria,
                )
            )
        if not requirements:
            raise ValueError("No actionable requirements found in PRD.")
        LOGGER.info("Extracted %s requirements from PRD", len(requirements))
        return requirements

    def build_rtm(self, requirements: list[Requirement]) -> list[dict]:
        return [
            {
                "reqId": item.req_id,
                "description": item.description,
                "priority": item.priority,
                "acceptanceCriteria": item.acceptance_criteria,
            }
            for item in requirements
        ]


def _extract_candidate_lines(content: str) -> list[str]:
    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^[-*+]\s+", line):
            lines.append(line)
            continue
        if re.match(r"^\d+[\.)]\s+", line):
            lines.append(line)
            continue
        if re.match(r"^(REQ|US|AC)[-_ ]?\d+", line, flags=re.IGNORECASE):
            lines.append(line)
            continue
        if _looks_like_requirement(line):
            lines.append(line)
    return _dedupe_keep_order(lines)


def _looks_like_requirement(line: str) -> bool:
    normalized = line.lower()
    signals = [
        "user can",
        "user should",
        "as a user",
        "must",
        "shall",
        "should",
        "allow",
        "enable",
        "support",
        "login",
        "checkout",
        "search",
    ]
    return any(signal in normalized for signal in signals) and len(line) <= 300


def _clean_requirement_text(line: str) -> str:
    line = re.sub(r"^[-*+]\s+", "", line)
    line = re.sub(r"^\d+[\.)]\s+", "", line)
    line = re.sub(r"^(REQ|US|AC)[-_ ]?\d+[:.)\-\s]*", "", line, flags=re.IGNORECASE)
    return line.strip(" -:\t")


def _infer_priority(description: str) -> str:
    text = description.lower()
    if any(token in text for token in ["critical", "must", "p0", "blocker"]):
        return "P0"
    if any(token in text for token in ["high", "should", "p1"]):
        return "P1"
    if any(token in text for token in ["nice", "could", "p3"]):
        return "P3"
    return "P2"


def _infer_acceptance_criteria(description: str) -> list[str]:
    text = description.strip().rstrip(".")
    return [
        f"The user can complete: {text}.",
        "The page provides visible feedback for the expected result.",
    ]


def _client_kwargs_for_provider(provider: str) -> dict[str, str]:
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for PRD LLM extraction.")
        return {"api_key": api_key}
    if provider in {"glm", "zai", "zhipu", "zhipuai"}:
        api_key = _first_env("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ZAI_API_KEY/ZHIPUAI_API_KEY/GLM_API_KEY is required for PRD LLM extraction."
            )
        return {"api_key": api_key, "base_url": _glm_base_url()}
    raise ValueError(f"Unsupported TEST_AGENT_PRD_PROVIDER: {provider}")


def _build_prd_extraction_prompt(content: str, *, max_requirements: int) -> str:
    return (
        "Read this PRD and extract the most important actionable E2E test requirements.\n"
        "Only include behavior a browser automation agent can verify on the target website.\n"
        f"Return at most {max_requirements} requirements.\n\n"
        "Answer ONLY with strict JSON in this shape:\n"
        '{"requirements":[{"description":"User can ...","priority":"P0|P1|P2|P3",'
        '"acceptance_criteria":["The user can ...","The page ..."]}]}\n\n'
        "PRD:\n"
        f"{content}"
    )


def _build_json_repair_prompt(
    malformed_text: str, *, error: str, max_requirements: int
) -> str:
    return (
        "The previous PRD extraction response was not valid JSON.\n"
        f"JSON parser error: {error}\n\n"
        "Rewrite it into valid strict JSON only. Preserve the requirement meanings, "
        f"keep at most {max_requirements} requirements, and use this exact shape:\n"
        '{"requirements":[{"description":"User can ...","priority":"P0|P1|P2|P3",'
        '"acceptance_criteria":["The user can ...","The page ..."]}]}\n\n'
        "Malformed response:\n"
        "<<<\n"
        f"{malformed_text[:12000]}\n"
        ">>>"
    )


def _requirements_from_llm_text(text: str) -> list[Requirement]:
    data = _parse_json_object(text)
    raw_requirements = data.get("requirements", [])
    if not isinstance(raw_requirements, list):
        return []

    requirements: list[Requirement] = []
    for index, item in enumerate(raw_requirements, start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        priority = str(item.get("priority", "P2")).upper()
        if priority not in {"P0", "P1", "P2", "P3"}:
            priority = _infer_priority(description)
        criteria = item.get("acceptance_criteria") or item.get("acceptanceCriteria")
        if isinstance(criteria, list):
            acceptance_criteria = [str(value).strip() for value in criteria if str(value).strip()]
        else:
            acceptance_criteria = []
        if not acceptance_criteria:
            acceptance_criteria = _infer_acceptance_criteria(description)
        requirements.append(
            Requirement(
                req_id=f"REQ-{len(requirements) + 1:03d}",
                description=description,
                priority=priority,
                acceptance_criteria=acceptance_criteria,
            )
        )
    return requirements


def _parse_json_object(text: str) -> dict[str, Any]:
    json_text = _extract_json_object_text(text)
    if not json_text:
        raise ValueError("LLM PRD extraction returned non-JSON output.")
    data = json.loads(json_text)
    if not isinstance(data, dict):
        raise ValueError("LLM PRD extraction returned a non-object JSON payload.")
    return data


def _extract_json_object_text(text: str) -> str | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def _create_chat_completion(
    *,
    client: object,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> object:
    return client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0,
    )


def _extract_completion_text(completion: object) -> str:
    choices = _field(completion, "choices")
    choice = choices[0] if choices else None
    message = _field(choice, "message") if choice is not None else None
    content = _field(message, "content") if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_block_text(block) for block in content)
    return str(content) if content else ""


def _content_block_text(block: object) -> str:
    if isinstance(block, dict):
        return str(block.get("text") or block.get("content") or "")
    return str(getattr(block, "text", "") or getattr(block, "content", "") or "")


def _field(value: object, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _glm_base_url() -> str:
    return (
        _first_env("ZAI_BASE_URL", "ZHIPUAI_BASE_URL", "GLM_BASE_URL")
        or _DEFAULT_ZAI_BASE_URL
    )


def _first_meaningful_paragraph(content: str) -> str:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", content) if chunk.strip()]
    if paragraphs:
        return paragraphs[0][:300]
    return content.strip()[:300]


def _dedupe_keep_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        key = _clean_requirement_text(line).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(line)
    return result


def _read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError(f"Invalid DOCX file, missing word/document.xml: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid DOCX file: {path}") from exc

    root = ElementTree.fromstring(document_xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        chunks: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{namespace}t" and node.text:
                chunks.append(node.text)
            elif node.tag == f"{namespace}tab":
                chunks.append("\t")
            elif node.tag == f"{namespace}br":
                chunks.append("\n")
        text = "".join(chunks).strip()
        if text:
            paragraphs.append(text)

    content = "\n".join(paragraphs).strip()
    if not content:
        raise ValueError(f"No readable text found in DOCX file: {path}")
    return content
