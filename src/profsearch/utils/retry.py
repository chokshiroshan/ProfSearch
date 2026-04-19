"""Retry helpers for sync and async operations."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


async def async_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay_seconds: float = 0.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except retry_on:
            attempt += 1
            if attempt > retries:
                raise
            await asyncio.sleep(base_delay_seconds * (2 ** (attempt - 1)))


def retry(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    base_delay_seconds: float = 0.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except retry_on:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
