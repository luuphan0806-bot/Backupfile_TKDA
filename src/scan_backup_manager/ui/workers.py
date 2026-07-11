from __future__ import annotations

import traceback
from typing import Callable

import flet as ft

from ..logging_config import get_logger


def run_worker(
    page: ft.Page,
    func: Callable[[], object],
    *,
    on_success: Callable[[object], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Run `func` on the page's background executor thread (per Flet's own
    `Page.run_thread` helper, which marshals control updates back safely --
    this is the supported alternative to raw `threading.Thread` + manual
    synchronization)."""

    def _target() -> None:
        try:
            result = func()
        except Exception:  # noqa: BLE001 - top-level worker boundary: log + surface via on_error
            get_logger().exception("Background task failed: %s", func)
            if on_error:
                on_error(traceback.format_exc())
            return
        if on_success:
            on_success(result)

    page.run_thread(_target)
