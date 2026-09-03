"""DAG Abstract Syntax Tree (AST) Definitions Module for Basalt Workflow Engine.

Defines Pydantic v2 schemas for DAG specification, step definitions, task executors,
trigger specifications, and retry policies.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from basalt.utils.validators import is_valid_identifier, validate_cron_expression, validate_http_url


class ExecutorType(str, Enum):
    """Supported task step executor types."""

    INLINE = "inline"
    PYTHON_INLINE = "python_inline"
    SUBPROCESS = "subprocess"
    HTTP = "http"
    CUSTOM = "custom"


class TriggerType(str, Enum):
    """Supported event trigger types."""

    CRON = "cron"
    INTERVAL = "interval"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class OnFailureAction(str, Enum):
    """Action to take when a step fails after retry exhaustion."""

    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"
    RETRY = "retry"


class RetryPolicySpec(BaseModel):
    """Specification schema for step execution retry and backoff rules."""

    max_retries: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Maximum retry attempts after initial failure.",
    )
    initial_delay_seconds: float = Field(
        default=1.0,
        gt=0.0,
        description="Initial delay in seconds before first retry.",
    )
    max_delay_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Maximum backoff delay ceiling in seconds.",
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        description="Exponential multiplier for backoff calculation.",
    )
    jitter: bool = Field(
        default=True,
        description="Apply randomized jitter to backoff delay interval.",
    )

    @model_validator(mode="before")
    @classmethod
    def handle_interval_alias(cls, data: Any) -> Any:
        """Map initial_interval_seconds YAML alias to initial_delay_seconds."""
        if isinstance(data, dict):
            if "initial_interval_seconds" in data and "initial_delay_seconds" not in data:
                data = dict(data)
                data["initial_delay_seconds"] = data["initial_interval_seconds"]
        return data



class StepSpec(BaseModel):
    """Specification schema for an individual workflow task step."""

    id: str = Field(
        ...,
        description="Unique identifier for the step within the DAG.",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable step display title.",
    )
    description: str | None = Field(
        default=None,
        description="Detailed description of step responsibility.",
    )
    executor_type: ExecutorType = Field(
        default=ExecutorType.SUBPROCESS,
        description="Executor type handling task execution.",
    )

    # Subprocess Executor Parameters
    command: str | None = Field(
        default=None,
        description="Shell command or script string for subprocess executor.",
    )
    working_dir: str | None = Field(
        default=None,
        description="Working directory for subprocess execution.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Step-specific environment variables.",
    )

    # Inline Executor Parameters
    function: str | None = Field(
        default=None,
        description="Import path of Python callable for inline executor.",
    )
    callable_name: str | None = Field(
        default=None,
        description="Registry name of Python callable for inline executor.",
    )
    module_path: str | None = Field(
        default=None,
        description="Python module import path.",
    )
    function_name: str | None = Field(
        default=None,
        description="Python function name inside module.",
    )

    # HTTP Executor Parameters
    url: str | None = Field(
        default=None,
        description="HTTP URL for HTTP executor.",
    )
    method: str = Field(
        default="GET",
        description="HTTP verb (GET, POST, PUT, DELETE, PATCH).",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers dictionary for HTTP executor.",
    )
    query_params: dict[str, Any] = Field(
        default_factory=dict,
        description="HTTP query parameters.",
    )
    body: Any | None = Field(
        default=None,
        description="HTTP body payload string.",
    )
    json_payload: Any | None = Field(
        default=None,
        description="HTTP JSON body payload.",
    )
    expected_status_codes: list[int] | None = Field(
        default=None,
        description="Acceptable HTTP response status codes list.",
    )

    # Dynamic Step Inputs & Configuration
    params: dict[str, Any] = Field(
        default_factory=dict,
        alias="parameters",
        description="Parameters dictionary passed into step execution context.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters dictionary alias.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="List of step IDs that must complete before this step runs.",
    )
    timeout_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Execution timeout limit in seconds.",
    )
    condition: str | None = Field(
        default=None,
        alias="when",
        description="Conditional expression string evaluated before execution.",
    )
    when: str | None = Field(
        default=None,
        description="Conditional expression alias.",
    )
    retry_policy: RetryPolicySpec | None = Field(
        default_factory=RetryPolicySpec,
        description="Retry policy configuration for step execution.",
    )
    on_failure: OnFailureAction = Field(
        default=OnFailureAction.FAIL_FAST,
        description="Action to take when step execution fails.",
    )

    @model_validator(mode="after")
    def sync_aliases(self) -> "StepSpec":
        """Synchronize params/parameters and condition/when fields."""
        if not self.params and self.parameters:
            object.__setattr__(self, "params", self.parameters)
        elif not self.parameters and self.params:
            object.__setattr__(self, "parameters", self.params)

        if not self.condition and self.when:
            object.__setattr__(self, "condition", self.when)
        elif not self.when and self.condition:
            object.__setattr__(self, "when", self.condition)
        return self

    @field_validator("id")
    @classmethod
    def validate_step_id(cls, v: str) -> str:
        """Validate step ID matches identifier syntax rules."""
        if not is_valid_identifier(v):
            raise ValueError(
                f"Step ID '{v}' is invalid. Must match alphanumeric/underscore/hyphen ^[a-zA-Z0-9_-]+$."
            )
        return v

    @model_validator(mode="after")
    def validate_executor_parameters(self) -> "StepSpec":
        """Validate required payload parameters are present for selected executor type."""
        if self.executor_type == ExecutorType.SUBPROCESS and not self.command:
            raise ValueError(
                f"Step '{self.id}' with executor_type 'subprocess' requires 'command'."
            )
        if self.executor_type == ExecutorType.INLINE and not (
            self.function or self.callable_name or (self.module_path and self.function_name)
        ):
            raise ValueError(
                f"Step '{self.id}' with executor_type 'inline' requires function definition."
            )
        if self.executor_type == ExecutorType.PYTHON_INLINE and not (
            self.function or self.callable_name or (self.module_path and self.function_name)
        ):
            raise ValueError(
                f"Step '{self.id}' with executor_type 'python_inline' requires function definition."
            )
        if self.executor_type == ExecutorType.HTTP:
            if not self.url:
                raise ValueError(f"Step '{self.id}' with executor_type 'http' requires 'url'.")
            if not validate_http_url(self.url):
                raise ValueError(f"Step '{self.id}' contains invalid HTTP URL '{self.url}'.")
        return self


class TriggerSpec(BaseModel):
    """Specification schema for an event trigger attachment."""

    id: str = Field(
        ...,
        description="Unique trigger identifier.",
    )
    type: TriggerType = Field(
        ...,
        description="Event trigger classification.",
    )
    cron: str | None = Field(
        default=None,
        description="5-field Cron schedule string (e.g. '*/5 * * * *').",
    )
    interval_seconds: float | None = Field(
        default=None,
        gt=0.0,
        description="Fixed interval delay in seconds.",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Secret key for HMAC signature verification of incoming webhooks.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether trigger is active.",
    )

    @field_validator("id")
    @classmethod
    def validate_trigger_id(cls, v: str) -> str:
        """Validate trigger ID matches identifier syntax rules."""
        if not is_valid_identifier(v):
            raise ValueError(f"Trigger ID '{v}' is invalid. Must match ^[a-zA-Z0-9_-]+$.")
        return v

    @model_validator(mode="after")
    def validate_trigger_parameters(self) -> "TriggerSpec":
        """Validate required parameters are supplied for trigger type."""
        if self.type == TriggerType.CRON:
            if not self.cron:
                raise ValueError(f"Trigger '{self.id}' of type 'cron' requires 'cron' expression.")
            if not validate_cron_expression(self.cron):
                raise ValueError(f"Trigger '{self.id}' has invalid cron expression '{self.cron}'.")
        elif self.type == TriggerType.INTERVAL:
            if not self.interval_seconds or self.interval_seconds <= 0:
                raise ValueError(
                    f"Trigger '{self.id}' of type 'interval' requires positive 'interval_seconds'."
                )
        return self


class DAGSpec(BaseModel):
    """Root specification schema for a complete Workflow Directed Acyclic Graph."""

    id: str = Field(
        ...,
        description="Unique workflow DAG identifier.",
    )
    name: str = Field(
        default="Unnamed Workflow",
        description="Human-readable workflow title.",
    )
    description: str | None = Field(
        default=None,
        description="Detailed summary of workflow purpose.",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version string of workflow specification.",
    )
    owner: str | None = Field(
        default=None,
        description="Workflow owner email or team identifier.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Categorization tags list.",
    )
    timeout_seconds: float = Field(
        default=3600.0,
        gt=0.0,
        description="Maximum total execution timeout limit in seconds.",
    )
    max_concurrency: int = Field(
        default=10,
        ge=1,
        description="Maximum concurrent step executions allowed.",
    )
    steps: list[StepSpec] = Field(
        ...,
        min_length=1,
        description="List of task step specifications forming the workflow DAG.",
    )
    triggers: list[TriggerSpec] = Field(
        default_factory=list,
        description="List of event trigger rules attached to this workflow.",
    )

    @field_validator("id")
    @classmethod
    def validate_dag_id(cls, v: str) -> str:
        """Validate DAG ID matches identifier syntax rules."""
        if not is_valid_identifier(v):
            raise ValueError(f"DAG ID '{v}' is invalid. Must match ^[a-zA-Z0-9_-]+$.")
        return v

    def get_step(self, step_id: str) -> StepSpec | None:
        """Find and return StepSpec by step_id."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_step_ids(self) -> list[str]:
        """Return list of all step IDs in the DAG."""
        return [step.id for step in self.steps]

    def get_root_steps(self) -> list[StepSpec]:
        """Return list of root steps that have no upstream dependencies."""
        return [step for step in self.steps if not step.depends_on]
