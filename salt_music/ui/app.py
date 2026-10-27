"""Main window: library + player | downloads + link field | settings."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path

import flet as ft

from .. import __version__, adb, app_update, desktop, i18n, library, links, metadata, tools, updater
from ..config import Settings
from ..downloader import Downloader
from ..i18n import t
from ..links import LinkError
from ..paths import IS_WINDOWS, assets_dir
from . import theme as th
from .downloads_panel import DownloadsPanel, PushTask
from .library_panel import LibraryPanel
from .phone_panel import PhonePanel
from .player import Player
from .settings_panel import SettingsPanel
from .sidebar import Sidebar

log = logging.getLogger(__name__)


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.settings = Settings.load()
        tools.set_custom(self.settings.tool_paths)
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
        # updates: "idle" | "checking" | "downloading"; what was found stays until installed
        self._upd_state = "idle"
        self._upd_release: app_update.Release | None = None
        self._upd_ytdlp: str | None = None
        self._upd_progress = 0
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
        self.update_btn = th.capsule(t("upd_check"), self._on_update_click, icon=ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED)
        self._paint_update()
        input_row = ft.Container(
            padding=ft.Padding.only(left=16, right=16, bottom=16, top=4),
            content=ft.Column([
                ft.Row([self.update_btn]),
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
                "reset_ytdlp": self._reset_ytdlp,
                "open_logs": self._open_logs,
                "clear_archive": self._clear_archive,
                "cookies_ok": self.downloader.retry_blocked,
                "tools_changed": self._on_tools_changed,
            },
            on_close=lambda: self.right_bar.set_open(False),
        )
        self.settings_panel.check_cookies()
        self._show_system()
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
                ft.Image(src="icon.svg", width=30, height=30),
                ft.Text("SALT", size=15, color=th.TEXT, font_family=th.FONT_BOLD),
                ft.Text("MUSIC", size=15, color=th.ACCENT, font_family=th.FONT_BOLD),
                ft.Container(expand=True),
                th.label(f"v{__version__}", 10, th.FAINT),
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
        state = {"lib": 0.0, "phone": 0.0, "update": time.monotonic() - self.UPDATE_EVERY + self.UPDATE_FIRST}
        threading.Thread(target=app_update.cleanup, daemon=True, name="salt-update-cleanup").start()
        while True:
            await asyncio.sleep(0.3)
            try:
                if await self._tick(state):
                    return
            except Exception:
                # one bad tick must not stop the UI from updating for good
                log.exception("ui loop")
                await asyncio.sleep(2)

    async def _tick(self, state: dict) -> bool:
        """One pass of the loop; True when the app has quit."""
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
            return True
        if self.lib_dirty and now - state["lib"] > 3:
            self.lib_dirty = False
            state["lib"] = now
            await self._rescan()
        if now - state["phone"] > 5:
            state["phone"] = now
            await self._check_phone(False)
        if now - state["update"] > self.UPDATE_EVERY:
            state["update"] = now
            self._check_updates(manual=False)
        self._auto_push()
        return False

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
        if self.hidden:
            # downloading in the background: the question would wait unseen forever
            await self.show_window()
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
                log.exception("push failed")
                task.status, task.error = "error", str(err)
            if move and on_phone:
                # only what really is on the phone now, even if the transfer stopped halfway
                library.remove_moved(on_phone, base)
                self.lib_dirty = True
            task.finished = time.monotonic()
            self.dirty = True

        threading.Thread(target=run, daemon=True, name="salt-push").start()
        return task

    # ---------- system ----------

    @staticmethod
    def _ytdlp_version() -> str:
        try:
            import yt_dlp.version
            return yt_dlp.version.__version__
        except Exception:
            return "?"

    def _show_system(self, version: str | None = None) -> None:
        tools.refresh()  # the user may have installed something meanwhile
        self.settings_panel.set_system(version or self._ytdlp_version(),
                                       overlay=updater.active_version() is not None)

    # ---------- updates of the app and yt-dlp ----------

    UPDATE_FIRST = 5.0  # seconds after start
    UPDATE_EVERY = 6 * 3600.0

    def _paint_update(self) -> None:
        """The button above the link field shows what is going on with updates."""
        icon, text = self.update_btn.content.controls
        found = self._upd_release or self._upd_ytdlp
        if self._upd_state == "downloading":
            label, hot = t("upd_downloading", p=self._upd_progress), True
        elif self._upd_state == "checking":
            label, hot = t("upd_checking"), False
        elif self._upd_release:
            label, hot = t("upd_available", v=self._upd_release.version), True
        elif self._upd_ytdlp:
            label, hot = t("upd_ytdlp_available", v=self._upd_ytdlp), True
        else:
            label, hot = t("upd_check"), False
        text.value = label
        fg = th.BG if hot else th.TEXT
        icon.color = text.color = fg
        icon.name = ft.Icons.DOWNLOADING_ROUNDED if self._upd_state == "downloading" else (
            ft.Icons.NEW_RELEASES_ROUNDED if found else ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED)
        self.update_btn.bgcolor = th.ACCENT if hot else th.SURFACE_HI
        self.update_btn.border = ft.Border.all(1, th.ACCENT if hot else th.BORDER)
        self.update_btn.tooltip = t("upd_tooltip", v=__version__)

    async def _repaint_update(self) -> None:
        self._paint_update()
        try:
            self.update_btn.update()
        except RuntimeError:
            pass  # rebuilt meanwhile (language switch): the new button is painted already

    def _on_update_click(self, e) -> None:
        if self._upd_state != "idle":
            return
        if self._upd_release or self._upd_ytdlp:
            self._confirm_update()
        else:
            self._check_updates(manual=True)

    def _check_updates(self, manual: bool) -> None:
        if self._upd_state != "idle":
            return
        self._upd_state = "checking"
        self._paint_update()
        if manual:
            self.update_btn.update()

        def run():
            release = ytdlp = error = None
            try:
                release = app_update.check()
            except Exception as err:
                error = err
            try:
                latest, _, _ = updater.latest("yt-dlp")
                if updater.is_newer(latest, updater.active_version() or self._ytdlp_version()):
                    ytdlp = latest
            except Exception as err:
                error = error or err
            if error:
                log.info("update check: %s", error)
            self.page.run_task(self._after_check, release, ytdlp, error, manual)

        threading.Thread(target=run, daemon=True, name="salt-update-check").start()

    async def _after_check(self, release, ytdlp, error, manual: bool) -> None:
        self._upd_state = "idle"
        self._upd_release, self._upd_ytdlp = release, ytdlp
        await self._repaint_update()
        if not manual:
            return
        if release or ytdlp:
            self._confirm_update()
        elif error:
            self._snack(t("upd_check_failed", e=str(error)[:200]), error=True)
        else:
            self._snack(t("upd_none", v=__version__))

    _NOTES_STYLE = ft.MarkdownStyleSheet(
        p_text_style=ft.TextStyle(size=11, color=th.MUTED),
        code_text_style=ft.TextStyle(size=11, color=th.ACCENT),
        **{f"h{i}_text_style": ft.TextStyle(size=12, color=th.TEXT, font_family=th.FONT_BOLD) for i in (1, 2, 3)},
    )

    def _confirm_update(self) -> None:
        release, ytdlp = self._upd_release, self._upd_ytdlp
        kind = app_update.install_kind()
        lines: list[ft.Control] = []
        if release:
            lines.append(ft.Text(t("upd_app", v=release.version, cur=__version__), size=12, color=th.TEXT))
            if release.notes.strip():
                lines.append(ft.Container(
                    ft.Column([ft.Markdown(release.notes, selectable=True, md_style_sheet=self._NOTES_STYLE)],
                              scroll=ft.ScrollMode.AUTO),
                    height=220, bgcolor=th.PANEL, border=ft.Border.all(1, th.BORDER), border_radius=th.SHARP,
                    padding=10))
            lines.append(th.label(t("upd_how_" + (kind or "manual")), 11))
        if ytdlp and not (release and kind):  # a new app brings its own yt-dlp
            lines.append(ft.Text(t("upd_ytdlp", v=ytdlp), size=12, color=th.TEXT))
        busy = self.downloader.busy or any(p.status == "running" for p in self.downloads.pushes)
        if release and kind and busy:
            lines.append(th.label(t("upd_busy"), 11, th.ERROR))

        actions = [ft.TextButton(t("cancel"), on_click=lambda e: self.page.pop_dialog())]
        if release and not kind:
            actions.append(ft.TextButton(t("upd_open_page"), on_click=lambda e: self._open_release(release)))
        if (release and kind) or ytdlp:
            actions.append(ft.TextButton(t("upd_install"), on_click=lambda e: self._install_updates(kind)))
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(t("upd_title"), size=14, font_family=th.FONT_BOLD),
            content=ft.Column(lines, spacing=10, tight=True, width=480),
            bgcolor=th.SURFACE, shape=ft.RoundedRectangleBorder(radius=th.SHARP), actions=actions,
        ))

    def _open_release(self, release: app_update.Release) -> None:
        self.page.pop_dialog()
        self.page.run_task(self.page.launch_url, release.page)

    def _install_updates(self, kind: str | None) -> None:
        self.page.pop_dialog()
        release = self._upd_release if kind else None
        ytdlp = None if release else self._upd_ytdlp
        self._upd_state, self._upd_progress = "downloading", 0
        self._paint_update()
        self.update_btn.update()

        def progress(fraction: float) -> None:
            pct = int(fraction * 100)
            if pct != self._upd_progress:
                self._upd_progress = pct
                self.page.run_task(self._repaint_update)

        def run():
            try:
                if release:
                    path = app_update.download(release, kind, progress=progress)
                    self.page.run_task(self._restart_into, path, kind)
                    return
                if ytdlp:
                    v = updater.update(updater.active_version() or self._ytdlp_version())
                    self.page.run_task(self._after_ytdlp_update, v)
            except Exception as err:
                log.warning("update failed: %s", err)
                self.page.run_task(self._update_failed, str(err)[:200])

        threading.Thread(target=run, daemon=True, name="salt-update").start()

    async def _restart_into(self, installer: Path, kind: str) -> None:
        try:
            app_update.launch(installer, kind)
        except Exception as err:
            await self._update_failed(str(err)[:200])
            return
        await self.quit()

    async def _after_ytdlp_update(self, version: str | None) -> None:
        self._upd_state, self._upd_ytdlp = "idle", None
        await self._repaint_update()
        if version:
            self._show_system(version)
            self.settings_panel.view.update()
        self._snack(t("updated", v=version) if version else t("ytdlp_latest"))

    async def _update_failed(self, message: str) -> None:
        self._upd_state = "idle"
        await self._repaint_update()
        self._snack(t("update_failed", e=message), error=True)

    def _on_tools_changed(self) -> None:
        """A program was chosen by hand or found again: the phone check picks it up at once."""
        self.page.run_task(self._check_phone, False)

    def _update_ytdlp(self) -> None:
        """Download the newest yt-dlp next to the app (no pip in the packed .exe)."""
        self._snack(t("updating"))
        pending = updater.active_version()
        current = pending or self._ytdlp_version()

        def run():
            try:
                v = updater.update(current)
            except Exception as err:
                log.warning("yt-dlp update failed: %s", err)
                self.page.run_task(self._after_update, t("update_failed", e=str(err)[:200]), True)
                return
            if v is None:
                self.page.run_task(self._after_update, t("ytdlp_latest"), False)
            else:
                self.page.run_task(self._after_update, t("updated", v=v), False, v)

        threading.Thread(target=run, daemon=True, name="salt-update").start()

    async def _after_update(self, msg: str, error: bool, version: str | None = None) -> None:
        if version:
            self._show_system(version)
            self.settings_panel.view.update()
        self._snack(msg, error)

    def _reset_ytdlp(self) -> None:
        updater.reset()
        self._snack(t("ytdlp_reset_done"))

    def _open_logs(self) -> None:
        from ..paths import LOG_DIR

        try:
            desktop.open_folder(LOG_DIR)
        except OSError as err:
            self._snack(t("err_open_folder", e=err), error=True)

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
    icon = assets_dir() / ("icon.ico" if IS_WINDOWS else "icon.png")
    if icon.is_file():
        page.window.icon = str(icon)
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
    assets = assets_dir()
    port = os.environ.get("SALT_WEB_PORT")
    if port:  # browser mode, handy for UI checks; listens on localhost only
        ft.run(main, assets_dir=str(assets), view=ft.AppView.WEB_BROWSER, port=int(port), host="127.0.0.1")
        return
    _instance = desktop.claim()
    if _instance is None:
        log.info("another copy is running: woke it up")
        return
    ft.run(main, assets_dir=str(assets))
