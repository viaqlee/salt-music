"""Right sidebar: download settings."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

import flet as ft

from .. import desktop, naming
from ..downloader import cookie_file_status, cookie_status
from ..paths import IS_WINDOWS
from ..config import BROWSERS, DEFAULT_FILENAME, DEFAULT_TEMPLATES, FORMATS, KINDS, Settings
from ..i18n import t
from . import theme as th

PRESETS = [
    "{genre}/{artist}/{album}",
    "{artist}/{album}",
    "{artist}/{year} — {album}",
    "{genre}/{artist}/{year} — {album}",
    "{genre}/{artist}/Singles",
    "{artist}/Singles",
]
SAMPLE = {
    "genre": "Britpop", "artist": "Oasis", "year": "1994", "title": "Supersonic",
}
SAMPLE_ALBUM = {"album": "Definitely Maybe", "ep": "Whatever EP", "single": "Supersonic", "track": "Supersonic",
                "video": "Videos"}


class SettingsPanel:
    def __init__(
        self,
        page: ft.Page,
        settings: Settings,
        file_picker: ft.FilePicker,
        on_change: Callable[[], None],
        on_language: Callable[[str], None],
        actions: dict[str, Callable],
        on_close: Callable[[], None] | None = None,
    ):
        self.page = page
        self.s = settings
        self.picker = file_picker
        self.on_change = on_change
        self.on_language = on_language
        self.actions = actions
        self.kind = "album"

        # --- folder
        self.folder_text = ft.Text(self._short_path(self.s.music_dir), size=11, color=th.TEXT, selectable=True,
                                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        folder = th.section(t("sec_folder"), [
            ft.Row([ft.Icon(ft.Icons.FOLDER_ROUNDED, size=16, color=th.ACCENT), ft.Container(self.folder_text, expand=True)],
                   spacing=8),
            ft.Row([th.capsule(t("choose"), self._pick_folder, icon=ft.Icons.FOLDER_OPEN_ROUNDED),
                    th.capsule(t("open_folder"), self._open_folder, icon=ft.Icons.OPEN_IN_NEW_ROUNDED)], spacing=6),
        ])

        # --- format
        self.format_hint = th.label("", 10)
        self.format_btn = ft.SegmentedButton(
            segments=[ft.Segment(value=f, label=ft.Text(f.upper(), size=11)) for f in FORMATS],
            selected=[self.s.audio_format],
            show_selected_icon=False,
            on_change=self._on_format,
            style=ft.ButtonStyle(shape=ft.StadiumBorder(), padding=ft.Padding.symmetric(horizontal=6)),
        )
        self._format_hint()
        fmt = th.section(t("sec_format"), [ft.Row([self.format_btn], scroll=ft.ScrollMode.AUTO), self.format_hint])

        # --- layout
        self.kind_row = ft.Row(spacing=6, wrap=True, run_spacing=6)
        self.template = th.field(value=self.s.templates[self.kind], label=t("path_template"),
                                 on_change=self._on_template)
        self.filename = th.field(value=self.s.filename_template, label=t("file_template"),
                                 on_change=self._on_filename)
        self.preview = ft.Text("", size=10, color=th.ACCENT, selectable=True)
        self.preset_row = ft.Row(spacing=6, wrap=True, run_spacing=6)
        tokens = ft.Row(spacing=6, wrap=True, run_spacing=6, controls=[
            th.capsule("{" + t(f"tok_{k}") + "}", lambda e, k=k: self._insert(k)) for k in
            ("genre", "artist", "album", "year", "type")
        ])
        file_tokens = ft.Row(spacing=6, wrap=True, run_spacing=6, controls=[
            th.capsule("{" + t(f"tok_{k}") + "}", lambda e, k=k: self._insert_file(k)) for k in
            ("track", "title", "artist", "album", "year")
        ])
        self._render_kinds()
        self._render_presets()
        layout = th.section(t("sec_layout"), [
            th.label(t("release_type"), 10),
            self.kind_row,
            self.template,
            th.label(t("blocks"), 10), tokens,
            th.label(t("presets"), 10), self.preset_row,
            self.filename, file_tokens,
            ft.Container(
                content=ft.Column([th.label(t("preview"), 10), self.preview], spacing=2),
                bgcolor=th.PANEL, border=ft.Border.all(1, th.BORDER), border_radius=th.SHARP, padding=8,
            ),
            th.label(t("layout_hint"), 10, th.FAINT),
            ft.Row([th.capsule(t("reset"), self._reset_layout, icon=ft.Icons.RESTART_ALT_ROUNDED)]),
        ])
        self._update_preview()

        # --- genre
        self.manual = th.field(value=self.s.manual_genre, label=t("manual_genre"), disabled=self.s.auto_genre,
                               on_change=self._on_manual)
        genre = th.section(t("sec_genre"), [
            ft.Row([ft.Text(t("auto_genre"), size=12, color=th.TEXT, expand=True),
                    ft.Switch(value=self.s.auto_genre, active_color=th.ACCENT, on_change=self._on_auto)]),
            th.label(t("auto_genre_hint"), 10),
            self.manual,
            ft.Row([th.capsule(t("artist_genres"), lambda e: actions["genres"](), icon=ft.Icons.SELL_ROUNDED)]),
        ])

        # --- source
        self.sleep_label = th.label(t("sleep", s=f"{self.s.sleep_between:g}"), 11, th.TEXT)
        self.cookie_text = th.label("", 10)
        self.cookie_file_text = ft.Text("", size=11, color=th.TEXT, selectable=True, max_lines=2,
                                        overflow=ft.TextOverflow.ELLIPSIS)
        # stays in the tree, only its visibility changes: recreated buttons lose clicks
        self.cookie_file_clear = th.capsule(t("cookies_file_clear"), self._clear_cookie_file,
                                            icon=ft.Icons.CLOSE_ROUNDED)
        self._cookie_file_ui()
        source = th.section(t("sec_source"), [
            ft.Row([ft.Text(t("include_videos"), size=12, color=th.TEXT, expand=True),
                    ft.Switch(value=self.s.include_videos, active_color=th.ACCENT, on_change=self._on_videos)]),
        ])
        access = th.section(t("sec_access"), [
            ft.Dropdown(
                label=t("cookies"),
                value=self.s.cookies_browser or "-",
                options=[ft.DropdownOption(key=b or "-", text=b.capitalize() if b else t("cookies_none"))
                         for b in BROWSERS],
                on_select=self._on_cookies,
                text_size=12, dense=True, border_color=th.BORDER, focused_border_color=th.ACCENT,
                border_radius=th.SHARP, expand=True,
            ),
            th.label(t("cookies_hint"), 10),
            th.label(t("cookies_file"), 11, th.TEXT),
            ft.Row([ft.Icon(ft.Icons.DESCRIPTION_ROUNDED, size=16, color=th.ACCENT),
                    ft.Container(self.cookie_file_text, expand=True)], spacing=8),
            ft.Row([th.capsule(t("cookies_file_pick"), self._pick_cookie_file, icon=ft.Icons.FILE_OPEN_ROUNDED),
                    self.cookie_file_clear], spacing=6, wrap=True, run_spacing=6),
            th.label(t("cookies_file_hint"), 10),
            self.cookie_text,
            self.sleep_label,
            ft.Slider(min=0, max=10, divisions=20, value=self.s.sleep_between, active_color=th.ACCENT,
                      inactive_color=th.BORDER, on_change=self._on_sleep, on_change_end=self._on_sleep_end),
        ])

        # --- system
        self.ytdlp_text = th.label("", 11, th.TEXT)
        self.deno_text = th.label("", 10)
        self.ytdlp_reset = th.capsule(t("ytdlp_reset"), lambda e: self._reset_ytdlp(),
                                      icon=ft.Icons.SETTINGS_BACKUP_RESTORE_ROUNDED)
        system = th.section(t("sec_system"), [
            ft.Row([th.label(t("language"), 11, th.TEXT, expand=True),
                    th.capsule("RU", lambda e: self.on_language("ru"), selected=self.s.language == "ru"),
                    th.capsule("EN", lambda e: self.on_language("en"), selected=self.s.language == "en")],
                   spacing=6),
            ft.Row([self.ytdlp_text, ft.Container(expand=True),
                    th.capsule(t("update_ytdlp"), lambda e: actions["update_ytdlp"](), icon=ft.Icons.UPDATE_ROUNDED)]),
            ft.Row([self.ytdlp_reset,
                    th.capsule(t("open_logs"), lambda e: actions["open_logs"](), icon=ft.Icons.ARTICLE_ROUNDED)],
                   spacing=6, wrap=True, run_spacing=6),
            self.deno_text,
        ])
        behaviour = th.section(t("sec_behaviour"), [
            ft.Row([ft.Text(t("background_on_close"), size=12, color=th.TEXT, expand=True),
                    ft.Switch(value=self.s.background_on_close, active_color=th.ACCENT,
                              on_change=self._on_background)]),
            th.label(t("background_on_close_hint"), 10),
            ft.Row([ft.Text(t("skip_by_folder"), size=12, color=th.TEXT, expand=True),
                    ft.Switch(value=self.s.skip_by_folder, active_color=th.ACCENT, on_change=self._on_skip_mode)]),
            th.label(t("skip_by_folder_hint"), 10),
            th.label(t("clear_archive_hint"), 10),
            ft.Row([th.capsule(t("clear_archive"), lambda e: actions["clear_archive"](),
                               icon=ft.Icons.DELETE_SWEEP_ROUNDED)]),
        ])

        # rarely touched settings live on their own tab
        self.pages = {
            "main": ft.ListView(expand=True, spacing=10, padding=ft.Padding.only(right=8, bottom=12),
                                controls=[folder, fmt, layout, genre, source]),
            "more": ft.ListView(expand=True, spacing=10, padding=ft.Padding.only(right=8, bottom=12),
                                controls=[access, behaviour, system]),
        }
        self.tabs = ft.Row(spacing=6, tight=True)
        self.view = ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Container(
                    ft.Row([th.heading(t("settings"), 11), ft.Container(expand=True), self.tabs,
                            th.icon_btn(ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_ROUNDED, lambda e: on_close(),
                                        tooltip=t("hide_panel"), size=16)] if on_close else
                           [th.heading(t("settings"), 11), ft.Container(expand=True), self.tabs],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.only(left=4, right=4),
                ),
                ft.Stack(list(self.pages.values()), expand=True),
            ],
        )
        self._show_tab(SettingsPanel.tab)

    tab = "main"  # class-level: survives the rebuild after a language switch

    def _show_tab(self, name: str) -> None:
        SettingsPanel.tab = name
        for k, v in self.pages.items():
            v.visible = k == name
        self.tabs.controls = [
            th.capsule(t("tab_main"), lambda e: self._switch("main"), selected=name == "main"),
            th.capsule(t("tab_more"), lambda e: self._switch("more"), selected=name == "more",
                       icon=ft.Icons.TUNE_ROUNDED),
        ]

    def _switch(self, name: str) -> None:
        self._show_tab(name)
        self.view.update()

    # ---------- helpers ----------

    @staticmethod
    def _short_path(p: str) -> str:
        if IS_WINDOWS:
            return p  # "~" means nothing to Windows users
        home = str(Path.home())
        return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p

    def _changed(self):
        self.s.save()
        self.on_change()

    def set_system(self, ytdlp: str, deno_ok: bool, ffmpeg_ok: bool, mpv_ok: bool = True,
                   overlay: bool = False) -> None:
        """overlay: an updated yt-dlp downloaded by the app is (or will be after restart) in use."""
        self.ytdlp_text.value = t("ytdlp_version", v=ytdlp)
        self.ytdlp_reset.visible = overlay
        msgs = [t("deno_ok") if deno_ok else t("deno_missing")]
        if not ffmpeg_ok:
            msgs.append(t("ffmpeg_missing"))
        if not mpv_ok:
            msgs.append(t("mpv_missing"))
        self.deno_text.value = "\n".join(msgs)
        self.deno_text.color = th.MUTED if deno_ok and ffmpeg_ok and mpv_ok else th.ERROR

    # ---------- folder ----------

    async def _pick_folder(self, e):
        path = await self.picker.get_directory_path(dialog_title=t("sec_folder"),
                                                    initial_directory=self.s.music_dir)
        if path:
            self.s.music_dir = path
            self.folder_text.value = self._short_path(path)
            self._update_preview()
            self._changed()
            self.view.update()

    def _open_folder(self, e):
        try:
            desktop.open_folder(Path(self.s.music_dir).expanduser())
        except OSError as err:
            self.page.show_dialog(ft.SnackBar(ft.Text(t("err_open_folder", e=err)), bgcolor=th.SURFACE_HI))

    # ---------- format ----------

    def _format_hint(self):
        f = self.s.audio_format
        self.format_hint.value = t(f"fmt_{f}")
        self.format_hint.color = th.ERROR if f == "flac" else th.MUTED

    def _on_format(self, e):
        sel = list(e.control.selected or [])
        if sel:
            self.s.audio_format = sel[0]
        self._format_hint()
        self._update_preview()
        self._changed()
        self.view.update()

    # ---------- layout ----------

    def _render_kinds(self):
        self.kind_row.controls = [
            th.capsule(t(f"kind_{k}"), lambda e, k=k: self._select_kind(k), selected=k == self.kind) for k in KINDS
        ]

    def _render_presets(self):
        cur = self.s.templates[self.kind]
        self.preset_row.controls = [th.capsule(self._pretty(p), lambda e, p=p: self._apply_preset(p),
                                               selected=p == cur) for p in PRESETS]

    @staticmethod
    def _pretty(template: str) -> str:
        out = template
        for k in naming.TOKENS:
            out = out.replace("{" + k + "}", t(f"tok_{k}"))
        return out

    def _select_kind(self, k: str):
        self.kind = k
        self.template.value = self.s.templates[k]
        self._render_kinds()
        self._render_presets()
        self._update_preview()
        self.view.update()

    def _apply_preset(self, p: str):
        self.template.value = p
        self._store_template()

    def _insert(self, token: str):
        val = (self.template.value or "").rstrip("/")
        self.template.value = f"{val}/{{{token}}}" if val else f"{{{token}}}"
        self._store_template()

    def _insert_file(self, token: str):
        val = self.filename.value or ""
        sep = ". " if token == "title" and val.endswith("}") else (" " if val and not val.endswith(" ") else "")
        self.filename.value = f"{val}{sep}{{{token}}}"
        self._on_filename(None)
        self.view.update()

    def _on_template(self, e):
        self._store_template(update_field=False)

    def _store_template(self, update_field: bool = True):
        value = (self.template.value or "").strip().strip("/") or DEFAULT_TEMPLATES[self.kind]
        self.s.templates[self.kind] = value
        self._render_presets()
        self._update_preview()
        self._changed()
        self.view.update()

    def _on_filename(self, e):
        self.s.filename_template = (self.filename.value or "").strip() or DEFAULT_FILENAME
        self._update_preview()
        self._changed()
        if e is not None:
            self.view.update()

    def _reset_layout(self, e):
        self.s.templates = dict(DEFAULT_TEMPLATES)
        self.s.filename_template = DEFAULT_FILENAME
        self.template.value = self.s.templates[self.kind]
        self.filename.value = DEFAULT_FILENAME
        self._render_presets()
        self._update_preview()
        self._changed()
        self.view.update()

    def _update_preview(self):
        k = self.kind
        values = {**SAMPLE, "album": SAMPLE_ALBUM[k], "type": k.upper() if k == "ep" else k.capitalize(),
                  "genre": SAMPLE["genre"] if self.s.auto_genre or not self.s.manual_genre else self.s.manual_genre}
        parts = naming.render(self.s.templates[k], values)
        fvals = {**values, "track": "01" if k in ("album", "ep") else ""}
        stem = naming.clean(" ".join(naming.render(self.s.filename_template, fvals)) or "Supersonic")
        base = self._short_path(self.s.music_dir)
        self.preview.value = os.sep.join([base.rstrip("\\/"), *parts, f"{stem}.{self.s.audio_format}"])

    # ---------- genre / source ----------

    def _on_auto(self, e):
        self.s.auto_genre = bool(e.control.value)
        self.manual.disabled = self.s.auto_genre
        self._update_preview()
        self._changed()
        self.view.update()

    def _on_manual(self, e):
        self.s.manual_genre = e.control.value or ""
        self._update_preview()
        self._changed()
        self.view.update()

    def _on_videos(self, e):
        self.s.include_videos = bool(e.control.value)
        self._changed()

    def _on_background(self, e):
        self.s.background_on_close = bool(e.control.value)
        self._changed()

    def _on_skip_mode(self, e):
        self.s.skip_by_folder = bool(e.control.value)
        self._changed()

    def _on_cookies(self, e):
        v = e.control.value
        self.s.cookies_browser = "" if v in (None, "-") else v
        self._changed()
        self.check_cookies()

    def _cookie_file_ui(self) -> None:
        self.cookie_file_text.value = self.s.cookies_file or t("cookies_none")
        self.cookie_file_text.color = th.TEXT if self.s.cookies_file else th.MUTED
        self.cookie_file_clear.visible = bool(self.s.cookies_file)

    async def _pick_cookie_file(self, e):
        files = await self.picker.pick_files(dialog_title=t("cookies_file"), file_type=ft.FilePickerFileType.CUSTOM,
                                             allowed_extensions=["txt"])
        path = files[0].path if files else None
        if not path:
            return
        self.s.cookies_file = path
        self._cookie_file_ui()
        self._changed()
        self.view.update()
        self.check_cookies()

    def _clear_cookie_file(self, e):
        self.s.cookies_file = ""
        self._cookie_file_ui()
        self._changed()
        self.view.update()
        self.check_cookies()

    def _reset_ytdlp(self) -> None:
        self.actions["reset_ytdlp"]()
        self.ytdlp_reset.visible = False
        self._refresh(self.ytdlp_reset)

    def _cookie_source(self) -> tuple[str, str]:
        """(kind, value) of what downloads will use: a file wins over a browser."""
        if self.s.cookies_file:
            return "file", self.s.cookies_file
        if self.s.cookies_browser:
            return "browser", self.s.cookies_browser
        return "", ""

    def check_cookies(self) -> None:
        kind, value = self._cookie_source()
        if not kind:
            self.cookie_text.value = ""
            self._refresh(self.cookie_text)
            return
        self.cookie_text.value, self.cookie_text.color = t("cookies_checking"), th.MUTED
        self._refresh(self.cookie_text)

        def work():
            status = cookie_file_status(value) if kind == "file" else cookie_status(value)
            if (kind, value) == self._cookie_source():
                self.page.run_task(self._show_cookies, status, kind, value)

        threading.Thread(target=work, daemon=True, name="salt-cookies").start()

    async def _show_cookies(self, status: str, kind: str, value: str) -> None:
        name = t("cookies_file_title", b=Path(value).name) if kind == "file" else value.capitalize()
        self.cookie_text.value = t("cookies_" + status, b=name)
        self.cookie_text.color = th.ACCENT if status == "ok" else th.ERROR
        self._refresh(self.cookie_text)
        if status == "ok":
            self.actions["cookies_ok"]()

    @staticmethod
    def _refresh(control: ft.Control) -> None:
        try:
            control.update()
        except RuntimeError:
            pass  # not mounted yet: the value shows on first render

    def _on_sleep(self, e):
        self.sleep_label.value = t("sleep", s=f"{float(e.control.value):g}")
        self.sleep_label.update()

    def _on_sleep_end(self, e):
        self.s.sleep_between = round(float(e.control.value), 1)
        self._changed()
