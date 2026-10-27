"""Mini player (bottom-left): plays files from the library."""

from __future__ import annotations

import flet as ft

from .. import tagger
from ..audio import AudioError, Mpv
from ..i18n import t
from ..library import LibTrack
from . import theme as th


class Player:
    def __init__(self, page: ft.Page):
        self.page = page
        self.queue: list[LibTrack] = []
        self.index = -1
        self.playing = False
        self.duration_ms = 0
        self.position_ms = 0
        self._seeking = False
        self.volume = 0.8
        self.audio = Mpv(self._on_event)

        self.cover = ft.Container(
            width=52, height=52, bgcolor=th.SURFACE_HI, border_radius=th.SHARP,
            alignment=ft.Alignment.CENTER, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Icon(ft.Icons.MUSIC_NOTE_ROUNDED, color=th.FAINT, size=22),
        )
        self.title = ft.Text(t("nothing_playing"), size=12, color=th.TEXT, font_family=th.FONT_MEDIUM,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.artist = ft.Text("", size=10, color=th.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.pos_text = th.label("0:00", 10)
        self.dur_text = th.label("0:00", 10)
        self.seek = ft.Slider(min=0, max=1, value=0, height=18, active_color=th.ACCENT, inactive_color=th.BORDER,
                              thumb_color=th.TEXT, on_change_start=self._seek_start, on_change_end=self._seek_end,
                              expand=True)
        self.play_btn = th.circle_button(ft.Icons.PLAY_ARROW_ROUNDED, self._toggle, size=38, tooltip=None)
        self.vol = ft.Slider(min=0, max=1, value=self.volume, width=90, height=18, active_color=th.TEXT,
                             inactive_color=th.BORDER, thumb_color=th.TEXT, on_change=self._on_volume)

        self.view = ft.Container(
            bgcolor=th.SURFACE,
            border=ft.Border.only(top=ft.BorderSide(1, th.BORDER)),
            padding=ft.Padding.only(left=12, right=12, top=10, bottom=8),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Row([self.cover, ft.Column([self.title, self.artist], spacing=2, expand=True, tight=True)],
                           spacing=10),
                    ft.Row([self.pos_text, self.seek, self.dur_text], spacing=0,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Row(
                        [
                            th.icon_btn(ft.Icons.SKIP_PREVIOUS_ROUNDED, self._prev, color=th.TEXT),
                            self.play_btn,
                            th.icon_btn(ft.Icons.SKIP_NEXT_ROUNDED, self._next, color=th.TEXT),
                            ft.Container(expand=True),
                            ft.Icon(ft.Icons.VOLUME_UP_ROUNDED, size=14, color=th.MUTED),
                            self.vol,
                        ],
                        spacing=2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
            ),
        )

    # ---------- public ----------

    async def play_list(self, tracks: list[LibTrack], start: int = 0) -> None:
        if not tracks:
            return
        self.queue = list(tracks)
        self._load(start)

    def close(self) -> None:
        self.audio.stop()

    # ---------- internals ----------

    def _load(self, index: int) -> None:
        if not (0 <= index < len(self.queue)):
            return
        self.index = index
        tr = self.queue[index]
        self.title.value = tr.title
        self.artist.value = f"{tr.artist} · {tr.album}"
        cover = tagger.read_cover(tr.path)
        self.cover.content = (ft.Image(src=cover, width=52, height=52, fit=ft.BoxFit.COVER) if cover
                              else ft.Icon(ft.Icons.MUSIC_NOTE_ROUNDED, color=th.FAINT, size=22))
        self.position_ms = 0
        self.duration_ms = 0
        self.seek.value = 0
        self.pos_text.value = self.dur_text.value = "0:00"
        try:
            self.audio.set_volume(self.volume)
            self.audio.load(str(tr.path))
        except AudioError as e:
            self.title.value = t("err_" + str(e))
            self.artist.value = ""
            self._set_playing(False)
            return
        self._set_playing(True)

    def _set_playing(self, playing: bool) -> None:
        self.playing = playing
        self.play_btn.content.icon = ft.Icons.PAUSE_ROUNDED if playing else ft.Icons.PLAY_ARROW_ROUNDED
        self.view.update()

    def _toggle(self, e=None):
        if self.index < 0:
            return
        self.audio.set_paused(self.playing)
        self._set_playing(not self.playing)

    def _next(self, e=None):
        if self.index + 1 < len(self.queue):
            self._load(self.index + 1)

    def _prev(self, e=None):
        if self.position_ms > 3000 or self.index == 0:
            self.audio.seek(0)
        else:
            self._load(self.index - 1)

    def _on_volume(self, e):
        self.volume = float(e.control.value)
        self.audio.set_volume(self.volume)

    def _seek_start(self, e):
        self._seeking = True

    def _seek_end(self, e):
        self._seeking = False
        if self.duration_ms:
            self.audio.seek(float(e.control.value) * self.duration_ms / 1000)

    # mpv events arrive on its reader thread; hop onto the UI loop.
    def _on_event(self, name: str, value) -> None:
        try:
            self.page.run_task(self._apply_event, name, value)
        except RuntimeError:
            pass  # page already closed

    async def _apply_event(self, name: str, value) -> None:
        if name == "duration":
            self.duration_ms = int(value * 1000)
            self.dur_text.value = th.fmt_time(value)
        elif name == "position":
            self.position_ms = int(value * 1000)
            self.pos_text.value = th.fmt_time(value)
            if self.duration_ms and not self._seeking:
                self.seek.value = min(self.position_ms / self.duration_ms, 1.0)
        elif name == "paused":
            if value == self.playing:
                self.playing = not value
                self.play_btn.content.icon = ft.Icons.PLAY_ARROW_ROUNDED if value else ft.Icons.PAUSE_ROUNDED
        elif name == "ended":
            if self.index + 1 < len(self.queue):
                self._load(self.index + 1)
                return
            self.playing = False
            self.play_btn.content.icon = ft.Icons.PLAY_ARROW_ROUNDED
        try:
            self.view.update()
        except RuntimeError:
            pass
