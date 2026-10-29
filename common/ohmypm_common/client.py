"""Thin HTTP clients for the ohmypm REST API (sync for the CLI, async for the runner)."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _raise_for_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    code, message, details = "http_error", response.reason_phrase or "error", None
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = str(err.get("code", code))
            message = str(err.get("message", message))
            details = err.get("details")
    except ValueError:
        message = response.text[:500] or message
    raise ApiError(response.status_code, code, message, details)


def _headers(token: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "ohmypm-client/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=_headers(token), timeout=timeout, transport=transport
        )

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        _raise_for_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def patch(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


class AsyncApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=_headers(token), timeout=timeout, transport=transport
        )

    async def __aenter__(self) -> AsyncApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, path, **kwargs)
        _raise_for_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return await self.request("POST", path, json=json, **kwargs)
