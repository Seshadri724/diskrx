import os
import tempfile
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import click


class ExitCode(IntEnum):
    SUCCESS = 0
    RUNTIME_ERROR = 1
    VALIDATION_ERROR = 2
    UNSAFE_OPERATION = 3
    CI_FAILURE = 4
    INTERRUPTED = 130


class DxCliError(click.ClickException):
    def __init__(self, message: str, exit_code: ExitCode = ExitCode.RUNTIME_ERROR):
        super().__init__(message)
        self.exit_code = int(exit_code)


def ensure_dx_dir() -> str:
    dx_dir = os.path.join(os.path.expanduser("~"), ".dx")
    if not os.path.exists(dx_dir):
        os.makedirs(dx_dir, mode=0o700, exist_ok=True)
    elif os.name != "nt":
        os.chmod(dx_dir, 0o700)
    return dx_dir


def secure_path(path: str, file_mode: Optional[int] = None) -> str:
    if os.name != "nt" and file_mode is not None and os.path.exists(path):
        os.chmod(path, file_mode)
    return path


def atomic_write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def resolve_partition_for_path(provider, path: str):
    normalized = os.path.abspath(path)
    normalized_cmp = normalized.lower() if os.name == "nt" else normalized
    best_match = None
    for part in provider.get_partitions():
        mount = part.mountpoint.lower() if os.name == "nt" else part.mountpoint
        # Proper path boundary check: mount must be an exact prefix at a separator
        mount_with_sep = mount.rstrip(os.sep) + os.sep
        if normalized_cmp == mount or normalized_cmp.startswith(mount_with_sep):
            if best_match is None or len(part.mountpoint) > len(best_match.mountpoint):
                best_match = part
    return best_match


def validate_webhook_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DxCliError(
            f"Invalid webhook URL: {url}. Only absolute http/https URLs are allowed.",
            ExitCode.VALIDATION_ERROR,
        )
    from .outputs.notifier import validate_webhook_destination

    is_valid, error, _ = validate_webhook_destination(url)
    if not is_valid:
        raise DxCliError(f"Invalid webhook URL: {error}", ExitCode.VALIDATION_ERROR)
    return url


def validate_bind_address(bind: str) -> str:
    if not bind:
        raise DxCliError("Bind address cannot be empty.", ExitCode.VALIDATION_ERROR)
    return bind


def ensure_within_scope(
    path: str, allowed_roots: Iterable[str], follow_symlinks: bool = False
) -> str:
    candidate = Path(path)
    resolved_candidate = (
        candidate.resolve(strict=False) if follow_symlinks else candidate.absolute()
    )
    for root in allowed_roots:
        resolved_root = (
            Path(root).resolve(strict=False)
            if follow_symlinks
            else Path(root).absolute()
        )
        try:
            resolved_candidate.relative_to(resolved_root)
            return str(resolved_candidate)
        except ValueError:
            continue
    raise DxCliError(
        f"Refusing to operate on path outside the allowed scope: {path}",
        ExitCode.UNSAFE_OPERATION,
    )
