"""Right sidebar next to the settings: the phone over ADB, sending music to it."""

from __future__ import annotations

from typing import Callable

import flet as ft

from ..config import PHONE_DIR, Settings
from ..i18n import t
from . import theme as th


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class PhonePanel:
    def __init__(self, settings: Settings, actions: dict[str, Callable], on_close: Callable[[], None]):
        self.s = settings
        self.actions = actions

        # --- connection
        self.status = ft.Text(t("phone_none"), size=11, color=th.MUTED)
        self.icon = ft.Icon(ft.Icons.PHONE_ANDROID_ROUNDED, size=16, color=th.FAINT)
        self.details = th.label("", 10, visible=False)
        self.address = th.field(value=self.s.phone_address, hint_text="192.168.1.5:5555", expand=True,
                                on_change=self._on_address, on_submit=lambda e: self._connect())
        connection = th.section(t("sec_connection"), [
            ft.Row([self.icon, ft.Container(self.status, expand=True),
                    th.icon_btn(ft.Icons.REFRESH_ROUNDED, lambda e: actions["refresh"](), tooltip=t("phone_refresh"))],
                   spacing=8),
            self.details,
            th.label(t("wifi_adb"), 10, th.TEXT),
            ft.Row([self.address, th.capsule(t("wifi_connect"), lambda e: self._connect(), icon=ft.Icons.WIFI_ROUNDED)],
                   spacing=6),
            th.label(t("wifi_hint"), 10, th.FAINT),
        ])

        # --- sending
        self.picked = th.label(t("picked_none"), 11)
        self.send_picked = th.capsule(t("send_picked"), lambda e: actions["push_selected"](),
                                      icon=ft.Icons.UPLOAD_ROUNDED)
        self.unpick = th.capsule(t("unpick"), lambda e: actions["clear_selection"](), icon=ft.Icons.CLOSE_ROUNDED)
        self.dir = th.field(value=self.s.phone_dir, label=t("phone_dir"), on_change=self._on_dir, expand=True)
        self.mode_row = ft.Row(spacing=6)
        self.mode_hint = th.label("", 10)
        self._render_mode()
        sending = th.section(t("sec_sending"), [
            self.picked,
            ft.Row([self.send_picked, self.unpick], spacing=6, wrap=True, run_spacing=6),
            ft.Row([th.capsule(t("phone_send_all"), lambda e: actions["push_all"](), icon=ft.Icons.LIBRARY_MUSIC_ROUNDED)]),
            th.label(t("send_skips_hint"), 10, th.FAINT),
            ft.Row([self.dir, th.icon_btn(ft.Icons.FOLDER_OPEN_ROUNDED, lambda e: actions["browse_dir"](),
                                          tooltip=t("phone_browse"))], spacing=4),
            th.label(t("phone_mode"), 10),
            self.mode_row,
            self.mode_hint,
            self._switch(t("phone_covers"), self.s.phone_covers, self._on_covers),
            self._switch(t("phone_auto"), self.s.phone_auto, self._on_auto),
            th.label(t("phone_auto_hint"), 10),
        ])

        # --- what is on the phone
        self.compare_text = th.label(t("compare_hint"), 11)
        on_phone = th.section(t("sec_on_phone"), [
            self.compare_text,
            ft.Row([th.capsule(t("compare"), lambda e: actions["compare"](), icon=ft.Icons.COMPARE_ARROWS_ROUNDED)]),
        ])

        self.view = ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Container(
                    ft.Row([th.heading(t("phone"), 11), ft.Container(expand=True),
                            th.icon_btn(ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_ROUNDED, lambda e: on_close(),
                                        tooltip=t("hide_panel"), size=16)],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.only(left=4, right=4),
                ),
                ft.ListView(expand=True, spacing=10, padding=ft.Padding.only(right=8, bottom=12),
                            controls=[connection, sending, on_phone]),
            ],
        )
        self.set_picked(0, 0)

    @staticmethod
    def _switch(text: str, value: bool, on_change) -> ft.Row:
        return ft.Row([ft.Text(text, size=12, color=th.TEXT, expand=True),
                       ft.Switch(value=value, active_color=th.ACCENT, on_change=on_change)])

    # ---------- shown state ----------

    def set_status(self, text: str, ok: bool, info: dict | None = None) -> None:
        self.status.value = text
        self.status.color = th.TEXT if ok else th.MUTED
        self.icon.color = th.ACCENT if ok else th.FAINT
        parts = []
        if ok and info:
            if info.get("android"):
                parts.append(f"Android {info['android']}")
            if "battery" in info:
                parts.append(t("battery", n=info["battery"]))
            if "free" in info:
                parts.append(t("free_space", free=fmt_size(info["free"]), total=fmt_size(info["total"])))
        self.details.value = "  ·  ".join(parts)
        self.details.visible = bool(parts)

    def set_picked(self, tracks: int, size: int) -> None:
        self.picked.value = t("picked", n=tracks, size=fmt_size(size)) if tracks else t("picked_none")
        self.picked.color = th.TEXT if tracks else th.MUTED
        self.send_picked.disabled = self.unpick.disabled = not tracks
        self.send_picked.opacity = self.unpick.opacity = 1 if tracks else 0.4

    def set_compare(self, text: str) -> None:
        self.compare_text.value = text

    def _refresh(self) -> None:
        try:
            self.view.update()
        except RuntimeError:
            pass  # sidebar closed / not mounted yet

    # ---------- settings ----------

    def _render_mode(self) -> None:
        move = self.s.phone_move
        self.mode_row.controls = [
            th.capsule(t("mode_copy"), lambda e: self._set_mode(False), selected=not move, icon=ft.Icons.COPY_ROUNDED),
            th.capsule(t("mode_move"), lambda e: self._set_mode(True), selected=move,
                       icon=ft.Icons.DRIVE_FILE_MOVE_ROUNDED),
        ]
        self.mode_hint.value = t("mode_move_hint") if move else t("mode_copy_hint")
        self.mode_hint.color = th.ERROR if move else th.MUTED

    def _set_mode(self, move: bool) -> None:
        self.s.phone_move = move
        self.s.save()
        self._render_mode()
        self._refresh()

    def set_dir(self, path: str) -> None:
        self.s.phone_dir = path
        self.s.save()
        self.dir.value = path

    def _on_dir(self, e):
        self.s.phone_dir = (e.control.value or "").strip() or PHONE_DIR
        self.s.save()

    def _on_address(self, e):
        self.s.phone_address = (e.control.value or "").strip()
        self.s.save()

    def _connect(self) -> None:
        if self.s.phone_address:
            self.actions["connect"](self.s.phone_address)

    def _on_covers(self, e):
        self.s.phone_covers = bool(e.control.value)
        self.s.save()

    def _on_auto(self, e):
        self.s.phone_auto = bool(e.control.value)
        self.s.save()
