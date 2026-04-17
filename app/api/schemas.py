from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class Credentials(BaseModel):
    username: str | None = None
    password: str | None = None
    login_url: str | None = Field(default=None, alias="loginUrl")
    extra_fields: dict[str, str] = Field(default_factory=dict, alias="extraFields")


class TestRunRequest(BaseModel):
    project_id: str = Field(..., min_length=1, alias="projectId")
    target_url: str = Field(..., min_length=1, alias="targetUrl")
    user_story_id: str | None = Field(default=None, alias="userStoryId")
    prd_json: dict[str, Any] | None = Field(default=None, alias="prdJson")
    prd_content: str | None = Field(default=None, alias="prdContent")
    prd_path: str | None = Field(default=None, alias="prdPath")
    ledger_json: dict[str, Any] | None = Field(default=None, alias="ledgerJson")
    ledger_content: str | None = Field(default=None, alias="ledgerContent")
    ledger_path: str | None = Field(default=None, alias="ledgerPath")
    credentials: Credentials | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    sync: bool = False

    @model_validator(mode="after")
    def _require_prd_source(self) -> "TestRunRequest":
        if self.prd_json is None and not self.prd_content and not self.prd_path:
            raise ValueError(
                "One of prdJson, prdContent, or prdPath is required."
            )
        has_ledger = (
            self.ledger_json is not None
            or bool(self.ledger_content)
            or bool(self.ledger_path)
        )
        if not self.user_story_id and not has_ledger:
            raise ValueError(
                "Either userStoryId or a ledger source (ledgerJson/ledgerContent/ledgerPath) is required."
            )
        return self


class TestRunCreated(BaseModel):
    project_id: str = Field(..., alias="projectId")
    test_id: str = Field(..., alias="testId")
    user_story_id: str | None = Field(default=None, alias="userStoryId")
    status: str
    report_url: str = Field(..., alias="reportUrl")


class HealthResponse(BaseModel):
    status: str
    execution_mode: str = Field(..., alias="executionMode")


class ErrorResponse(BaseModel):
    detail: str
