"""Main window: library + player | downloads + link field | settings."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import flet as ft

from .. import adb, desktop, i18n, library, links, metadata
from ..config import Settings
from ..downloader import Downloader
from ..i18n import t
from ..links import LinkError
from . import theme as th
from .downloads_panel import DownloadsPanel, PushTask
from .library_panel import LibraryPanel
from .phone_panel import PhonePanel
from .player import Player
from .settings_panel import SettingsPanel
from .sidebar import Sidebar


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.settings = Settings.load()
        i18n.set_language(self.settings.language)
        self.dirty = True
        self.lib_dirty = True
        self.device: adb.Device | None = None
        self._phone_text = (t("phone_none"), False)
        self._phone_info: dict = {}
        self._auto_files: list[Path] = []  # new downloads waiting to go to the phone
        self._auto_task: PushTask | None = None
        self.picker = ft.FilePicker()
        self.player = Player(page)
        self.downloader = Downloader(self.settings, self._on_job_change, self._ask_genre, self._on_file)
        self.lib_artists: list[library.LibArtist] = []
        self.hidden = False  # window closed while downloading: we keep working in the background
        self._build()

    # ---------- layout ----------

    def _build(self) -> None:
        p = self.page
        self.link = th.field(
            hint_text=t("link_hint"), expand=True, border_radius=th.CAPSULE, text_size=13,
            prefix_icon=ft.Icons.LINK_ROUNDED, on_submit=self._submit, autofocus=True,
            content_padding=ft.Padding.symmetric(horizontal=18, vertical=14),
        )
        self.link_error = ft.Text("", size=11, color=th.ERROR, visible=False)
        input_row = ft.Container(
            padding=ft.Padding.only(left=16, right=16, bottom=16, top=4),
            content=ft.Column([
                ft.Row([self.link, th.circle_button(ft.Icons.ARROW_DOWNWARD_ROUNDED, self._submit, size=48,
                                                    tooltip=t("download"))], spacing=10),
                self.link_error,
            ], spacing=4, tight=True),
        )
        self.downloads = DownloadsPanel(self.downloader, input_row, self._show_history)
        self.library = LibraryPanel(self._play, self._on_pick)
        self.library.set_artists(self.lib_artists)
        self.player.title.value = self.player.title.value if self.player.index >= 0 else t("nothing_playing")
        self.settings_panel = SettingsPanel(
            p, self.settings, self.picker, self._on_settings, self._set_language,
            actions={
                "genres": self._show_genres,
                "update_ytdlp": self._update_ytdlp,
                "clear_archive": self._clear_archive,
                "cookies_ok": self.downloader.retry_blocked,
            },
            on_close=lambda: self.right_bar.set_open(False),
        )
        self.settings_panel.check_cookies()
        self.settings_panel.set_system(self._ytdlp_version(), shutil.which("deno") is not None,
                                       shutil.which("ffmpeg") is not None, shutil.which("mpv") is not None)
        self.phone_panel = PhonePanel(
            self.settings,
            actions={
                "refresh": lambda: p.run_task(self._check_phone, True),
                "connect": lambda addr: p.run_task(self._connect, addr),
                "push_selected": lambda: self._push(t("picked_name", n=len(self.library.selected)),
                                                    self.library.selected_tracks()),
                "push_all": lambda: self._push(t("phone_send_all"), [tr for a in self.lib_artists for tr in a.tracks]),
                "clear_selection": self.library.clear_selection,
                "compare": lambda: p.run_task(self._compare),
                "browse_dir": lambda: p.run_task(self._browse_phone_dir),
            },
            on_close=lambda: self.phone_bar.set_open(False),
        )
        self._show_phone()
        self._on_pick(update=False)

        logo = ft.Container(
            padding=ft.Padding.only(left=14, right=14, top=14, bottom=10),
            content=ft.Row([
                ft.Container(width=30, height=30, shape=ft.BoxShape.CIRCLE, bgcolor=th.ACCENT,
                             alignment=ft.Alignment.CENTER,
                             content=ft.Text("S", size=15, color=th.BG, font_family=th.FONT_BOLD)),
                ft.Text("SALT", size=15, color=th.TEXT, font_family=th.FONT_BOLD),
                ft.Text("MUSIC", size=15, color=th.ACCENT, font_family=th.FONT_BOLD),
                ft.Container(expand=True),
                th.label("v0.1", 10, th.FAINT),
                th.icon_btn(ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_ROUNDED, lambda e: self.left_bar.set_open(False),
                            tooltip=t("hide_panel"), size=16),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        s = self.settings
        self.left_bar = Sidebar(
            "left", ft.Column([logo, self.library.view, self.player.view], spacing=6, expand=True),
            s.left_width, s.left_open, min_width=240, max_width=lambda: self._room(self.left_bar),
            on_save=lambda w, o: self._save_bar("left", w, o), on_open=self._make_room,
            rail_icon=ft.Icons.LIBRARY_MUSIC_ROUNDED, rail_tooltip=t("show_library"),
        )
        center = ft.Container(expand=True, padding=ft.Padding.only(top=14), content=self.downloads.view)
        self.right_bar = Sidebar(
            "right", ft.Container(self.settings_panel.view, padding=ft.Padding.only(left=12, right=4, top=14),
                                  expand=True),
            s.right_width, s.right_open, min_width=340, max_width=lambda: self._room(self.right_bar),
            on_save=lambda w, o: self._save_bar("right", w, o), on_open=self._make_room,
            rail_icon=ft.Icons.TUNE_ROUNDED, rail_tooltip=t("show_settings"),
        )
        self.phone_bar = Sidebar(
            "right", ft.Container(self.phone_panel.view, padding=ft.Padding.only(left=12, right=4, top=14),
                                  expand=True),
            s.phone_width, s.phone_open, min_width=300, max_width=lambda: self._room(self.phone_bar),
            on_save=lambda w, o: self._save_bar("phone", w, o), on_open=self._make_room,
            rail_icon=ft.Icons.PHONE_ANDROID_ROUNDED, rail_tooltip=t("show_phone"),
        )
        self.bars = [self.left_bar, self.phone_bar, self.right_bar]
        self._fit_bars()
        p.controls.clear()
        p.add(ft.Row([*self.left_bar.controls, center, *self.phone_bar.controls, *self.right_bar.controls],
                     spacing=0, expand=True,
                     vertical_alignment=ft.CrossAxisAlignment.STRETCH))
        p.on_resize = self._on_resize
        self.downloads.sync()

    CENTER_MIN = 480

    def _room(self, bar: Sidebar) -> float:
        """Widest a sidebar may get while the other ones and the downloads keep their place."""
        total = self.page.width or self.page.window.width or 1440
        others = sum(b.taken for b in getattr(self, "bars", []) if b is not bar)
        return max(0, total - others - self.CENTER_MIN - 8)

    def _make_room(self, bar: Sidebar) -> None:
        """A sidebar opens but doesn't fit: close the others, the neighbour on its side first."""
        order = [b for b in (self.right_bar, self.phone_bar, self.left_bar) if b is not bar]
        if bar.side == "left":
            order.reverse()
        for other in order:
            if bar.max_width() >= bar.min_width:
                break
            if other.opened:
                other.set_open(False, update=False)

    def _fit_bars(self) -> None:
        """Window got narrower: shrink the sidebars, and close those that no longer fit."""
        for bar in (self.phone_bar, self.right_bar, self.left_bar):
            if bar.opened and bar.max_width() < bar.min_width:
                bar.set_open(False, update=False)
        for bar in self.bars:
            bar.fit()

    def _save_bar(self, side: str, width: int, opened: bool) -> None:
        setattr(self.settings, f"{side}_width", width)
        setattr(self.settings, f"{side}_open", opened)
        self.settings.save()

    def _on_resize(self, e) -> None:
        self._fit_bars()
        self.page.update()

    def _set_language(self, lang: str) -> None:
        if lang == self.settings.language:
            return
        self.settings.language = lang
        self.settings.save()
        i18n.set_language(lang)
        self._build()
        self.page.update()

    # ---------- background loop ----------

    async def loop(self) -> None:
        last_lib = last_phone = 0.0
        while True:
            await asyncio.sleep(0.3)
            now = time.monotonic()
            active = any(j.status in ("running", "resolving") for j in self.downloader.jobs) or any(
                p.status == "running" for p in self.downloads.pushes)
            if self.dirty or active:
                self.dirty = False
                self.downloader.save_jobs()
                if not self.hidden:
                    self.downloads.sync()
                    self.downloads.view.update()
            if self.hidden and not active and not self.downloader.busy:
                desktop.notify(t("bg_done_title"), t("bg_done_body"))
                await self.quit()
                return
            if self.lib_dirty and now - last_lib > 3:
                self.lib_dirty = False
                last_lib = now
                await self._rescan()
            if now - last_phone > 5:
                last_phone = now
                await self._check_phone(False)
            self._auto_push()

    # ---------- window ----------

    async def on_window_event(self, e: ft.WindowEvent) -> None:
        if e.type != ft.WindowEventType.CLOSE:
            return
        busy = self.downloader.busy or any(p.status == "running" for p in self.downloads.pushes)
        if self.settings.background_on_close and busy:
            self.hidden = True
            if self.player.playing:
                self.player._toggle()
            self.page.window.visible = False
            self.page.update()
            desktop.notify(t("bg_title"), t("bg_body"))
            return
        await self.quit()

    async def show_window(self) -> None:
        self.hidden = False
        self.page.window.visible = True
        self.downloads.sync()
        self.page.update()
        await self.page.window.to_front()

    async def quit(self) -> None:
        self.downloader.save_jobs(force=True)
        self.player.close()
        await self.page.window.destroy()

    def _on_job_change(self, job) -> None:
        self.dirty = True

    def _on_file(self, path: Path) -> None:
        self.lib_dirty = True
        if self.settings.phone_auto and path.suffix.lower() in library.AUDIO_EXT:
            self._auto_files.append(path)

    def _on_settings(self) -> None:
        self.lib_dirty = True

    async def _rescan(self) -> None:
        base = Path(self.settings.music_dir).expanduser()
        self.lib_artists = await asyncio.to_thread(library.scan, base)
        self.library.set_artists(self.lib_artists)
        self.library.view.update()

    # ---------- link field ----------

    async def _submit(self, e=None) -> None:
        text = (self.link.value or "").strip()
        self.link_error.visible = False
        try:
            link = links.parse(text)
        except LinkError as err:
            looks_like_url = "://" in text or text.startswith(("www.", "youtu", "music.")) or (
                "." in text.split(" ")[0] and "/" in text)
            if text and not looks_like_url:
                await self._search(text)
                return
            self.link_error.value = t(str(err))
            self.link_error.visible = True
            self.page.update()
            return
        self.link.value = ""
        self.downloader.add(link, link.url)
        self.page.update()

    async def _search(self, query: str) -> None:
        results_col = ft.Column([th.label(t("searching"), 12)], spacing=4, scroll=ft.ScrollMode.AUTO, height=360,
                                width=520)
        dlg = ft.AlertDialog(
            title=ft.Text(t("search_results"), size=14, font_family=th.FONT_BOLD),
            content=results_col, bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            actions=[ft.TextButton(t("close"), on_click=lambda e: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)
        try:
            results = await asyncio.to_thread(metadata.search, query)
        except Exception as err:
            results_col.controls = [ft.Text(str(err), size=11, color=th.ERROR)]
            results_col.update()
            return
        if not results:
            results_col.controls = [th.label(t("nothing_found"), 12)]
        else:
            icons = {"track": ft.Icons.MUSIC_NOTE_ROUNDED, "album": ft.Icons.ALBUM_ROUNDED,
                     "artist": ft.Icons.PERSON_ROUNDED}

            def pick(r):
                def handler(e):
                    self.page.pop_dialog()
                    self.link.value = ""
                    self.downloader.add(links.parse(r["url"]), r["title"] or r["url"])
                    self.page.update()
                return handler

            results_col.controls = [
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8), border_radius=th.SHARP, ink=True,
                    bgcolor=th.PANEL, on_click=pick(r),
                    content=ft.Row([
                        ft.Icon(icons[r["kind"]], size=18, color=th.ACCENT),
                        ft.Column([ft.Text(r["title"] or "", size=12, color=th.TEXT, max_lines=1),
                                   th.label(r["sub"] if r["kind"] == "album" else f"{t('kind_' + r['kind'])}  {r['sub'] or ''}", 10)],
                                  spacing=1, expand=True, tight=True),
                        ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=16, color=th.MUTED),
                    ], spacing=10),
                )
                for r in results
            ]
        results_col.update()

    # ---------- genre dialogs ----------

    def _ask_genre(self, artist: str) -> str | None:
        """Called from the download thread: blocks until the user answers."""
        done = threading.Event()
        box: dict[str, str | None] = {"v": None}
        self.page.run_task(self._ask_genre_dialog, artist, done, box)
        done.wait()
        return box["v"]

    async def _ask_genre_dialog(self, artist: str, done: threading.Event, box: dict) -> None:
        tf = th.field(label=t("sec_genre"), autofocus=True)

        def finish(value):
            box["v"] = value
            self.page.pop_dialog()
            done.set()

        known = sorted({g for _, _, g in self.downloader.known_genres() if g})[:16]
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(t("ask_genre_title"), size=14, font_family=th.FONT_BOLD),
            bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            content=ft.Column([
                ft.Text(t("ask_genre_text", artist=artist), size=12, color=th.TEXT),
                tf,
                ft.Row([th.capsule(g, lambda e, g=g: finish(g)) for g in known], wrap=True, spacing=6, run_spacing=6),
            ], tight=True, spacing=12, width=440),
            actions=[
                ft.TextButton(t("cancel"), on_click=lambda e: finish(None)),
                ft.FilledButton(t("ok"), on_click=lambda e: finish(tf.value)),
            ],
        )
        tf.on_submit = lambda e: finish(tf.value)
        self.page.show_dialog(dlg)

    def _show_genres(self) -> None:
        rows = []
        for key, name, genre in self.downloader.known_genres():
            tf = th.field(value=genre, width=170)
            tf.on_blur = lambda e, k=key, n=name: self.downloader.set_artist_genre(k, n, e.control.value or "")
            tf.on_submit = tf.on_blur
            rows.append(ft.Row([ft.Text(name, size=12, color=th.TEXT, expand=True, max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS), tf], spacing=10))
        content = ft.Column(rows or [th.label(t("artist_genres_empty"), 12)], spacing=6, scroll=ft.ScrollMode.AUTO,
                            height=min(420, 48 * max(len(rows), 1) + 10), width=460)
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(t("artist_genres"), size=14, font_family=th.FONT_BOLD), content=content,
            bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            actions=[ft.TextButton(t("close"), on_click=lambda e: self.page.pop_dialog())],
        ))

    def _show_history(self) -> None:
        items = self.downloader.history.items
        col = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, height=420, width=560)

        def render():
            col.controls = [
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6), bgcolor=th.PANEL, border_radius=th.SHARP,
                    content=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=14, color=th.ACCENT),
                        ft.Column([ft.Text(h["title"], size=12, color=th.TEXT, max_lines=1),
                                   th.label(f"{h['artist']} · {h['album']}", 10)], spacing=1, expand=True, tight=True),
                        th.label(time.strftime("%d.%m %H:%M", time.localtime(h["time"])), 10),
                    ], spacing=10),
                ) for h in items
            ] or [th.label(t("history_empty"), 12)]

        def clear(e):
            self.downloader.history.clear()
            nonlocal items
            items = []
            render()
            col.update()

        render()
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(t("history"), size=14, font_family=th.FONT_BOLD), content=col, bgcolor=th.SURFACE,
            shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            actions=[ft.TextButton(t("clear"), on_click=clear),
                     ft.TextButton(t("close"), on_click=lambda e: self.page.pop_dialog())],
        ))

    def _snack(self, text: str, error: bool = False) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(text, color=th.ERROR if error else th.TEXT, size=12),
                                          bgcolor=th.SURFACE_HI, behavior=ft.SnackBarBehavior.FLOATING,
                                          shape=ft.StadiumBorder(), width=520))

    # ---------- player ----------

    def _play(self, tracks, index: int) -> None:
        self.page.run_task(self.player.play_list, tracks, index)

    # ---------- phone ----------

    async def _check_phone(self, show: bool = False) -> None:
        before = self.device.serial if self.device else None
        if not adb.available():
            self.device = None
            self._phone_text = (t("adb_missing"), False)
        else:
            try:
                devs = await asyncio.to_thread(adb.devices)
            except adb.AdbError as err:
                devs = []
                self._phone_text = (str(err), False)
            ready = [d for d in devs if d.state == "device"]
            self.device = ready[0] if ready else None
            if self.device:
                self._phone_text = (t("phone_ready", model=self.device.model or self.device.serial), True)
            elif any(d.state == "unauthorized" for d in devs):
                self._phone_text = (t("phone_unauthorized"), False)
            elif any(d.state == "no permissions" for d in devs):
                self._phone_text = (t("phone_noperm"), False)
            elif devs:
                self._phone_text = (t("phone_offline"), False)
            else:
                self._phone_text = (t("phone_none") + ". " + t("phone_help"), False)
        if self.device and (show or self.device.serial != before):
            self._phone_info = await asyncio.to_thread(adb.info, self.device.serial, self.settings.phone_dir)
        elif not self.device:
            self._phone_info = {}
        self._show_phone()
        self.phone_panel._refresh()

    def _show_phone(self) -> None:
        text, ok = self._phone_text
        self.phone_panel.set_status(text, ok, self._phone_info)

    async def _connect(self, address: str) -> None:
        self._snack(t("wifi_connecting", a=address))
        try:
            await asyncio.to_thread(adb.connect, address)
        except adb.AdbError as err:
            self._snack(t("wifi_failed", e=t(str(err)) if str(err) in i18n.STRINGS else str(err)), error=True)
        await self._check_phone(True)

    async def _browse_phone_dir(self) -> None:
        """A small file manager over adb: walk the phone's folders and pick where the music goes."""
        if not self.device or self.device.state != "device":
            self._snack(t("phone_dir_need"), error=True)
            return
        p = self.page
        serial = self.device.serial
        state = {"path": self.settings.phone_dir}
        where = ft.Text("", size=12, color=th.TEXT, font_family=th.FONT_MEDIUM, selectable=True)
        folders = ft.Column([], spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        new_name = th.field(hint_text=t("phone_dir_new"), expand=True, on_submit=lambda e: p.run_task(create))
        up_btn = th.icon_btn(ft.Icons.ARROW_UPWARD_ROUNDED, lambda e: p.run_task(go, parent(state["path"])),
                             tooltip=t("phone_dir_up"))

        def parent(path: str) -> str:
            return path.rsplit("/", 1)[0] or "/"

        def join(name: str) -> str:
            return f"{state['path'].rstrip('/')}/{name}"

        def row(name: str) -> ft.Container:
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=7), border_radius=th.SHARP, ink=True,
                bgcolor=th.PANEL, on_click=lambda e: p.run_task(go, join(name)),
                content=ft.Row([ft.Icon(ft.Icons.FOLDER_ROUNDED, size=16, color=th.ACCENT),
                                ft.Text(name, size=12, color=th.TEXT, max_lines=1, expand=True),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16, color=th.FAINT)], spacing=10),
            )

        async def go(path: str) -> None:
            folders.controls = [th.label(t("phone_dir_loading"), 11)]
            folders.update()
            try:
                real, names = await asyncio.to_thread(adb.list_dirs, serial, path)
            except adb.AdbError as err:
                folders.controls = [ft.Text(t(str(err)) if str(err) in i18n.STRINGS else str(err),
                                            size=11, color=th.ERROR)]
                folders.update()
                return
            state["path"] = real
            where.value = real
            up_btn.disabled = real == "/"
            folders.controls = [row(n) for n in names] or [th.label(t("phone_dir_empty"), 11)]
            dlg.update()

        async def create() -> None:
            name = (new_name.value or "").strip().strip("/")
            if not name:
                return
            try:
                await asyncio.to_thread(adb.make_dir, serial, join(name))
            except adb.AdbError as err:
                self._snack(str(err), error=True)
                return
            new_name.value = ""
            await go(join(name))

        def choose(e) -> None:
            p.pop_dialog()
            self.phone_panel.set_dir(state["path"])
            self.phone_panel._refresh()
            p.run_task(self._check_phone, True)  # free space is shown for this folder

        shortcuts = ft.Row([th.capsule(label, lambda e, d=d: p.run_task(go, d))
                            for label, d in (("sdcard", "/sdcard"), ("Music", "/sdcard/Music"),
                                             ("Download", "/sdcard/Download"))], spacing=6, wrap=True)
        dlg = ft.AlertDialog(
            title=ft.Text(t("phone_browse_title"), size=14, font_family=th.FONT_BOLD),
            bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            content=ft.Column([
                ft.Row([up_btn, ft.Container(where, expand=True)], spacing=6),
                shortcuts,
                ft.Container(folders, height=300),
                ft.Row([new_name, th.capsule(t("phone_dir_create"), lambda e: p.run_task(create),
                                             icon=ft.Icons.CREATE_NEW_FOLDER_ROUNDED)], spacing=6),
            ], spacing=10, width=480, tight=True),
            actions=[ft.TextButton(t("cancel_btn"), on_click=lambda e: p.pop_dialog()),
                     ft.TextButton(t("phone_dir_choose"), on_click=choose)],
        )
        p.show_dialog(dlg)
        await go(state["path"])

    def _on_pick(self, update: bool = True) -> None:
        picked = self.library.selected
        size = 0
        for path in picked:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        self.phone_panel.set_picked(len(picked), size)
        if update:
            self.phone_panel._refresh()

    async def _compare(self) -> None:
        if not self.device:
            self._snack(self._phone_text[0], error=True)
            return
        self.phone_panel.set_compare(t("comparing"))
        self.phone_panel._refresh()
        base = Path(self.settings.music_dir).expanduser()
        tracks = [tr.path for a in self.lib_artists for tr in a.tracks]
        try:
            on_phone, have, missing = await asyncio.to_thread(
                adb.compare, self.device.serial, base, tracks, self.settings.phone_dir)
        except adb.AdbError as err:
            self.phone_panel.set_compare(str(err))
        else:
            self.phone_panel.set_compare(t("compare_result", phone=on_phone, have=have, missing=missing))
        self.phone_panel._refresh()

    def _push(self, name: str, tracks) -> None:
        if not self.device:
            self._snack(self._phone_text[0], error=True)
            return
        if not tracks:
            self._snack(t("nothing_to_send"), error=True)
            return
        if not self.settings.phone_move:
            self._start_push(name, tracks)
            return

        def go(e):
            self.page.pop_dialog()
            self._start_push(name, tracks)

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(t("move_confirm_title"), size=14, font_family=th.FONT_BOLD),
            content=ft.Text(t("move_confirm", n=len(tracks)), size=12, color=th.MUTED, width=420),
            bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            actions=[ft.TextButton(t("cancel"), on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton(t("mode_move"), on_click=go)],
        ))

    def _auto_push(self) -> None:
        """Send fresh downloads in batches, one transfer at a time."""
        if not self._auto_files or not self.device:
            return
        if self._auto_task and self._auto_task.status == "running":
            return
        files, self._auto_files = self._auto_files, []
        tracks = [library.LibTrack(f, f.stem, "", "", 0) for f in files if f.exists()]
        if tracks:
            self._auto_task = self._start_push(t("auto_push_name", n=len(tracks)), tracks)

    def _start_push(self, name: str, tracks) -> PushTask | None:
        base = Path(self.settings.music_dir).expanduser()
        files = library.files_for_push(tracks, base, self.settings.phone_covers)
        task = PushTask(name=name, total=len(files))
        self.downloads.add_push(task)
        self.dirty = True
        serial, remote, move = self.device.serial, self.settings.phone_dir, self.settings.phone_move
        on_phone: list[Path] = []

        def progress(i, total, f, state):
            task.done = i if state != "sending" else i - 1
            task.current = f.name
            if state == "skipped":
                task.skipped += 1
            elif state == "sent":
                task.sent += 1
            if state in ("skipped", "sent"):
                on_phone.append(f)

        def run():
            try:
                adb.push(serial, base, files, remote, progress, lambda: task.cancel)
                task.status = "cancelled" if task.cancel else "done"
            except adb.AdbError as err:
                task.status, task.error = "error", t(str(err)) if str(err) in i18n.STRINGS else str(err)
            except Exception as err:
                task.status, task.error = "error", str(err)
            if move and on_phone:
                # only what really is on the phone now, even if the transfer stopped halfway
                library.remove_moved(on_phone, base)
                self.lib_dirty = True
            task.finished = time.monotonic()
            self.dirty = True

        threading.Thread(target=run, daemon=True).start()
        return task

    # ---------- system ----------

    @staticmethod
    def _ytdlp_version() -> str:
        try:
            import yt_dlp.version
            return yt_dlp.version.__version__
        except Exception:
            return "?"

    def _update_ytdlp(self) -> None:
        self._snack(t("updating"))

        def run():
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                msg = t("update_failed", e=(r.stderr or r.stdout).strip().splitlines()[-1][:200])
                self.page.run_task(self._after_update, msg, True)
                return
            v = subprocess.run([sys.executable, "-c", "import yt_dlp.version as v; print(v.__version__)"],
                               capture_output=True, text=True).stdout.strip()
            self.page.run_task(self._after_update, t("updated", v=v), False, v)

        threading.Thread(target=run, daemon=True).start()

    async def _after_update(self, msg: str, error: bool, version: str | None = None) -> None:
        if version:
            self.settings_panel.set_system(version, shutil.which("deno") is not None,
                                           shutil.which("ffmpeg") is not None, shutil.which("mpv") is not None)
            self.settings_panel.view.update()
        self._snack(msg, error)

    def _clear_archive(self) -> None:
        self.downloader.archive.clear()
        self._snack(t("archive_cleared"))


async def main(page: ft.Page) -> None:
    page.title = "Salt Music"
    page.fonts = th.FONTS
    page.theme = th.theme()
    page.dark_theme = th.theme()
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = th.BG
    page.padding = 0
    page.spacing = 0
    page.window.width = 1440
    page.window.height = 900
    page.window.min_width = 1100
    page.window.min_height = 680
    page.window.bgcolor = th.BG
    app = App(page)
    if _instance:
        page.window.prevent_close = True
        page.window.on_event = app.on_window_event
        _instance.on_show = lambda: page.run_task(app.show_window)
    page.update()
    await app.loop()


_instance: desktop.InstanceServer | None = None


def run() -> None:
    global _instance
    assets = Path(__file__).resolve().parents[2] / "assets"
    port = os.environ.get("SALT_WEB_PORT")
    if port:  # browser mode, handy for UI checks
        ft.run(main, assets_dir=str(assets), view=ft.AppView.WEB_BROWSER, port=int(port))
        return
    if desktop.wake_running():
        return
    _instance = desktop.InstanceServer()
    ft.run(main, assets_dir=str(assets))
