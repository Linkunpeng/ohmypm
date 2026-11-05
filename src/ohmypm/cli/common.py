"""Shared CLI plumbing: options, output, input, errors."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, NoReturn

import click
import typer
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from typer.core import TyperGroup

from ohmypm.core.dates import parse_when  # noqa: F401 - re-exported for commands
from ohmypm.core.errors import OhmypmError, ValidationError


class _State:
    json: bool = False


STATE = _State()


def _set_json(value: bool) -> bool:
    if value:
        STATE.json = True
    return value


# ------------------------------------------------------------------ options

JsonOpt = Annotated[
    bool,
    typer.Option(
        "--json", help="Machine-readable JSON on stdout (errors as JSON on stderr).", callback=_set_json
    ),
]
ProjectOpt = Annotated[
    str | None,
    typer.Option(
        "--project",
        "-p",
        help="Project id, id prefix or name. Default: detect from the working directory.",
        envvar="OHMYPM_PROJECT",
        show_envvar=True,
    ),
]
CwdOpt = Annotated[
    Path | None,
    typer.Option(
        "--cwd", "-C", help="Workspace directory used for project detection (default: current directory)."
    ),
]
AuthorOpt = Annotated[
    str | None,
    typer.Option(
        "--author", help="Who records this (user or agent name).", envvar="OHMYPM_AUTHOR", show_envvar=True
    ),
]


def workspace(cwd: Path | None) -> str:
    return str(cwd) if cwd is not None else os.getcwd()


# ---------------------------------------------------------------- services


@lru_cache(maxsize=1)
def get_service():  # noqa: ANN201 - lazily imported type
    from ohmypm.core.service import MemoryService

    return MemoryService()


def reset_service() -> None:
    """Forget the cached service (tests switch data directories)."""
    if get_service.cache_info().currsize:
        get_service().db.dispose()
    get_service.cache_clear()


# ------------------------------------------------------------------ output


def to_jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    if isinstance(data, list):
        return [to_jsonable(x) for x in data]
    if isinstance(data, tuple):
        return [to_jsonable(x) for x in data]
    if isinstance(data, dict):
        return {k: to_jsonable(v) for k, v in data.items()}
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, Path):
        return str(data)
    return data


def emit_json(data: Any) -> None:
    sys.stdout.write(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2) + "\n")


def out(text: str = "") -> None:
    typer.echo(text)


def err(text: str) -> None:
    typer.echo(text, err=True)


def fail(message: str, *, code: str = "error", exit_code: int = 1, details: dict | None = None) -> NoReturn:
    report_error({"code": code, "message": message, **({"details": details} if details else {})})
    raise typer.Exit(exit_code)


def report_error(payload: dict[str, Any]) -> None:
    if STATE.json:
        sys.stderr.write(json.dumps({"error": payload}, ensure_ascii=False) + "\n")
        return
    err(f"Error: {payload['message']}")
    details = payload.get("details") or {}
    if "hint" in details:
        err(f"Hint: {details['hint']}")
    if "allowed" in details:
        allowed = details["allowed"]
        err("Allowed: " + (", ".join(map(str, allowed)) if isinstance(allowed, list) else str(allowed)))
    if "candidates" in details:
        for c in details["candidates"]:
            err(f"  - {c.get('name')} ({c.get('id')}) {c.get('root_path', '')}")


def local_time(value: datetime | str | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------- input


def read_text_input(
    content: str | None, file: Path | None, stdin: bool, *, what: str = "content"
) -> str | None:
    """Exactly one of --content/--file/--stdin (or none -> None)."""
    given = [x for x in (content is not None, file is not None, stdin) if x]
    if len(given) > 1:
        raise ValidationError(f"Use only one of --{what}, --file and --stdin")
    if content is not None:
        return content
    if file is not None:
        if str(file) == "-":
            return sys.stdin.read()
        try:
            return file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValidationError(f"File not found: {file}") from exc
        except UnicodeDecodeError as exc:
            raise ValidationError(f"File is not valid UTF-8: {file}") from exc
    if stdin:
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode()
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("stdin is not valid UTF-8") from exc
    return None


def parse_meta(pairs: list[str] | None) -> dict[str, Any]:
    """``key=value`` pairs; values are parsed as JSON when possible."""
    result: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValidationError(f"Invalid --meta '{pair}', expected key=value")
        try:
            result[key.strip()] = json.loads(value)
        except json.JSONDecodeError:
            result[key.strip()] = value
    return result


def confirm_or_fail(question: str, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty() or STATE.json:
        raise ValidationError(f"{question} Re-run with --yes to confirm.")
    if not typer.confirm(question, default=False):
        raise typer.Exit(1)


# ---------------------------------------------------------------- errors


class OhmypmGroup(TyperGroup):
    """Root command group that converts ohmypm errors into clean exits."""

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except OhmypmError as exc:
            report_error(exc.to_dict())
            raise typer.Exit(exc.exit_code) from None
        except PydanticValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg'].removeprefix('Value error, ')}"
                for e in exc.errors()
            ]
            report_error({"code": "validation_error", "message": "; ".join(problems)})
            raise typer.Exit(ValidationError.exit_code) from None
        except KeyboardInterrupt:
            err("Interrupted")
            raise typer.Exit(130) from None

    def main(self, *args: Any, **kwargs: Any) -> Any:
        STATE.json = False
        return super().main(*args, **kwargs)
