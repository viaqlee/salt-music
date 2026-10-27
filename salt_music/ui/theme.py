"""Look & feel: monochrome, one contrast blue, capsules / circles / sharp squares."""

from __future__ import annotations

import flet as ft

BG = "#0A0A0B"
PANEL = "#111113"
SURFACE = "#18181B"
SURFACE_HI = "#222226"
BORDER = "#2C2C31"
TEXT = "#EDEDEF"
MUTED = "#8B8B93"
FAINT = "#55555C"
ACCENT = "#38BDF8"
ACCENT_DIM = "#0C3A52"
ERROR = "#FF5C7A"
OK = "#EDEDEF"

FONT = "JetBrains Mono"
FONT_BOLD = "JetBrains Mono Bold"
FONT_MEDIUM = "JetBrains Mono Medium"

FONTS = {
    FONT: "fonts/JetBrainsMono-Regular.ttf",
    FONT_MEDIUM: "fonts/JetBrainsMono-Medium.ttf",
    FONT_BOLD: "fonts/JetBrainsMono-Bold.ttf",
}

CAPSULE = 999
SHARP = 2


def theme() -> ft.Theme:
    return ft.Theme(
        font_family=FONT,
        color_scheme=ft.ColorScheme(
            primary=ACCENT,
            on_primary=BG,
            primary_container=ACCENT_DIM,
            on_primary_container=ACCENT,
            secondary=TEXT,
            on_secondary=BG,
            surface=PANEL,
            on_surface=TEXT,
            on_surface_variant=MUTED,
            surface_container=SURFACE,
            surface_container_high=SURFACE_HI,
            surface_container_highest=SURFACE_HI,
            surface_container_low=PANEL,
            outline=BORDER,
            outline_variant=BORDER,
            error=ERROR,
        ),
        scaffold_bgcolor=BG,
        visual_density=ft.VisualDensity.COMPACT,
    )


def label(text: str, size: float = 11, color: str = MUTED, **kw) -> ft.Text:
    return ft.Text(text, size=size, color=color, **kw)


def heading(text: str, size: float = 12) -> ft.Text:
    return ft.Text(text.upper(), size=size, color=TEXT, font_family=FONT_BOLD, style=ft.TextStyle(letter_spacing=1.5))


def capsule(text: str, on_click=None, selected: bool = False, icon=None, tooltip=None, dense: bool = True) -> ft.Container:
    fg = BG if selected else TEXT
    row = [ft.Icon(icon, size=14, color=fg)] if icon else []
    row.append(ft.Text(text, size=11, color=fg, font_family=FONT_MEDIUM))
    return ft.Container(
        content=ft.Row(row, spacing=6, tight=True),
        bgcolor=ACCENT if selected else SURFACE_HI,
        border=ft.Border.all(1, ACCENT if selected else BORDER),
        border_radius=CAPSULE,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4 if dense else 8),
        on_click=on_click,
        tooltip=tooltip,
        ink=True,
    )


def status_chip(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=10, color=color, font_family=FONT_MEDIUM),
        border=ft.Border.all(1, color),
        border_radius=CAPSULE,
        padding=ft.Padding.symmetric(horizontal=8, vertical=1),
    )


def circle_button(icon, on_click=None, size: float = 40, filled: bool = True, tooltip=None, icon_size=None) -> ft.Container:
    return ft.Container(
        content=ft.Icon(icon, size=icon_size or size * 0.5, color=BG if filled else TEXT),
        width=size,
        height=size,
        bgcolor=ACCENT if filled else SURFACE_HI,
        border=None if filled else ft.Border.all(1, BORDER),
        shape=ft.BoxShape.CIRCLE,
        alignment=ft.Alignment.CENTER,
        on_click=on_click,
        tooltip=tooltip,
        ink=True,
    )


def icon_btn(icon, on_click=None, tooltip=None, color=MUTED, size=18) -> ft.IconButton:
    return ft.IconButton(icon=icon, icon_size=size, icon_color=color, on_click=on_click, tooltip=tooltip,
                         style=ft.ButtonStyle(shape=ft.CircleBorder(), padding=6))


def section(title: str, controls: list[ft.Control]) -> ft.Container:
    return ft.Container(
        content=ft.Column([heading(title, 11), *controls], spacing=10),
        bgcolor=SURFACE,
        border=ft.Border.all(1, BORDER),
        border_radius=SHARP,
        padding=14,
    )


def field(**kw) -> ft.TextField:
    defaults = dict(
        text_size=12,
        dense=True,
        border_color=BORDER,
        focused_border_color=ACCENT,
        border_radius=SHARP,
        bgcolor=PANEL,
        cursor_color=ACCENT,
        content_padding=ft.Padding.symmetric(horizontal=10, vertical=10),
    )
    defaults.update(kw)
    return ft.TextField(**defaults)


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "--:--"
    sec = int(max(sec, 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def fmt_speed(bps: float | None) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"
