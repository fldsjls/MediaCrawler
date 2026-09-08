"""Public workflow contracts, independent of workers and persistence."""
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field

Kind = Literal['session', 'discover', 'content', 'comments', 'media', 'files', 'export']


class StepSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    kind: Kind
    name: str = Field('', max_length=120)
    enabled: bool = True
    input: str = 'source'
    overrides: dict[str, Any] = Field(default_factory=dict)


class WorkflowPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field('未命名方案', max_length=120)
    platform: str = 'bili'
    target: str = Field('', max_length=10000)
    source: Literal['website', 'direct', 'selection', 'history'] = 'website'
    mode: Literal['detail', 'search', 'creator'] = 'detail'
    session_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list, max_length=10000)
    history_id: str | None = None
    steps: list[StepSpec] = Field(default_factory=list, max_length=50)


class TaskDefinition(BaseModel):
    id: Kind
    title: str
    inputs: list[str]
    output: str
    fields: list[str]


class StepRun(BaseModel):
    id: str
    kind: str
    name: str
    state: str = 'queued'
    settings: dict = Field(default_factory=dict)
    error: str = ''


class WorkflowRun(BaseModel):
    id: str
    name: str
    state: str
    steps: list[StepRun]
    retry_of: str | None = None


class Artifact(BaseModel):
    id: str
    task_id: str
    step_id: str = ''
    title: str
    kind: str
    state: str
    size: int | None = None
