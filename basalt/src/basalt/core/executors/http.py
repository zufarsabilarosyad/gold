"""Asynchronous HTTP API Step Executor Subsystem Module for Basalt Engine.

Provides an HTTP executor using `httpx.AsyncClient` supporting GET, POST, PUT, DELETE, PATCH,
custom headers, URL parameters, template interpolation, JSON body parsing, and status code checks.
"""

from typing import Any

import httpx

from basalt.core.dag.ast import StepSpec
from basalt.core.engine.context import ExecutionContext
from basalt.core.engine.evaluator import ExpressionEvaluator
from basalt.core.executors.base import BaseExecutor, ExecutorError
from basalt.utils.logger import get_logger
from basalt.utils.validators import validate_url

logger = get_logger(__name__)

SUPPORTED_HTTP_METHODS: set[str] = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


class HTTPExecutor(BaseExecutor):
    """Executor plugin for executing asynchronous HTTP/REST API web requests."""

    def __init__(self) -> None:
        super().__init__(executor_type="http")

    def validate_method(self, method_name: str, step_id: str) -> str:
        """Validate and normalize HTTP method string.

        Args:
            method_name: HTTP verb string.
            step_id: Step identifier.

        Returns:
            Normalized uppercase HTTP method.

        Raises:
            ExecutorError: If HTTP verb is unsupported.
        """
        upper_method = (method_name or "GET").upper().strip()
        if upper_method not in SUPPORTED_HTTP_METHODS:
            raise ExecutorError(
                step_id=step_id,
                executor_type=self.executor_type,
                message=f"Unsupported HTTP method '{method_name}'. Supported methods: {sorted(list(SUPPORTED_HTTP_METHODS))}",
            )
        return upper_method

    def build_headers(
        self,
        raw_headers: dict[str, str] | None,
        context: ExecutionContext,
    ) -> dict[str, str]:
        """Interpolate and construct HTTP request headers dictionary."""
        headers: dict[str, str] = {"User-Agent": "Basalt-Workflow-Engine/1.0"}
        if raw_headers:
            interpolated = ExpressionEvaluator.interpolate_value(raw_headers, context)
            if isinstance(interpolated, dict):
                for k, v in interpolated.items():
                    headers[str(k)] = str(v)
        return headers

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Asynchronously execute HTTP request defined in step AST.

        Args:
            step: StepSpec AST model.
            context: Active ExecutionContext.

        Returns:
            Dictionary output containing 'status_code', 'headers', 'body', 'json', and 'url'.

        Raises:
            ExecutorError: If URL is invalid, HTTP request fails, or status code is unacceptable.
            ExecutorTimeoutError: If request exceeds timeout.
        """
        self.validate_step_spec(step)

        if not step.url:
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message="HTTP step missing required 'url' parameter.",
            )

        # 1. Interpolate template expressions in URL and method
        raw_url = ExpressionEvaluator.interpolate_string(step.url, context)
        method = self.validate_method(step.method or "GET", step.id)

        if not validate_url(raw_url):
            raise ExecutorError(
                step_id=step.id,
                executor_type=self.executor_type,
                message=f"Invalid or unsafe HTTP URL '{raw_url}'.",
            )

        # 2. Interpolate headers, query parameters, and body payloads
        headers = self.build_headers(step.headers, context)

        params: dict[str, Any] = {}
        if step.query_params:
            interpolated_params = ExpressionEvaluator.interpolate_value(step.query_params, context)
            if isinstance(interpolated_params, dict):
                params = interpolated_params

        content: str | None = None
        json_payload: Any | None = None

        if step.body is not None:
            content = ExpressionEvaluator.interpolate_string(str(step.body), context)

        if step.json_payload is not None:
            json_payload = ExpressionEvaluator.interpolate_value(step.json_payload, context)

        # 3. Inner HTTP request execution wrapper
        async def _make_request() -> dict[str, Any]:
            timeout_sec = step.timeout_seconds if step.timeout_seconds else 30.0

            logger.debug(f"Step '{step.id}' making HTTP {method} request to '{raw_url}'")

            try:
                (
                    status_code,
                    response_text,
                    resp_headers,
                    parsed_json,
                ) = await make_http_request_direct(
                    url=raw_url,
                    method=method,
                    headers=headers,
                    params=params,
                    content=content,
                    json_payload=json_payload,
                    timeout_seconds=timeout_sec,
                )

                logger.debug(
                    f"Step '{step.id}' HTTP {method} response from '{raw_url}': status {status_code}"
                )

                # Determine status code acceptability
                allowed_statuses = step.expected_status_codes or list(range(200, 300))
                if status_code not in allowed_statuses:
                    error_msg = (
                        f"HTTP request to '{raw_url}' returned unexpected status code {status_code}. "
                        f"Response body: {response_text[:300]}"
                    )
                    raise ExecutorError(
                        step_id=step.id,
                        executor_type=self.executor_type,
                        message=error_msg,
                        details={
                            "status_code": status_code,
                            "url": raw_url,
                            "method": method,
                            "response_body": response_text[:1000],
                            "headers": resp_headers,
                        },
                    )

                output_data: dict[str, Any] = {
                    "status_code": status_code,
                    "url": raw_url,
                    "method": method,
                    "body": response_text,
                    "headers": resp_headers,
                }

                if parsed_json is not None:
                    output_data["json"] = parsed_json
                    if isinstance(parsed_json, dict):
                        for k, v in parsed_json.items():
                            if k not in output_data:
                                output_data[k] = v

                return self.sanitize_output(output_data)

            except httpx.TimeoutException as exc:
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"HTTP request to '{raw_url}' timed out: {exc}",
                ) from exc
            except httpx.RequestError as exc:
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"HTTP network request to '{raw_url}' failed: {exc}",
                ) from exc
            except ExecutorError:
                raise
            except Exception as exc:
                raise ExecutorError(
                    step_id=step.id,
                    executor_type=self.executor_type,
                    message=f"Unexpected HTTP execution error for '{raw_url}': {exc}",
                ) from exc

        # 4. Timeout execution wrapper
        timeout = step.timeout_seconds if step.timeout_seconds else 60.0
        return await self.execute_with_timeout(
            _make_request(),
            timeout_seconds=timeout,
            step_id=step.id,
        )


async def make_http_request_direct(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    content: str | None = None,
    json_payload: Any | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[int, str, dict[str, str], Any | None]:
    """Execute direct HTTP request and return (status_code, body_text, headers_dict, parsed_json).

    Args:
        url: Target HTTP URL string.
        method: HTTP method verb.
        headers: Request headers dictionary.
        params: URL query parameters dictionary.
        content: Raw body string.
        json_payload: JSON-serializable body payload.
        timeout_seconds: Request timeout in seconds.

    Returns:
        Tuple of (status_code, response_text, response_headers, parsed_json_or_none).
    """
    httpx_timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=httpx_timeout, follow_redirects=True) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            content=content,
            json=json_payload,
        )

    status_code = response.status_code
    response_text = response.text.strip()
    resp_headers = {k: v for k, v in response.headers.items()}

    parsed_json: Any | None = None
    try:
        parsed_json = response.json()
    except Exception:
        parsed_json = None

    return status_code, response_text, resp_headers, parsed_json
