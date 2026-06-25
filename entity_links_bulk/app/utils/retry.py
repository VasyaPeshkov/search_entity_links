from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import requests

T = TypeVar("T")


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status

    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception) and cause is not exc:
        return _status_code(cause)

    return None


def is_transient_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (requests.Timeout, requests.ConnectionError),
    ):
        return True

    return _status_code(exc) in {
        408, 425, 429, 500, 502, 503, 504
    }


def call_with_retry(
    callback: Callable[[], T],
    max_attempts: int,
    base_delay_seconds: float,
) -> T:
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return callback()
        except Exception as exc:
            last_error = exc

            if not is_transient_error(exc):
                raise

            if attempt >= max_attempts - 1:
                break

            delay = (
                base_delay_seconds * (2 ** attempt)
                + random.uniform(0.0, 0.8)
            )
            time.sleep(delay)

    assert last_error is not None
    raise last_error
