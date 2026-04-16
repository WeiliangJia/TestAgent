from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.config import Settings
from app.models.test_case import Requirement

LOGGER = logging.getLogger(__name__)


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
