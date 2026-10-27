"""Side panel with a draggable edge: resize it, drag it shut, or close it with a button."""

from __future__ import annotations

from typing import Callable

import flet as ft

from . import theme as th

RAIL = 36
HANDLE = 9
SNAP_CLOSE = 70  # dragged this far past the minimum width: close the panel


class Sidebar:
    def __init__(
        self,
        side: str,  # "left" | "right"
        content: ft.Control,
        width: int,
        opened: bool,
        min_width: int,
        max_width: Callable[[], float],
        on_save: Callable[[int, bool], None],
        rail_icon,
        rail_tooltip: str,
        on_open: Callable[["Sidebar"], None] | None = None,
    ):
        self.side = side
        self.min_width = min_width
        self.max_width = max_width
        self.on_save = on_save
        self.on_open = on_open
        width = max(min_width, width)
        self.width = width
        self.opened = opened
        self._raw = float(width)

        self.panel = ft.Container(width=width, bgcolor=th.PANEL, content=content)
        self.line = ft.Container(width=1, bgcolor=th.BORDER)
        self.handle = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            drag_interval=16,
            on_horizontal_drag_start=self._drag_start,
            on_horizontal_drag_update=self._drag,
            on_horizontal_drag_end=self._drag_end,
            on_double_tap=lambda e: self.set_open(False),
            on_enter=lambda e: self._highlight(True),
            on_exit=lambda e: self._highlight(False),
            content=ft.Container(width=HANDLE, alignment=ft.Alignment.CENTER, bgcolor=th.BG, content=self.line),
        )
        edge = ft.BorderSide(1, th.BORDER)
        self.rail = ft.Container(
            width=RAIL, bgcolor=th.PANEL, padding=ft.Padding.only(top=14),
            border=ft.Border.only(right=edge) if side == "left" else ft.Border.only(left=edge),
            alignment=ft.Alignment.TOP_CENTER,
            content=th.icon_btn(rail_icon, lambda e: self.set_open(True), tooltip=rail_tooltip, color=th.ACCENT),
        )
        self.controls = [self.panel, self.handle, self.rail] if side == "left" else [self.rail, self.handle, self.panel]
        self._apply()

    @property
    def taken(self) -> float:
        """Horizontal space the sidebar uses right now."""
        return self.width + HANDLE if self.opened else RAIL

    def _apply(self) -> None:
        self.panel.visible = self.handle.visible = self.opened
        self.rail.visible = not self.opened
        self.panel.width = self.width

    def set_open(self, opened: bool, update: bool = True) -> None:
        if opened and not self.opened and self.on_open:
            self.on_open(self)  # lets the others make room
        self.opened = opened
        if opened:
            self.width = max(self.min_width, min(self.width, int(self.max_width())))
        self._apply()
        self.on_save(self.width, self.opened)
        if update:
            self.panel.page.update()

    def fit(self) -> None:
        """The window got narrower: shrink so the center keeps its room."""
        if self.opened and self.width > self.max_width():
            self.width = max(self.min_width, int(self.max_width()))
            self.panel.width = self.width

    def _highlight(self, on: bool) -> None:
        self.line.bgcolor = th.ACCENT if on else th.BORDER
        self.line.width = 2 if on else 1
        self.line.update()

    def _drag_start(self, e) -> None:
        self._raw = float(self.width)

    def _drag(self, e: ft.DragUpdateEvent) -> None:
        d = e.primary_delta if e.primary_delta is not None else (e.local_delta.x if e.local_delta else 0)
        self._raw += d if self.side == "left" else -d
        w = int(max(self.min_width, min(self._raw, self.max_width())))
        if w != self.width:
            self.width = self.panel.width = w
            self.panel.update()

    def _drag_end(self, e) -> None:
        if self._raw < self.min_width - SNAP_CLOSE:
            self.set_open(False)
        else:
            self.on_save(self.width, self.opened)
