from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    username: str | None = None
    password: str | None = None
    login_url: str | None = Field(default=None, alias="loginUrl")
    extra_fields: dict[str, str] = Field(default_factory=dict, alias="extraFields")


class TestRunRequest(BaseModel):
    project_id: str = Field(..., min_length=1, alias="projectId")
    target_url: str = Field(..., min_length=1, alias="targetUrl")
    prd_content: str | None = Field(default=None, alias="prdContent")
    prd_path: str | None = Field(default=None, alias="prdPath")
    credentials: Credentials | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    sync: bool = False


class TestRunCreated(BaseModel):
    project_id: str = Field(..., alias="projectId")
    test_id: str = Field(..., alias="testId")
    status: str
    report_url: str = Field(..., alias="reportUrl")


class HealthResponse(BaseModel):
    status: str
    execution_mode: str = Field(..., alias="executionMode")


class ErrorResponse(BaseModel):
    detail: str
