"""Center: download / phone-transfer progress cards."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import flet as ft

from ..downloader import Downloader, Item, Job
from ..i18n import STRINGS, t
from . import theme as th

KIND_ICON = {
    "track": ft.Icons.MUSIC_NOTE_ROUNDED,
    "album": ft.Icons.ALBUM_ROUNDED,
    "playlist": ft.Icons.QUEUE_MUSIC_ROUNDED,
    "artist": ft.Icons.PERSON_ROUNDED,
    "push": ft.Icons.PHONE_ANDROID_ROUNDED,
}
STATUS_COLOR = {
    "queued": th.MUTED, "resolving": th.ACCENT, "running": th.ACCENT, "downloading": th.ACCENT,
    "processing": th.ACCENT, "sending": th.ACCENT, "done": th.TEXT, "sent": th.TEXT, "skipped": th.FAINT,
    "error": th.ERROR, "cancelled": th.FAINT,
}
ITEM_ICON = {
    "queued": ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED,
    "downloading": ft.Icons.DOWNLOADING_ROUNDED,
    "processing": ft.Icons.AUTORENEW_ROUNDED,
    "done": ft.Icons.CHECK_CIRCLE_ROUNDED,
    "skipped": ft.Icons.REMOVE_CIRCLE_OUTLINE_ROUNDED,
    "error": ft.Icons.ERROR_ROUNDED,
    "cancelled": ft.Icons.CANCEL_ROUNDED,
    "sending": ft.Icons.UPLOAD_ROUNDED,
    "sent": ft.Icons.CHECK_CIRCLE_ROUNDED,
}


@dataclass
class PushTask:
    """Phone transfer shown in the same list as downloads."""
    name: str
    total: int = 0
    done: int = 0
    sent: int = 0
    skipped: int = 0
    current: str = ""
    status: str = "running"  # running | done | error | cancelled
    error: str = ""
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    cancel: bool = False


class Chip:
    """Status capsule that keeps its controls and only changes text and colour."""

    def __init__(self) -> None:
        self.text = ft.Text("", size=10, font_family=th.FONT_MEDIUM)
        self.view = ft.Container(self.text, border_radius=th.CAPSULE,
                                 padding=ft.Padding.symmetric(horizontal=8, vertical=1))
        self._color = None

    def set(self, label: str, color: str) -> None:
        self.text.value = label
        if color != self._color:
            self._color = color
            self.text.color = color
            self.view.border = ft.Border.all(1, color)


class ItemRow:
    """One track inside an expanded card; reused between redraws."""

    def __init__(self) -> None:
        self.icon = ft.Icon(ITEM_ICON["queued"], size=13)
        self.num = ft.Text("", size=10, color=th.FAINT, width=22)
        self.title = ft.Text("", size=11, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.right = ft.Text("", size=10, max_lines=1)
        self.view = ft.Container(height=25, content=ft.Row([self.icon, self.num, self.title, self.right], spacing=8))

    def set(self, job: Job, it: Item) -> None:
        color = STATUS_COLOR.get(it.status, th.MUTED)
        right = ""
        left = job.item_left(it) if it.status in ("downloading", "processing", "queued") else None
        if it.status == "downloading":
            right = f"{it.progress * 100:.0f}%  {th.fmt_speed(it.speed)}"
        elif it.status == "processing":
            right = t("st_processing")
        if left is not None:
            right = f"{right}  ~{th.fmt_time(left)}".strip()
        elif it.status == "error":
            right = humanize_error(it.error)[:80]
        elif it.status in ("done", "skipped"):
            right = t(f"st_{it.status}")
        self.icon.icon, self.icon.color = ITEM_ICON.get(it.status), color
        self.num.value = f"{it.track.number:02}" if it.track.number else "··"
        self.title.value = it.track.title
        self.title.color = th.TEXT if it.status != "skipped" else th.MUTED
        self.right.value, self.right.color = right, color
        self.view.tooltip = it.error or None


def humanize_error(msg: str) -> str:
    if "not a bot" in msg or "Sign in to confirm" in msg:
        return t("err_bot")
    if "cookies database" in msg or "could not copy" in msg or "Failed to decrypt" in msg:
        return t("err_cookies")
    if msg in ("nothing",) or (msg.startswith("err_") and msg in STRINGS):
        return t(msg)
    return msg


class JobCard:
    def __init__(self, panel: "DownloadsPanel", job: Job):
        self.panel = panel
        self.job = job
        self.expanded = False
        self.icon = ft.Icon(KIND_ICON.get(job.link.kind, ft.Icons.MUSIC_NOTE_ROUNDED), size=18, color=th.TEXT)
        self.title = ft.Text("", size=13, color=th.TEXT, font_family=th.FONT_MEDIUM, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self.chip = Chip()
        self.rows: list[ItemRow] = []
        self.counts = th.label("", 11)
        self.times = th.label("", 11)
        self.current = ft.Text("", size=11, color=th.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.error = ft.Text("", size=11, color=th.ERROR, visible=False, selectable=True)
        self.bar = ft.ProgressBar(value=0, height=3, color=th.ACCENT, bgcolor=th.BORDER,
                                  border_radius=th.CAPSULE)
        # created once: the card is redrawn several times a second and a replaced button loses the click
        self.expand_btn = th.icon_btn(ft.Icons.EXPAND_MORE_ROUNDED, self._toggle, tooltip=t("show_tracks"))
        self.retry_btn = th.icon_btn(ft.Icons.REFRESH_ROUNDED, lambda e: panel.downloader.retry(self.job),
                                     tooltip=t("retry"), color=th.ACCENT)
        self.cancel_btn = th.icon_btn(ft.Icons.CLOSE_ROUNDED, lambda e: panel.downloader.cancel(self.job),
                                      tooltip=t("cancel"))
        self.remove_btn = th.icon_btn(ft.Icons.DELETE_OUTLINE_ROUNDED, lambda e: panel.downloader.remove(self.job),
                                      tooltip=t("remove"))
        self.buttons = ft.Row([self.expand_btn, self.retry_btn, self.cancel_btn, self.remove_btn],
                              spacing=0, tight=True)
        self.items = ft.Column(spacing=1, visible=False)
        self.items_box = ft.Container(self.items, visible=False, height=None)
        self.view = ft.Container(
            bgcolor=th.SURFACE,
            border=ft.Border.all(1, th.BORDER),
            border_radius=th.SHARP,
            padding=ft.Padding.only(left=14, right=8, top=10, bottom=10),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row([self.icon, self.title, self.chip.view, self.buttons], spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    self.bar,
                    ft.Row([self.counts, self.times], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.current,
                    self.error,
                    self.items_box,
                ],
            ),
        )
        self.refresh()

    def _toggle(self, e=None):
        self.expanded = not self.expanded
        self.refresh()
        self.view.update()

    def refresh(self) -> None:
        j = self.job
        self.title.value = j.title
        status = j.status
        if self.panel.downloader.paused.is_set() and status in ("running", "resolving"):
            label = t("paused")
        else:
            label = t(f"st_{status}")
        self.chip.set(label, STATUS_COLOR.get(status, th.MUTED))

        total = len(j.items)
        finished = j.count("done", "skipped")
        failed = j.count("error")
        active = next((i for i in j.items if i.status in ("downloading", "processing")), None)
        partial = active.progress if active else 0.0
        if status == "resolving" and not total:
            self.bar.value = None
        else:
            self.bar.value = (finished + failed + partial) / total if total else (1.0 if status == "done" else 0)
        self.bar.color = th.ERROR if status == "error" and not finished else th.ACCENT

        parts = [t("tracks_count", done=finished, total=total if j.resolved else f"{total}+")]
        if failed:
            parts.append(t("failed_count", n=failed))
        skipped = j.count("skipped")
        if skipped:
            parts.append(t("skipped_count", n=skipped))
        self.counts.value = "  ·  ".join(parts)
        eta = j.eta if status in ("running", "resolving") else None
        self.times.value = f"{t('elapsed')} {th.fmt_time(j.elapsed)}" + (
            f"   {t('left')} ~{th.fmt_time(eta)}" if eta else "")

        if active:
            pct = f"{active.progress * 100:.0f}%"
            speed = th.fmt_speed(active.speed)
            left = j.item_left(active)
            eta_tr = th.fmt_time(left) if left is not None else ""
            el = th.fmt_time(time.monotonic() - active.started) if active.started else ""
            bits = [f"▶ {active.track.title}", pct]
            if active.status == "processing":
                bits[1] = t("st_processing")
            if speed:
                bits.append(speed)
            if el:
                bits.append(el)
            if eta_tr:
                bits.append(f"{t('left')} ~{eta_tr}")
            self.current.value = "   ".join(bits)
            self.current.color = th.ACCENT
            self.current.visible = True
        else:
            self.current.visible = False

        err = j.error or next((i.error for i in reversed(j.items) if i.status == "error"), "")
        self.error.value = humanize_error(err)
        self.error.visible = bool(err)

        self.expand_btn.visible = total > 1 or bool(total and self.expanded)
        self.expand_btn.icon = ft.Icons.EXPAND_LESS_ROUNDED if self.expanded else ft.Icons.EXPAND_MORE_ROUNDED
        self.retry_btn.visible = status in ("error", "cancelled") or (status == "done" and bool(failed))
        self.cancel_btn.visible = status in ("queued", "running", "resolving")
        self.remove_btn.visible = not self.cancel_btn.visible

        self.items_box.visible = self.expanded
        self.items.visible = self.expanded
        if self.expanded:
            items = list(j.items)
            while len(self.rows) < len(items):
                self.rows.append(ItemRow())
            del self.rows[len(items):]
            for row, it in zip(self.rows, items):
                row.set(j, it)
            if len(self.items.controls) != len(self.rows):
                self.items.controls = [r.view for r in self.rows]
            self.items_box.height = min(len(self.rows) * 26 + 4, 320)
            self.items.scroll = ft.ScrollMode.AUTO
        elif self.rows:
            self.rows = []  # collapsed: free the rows of long artist pages
            self.items.controls = []


class PushCard:
    def __init__(self, panel: "DownloadsPanel", task: PushTask):
        self.panel = panel
        self.job = task
        self.title = ft.Text("", size=13, color=th.TEXT, font_family=th.FONT_MEDIUM, expand=True, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS)
        self.chip = Chip()
        self.bar = ft.ProgressBar(value=0, height=3, color=th.ACCENT, bgcolor=th.BORDER, border_radius=th.CAPSULE)
        self.info = th.label("", 11)
        self.current = ft.Text("", size=11, color=th.ACCENT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.error = ft.Text("", size=11, color=th.ERROR, visible=False, selectable=True)
        # created once: a button replaced on every redraw loses the click
        self.cancel_btn = th.icon_btn(ft.Icons.CLOSE_ROUNDED, self._cancel, tooltip=t("cancel"))
        self.remove_btn = th.icon_btn(ft.Icons.DELETE_OUTLINE_ROUNDED, self._remove, tooltip=t("remove"))
        self.buttons = ft.Row([self.cancel_btn, self.remove_btn], spacing=0, tight=True)
        self.view = ft.Container(
            bgcolor=th.SURFACE, border=ft.Border.all(1, th.BORDER), border_radius=th.SHARP,
            padding=ft.Padding.only(left=14, right=8, top=10, bottom=10),
            content=ft.Column(spacing=6, controls=[
                ft.Row([ft.Icon(KIND_ICON["push"], size=18, color=th.TEXT), self.title, self.chip.view, self.buttons],
                       spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.bar, self.info, self.current, self.error,
            ]),
        )
        self.refresh()

    def refresh(self) -> None:
        p = self.job
        self.title.value = t("push_title", name=p.name)
        status = "sending" if p.status == "running" else ("sent" if p.status == "done" else p.status)
        self.chip.set(t(f"st_{status}"), STATUS_COLOR.get(status, th.MUTED))
        self.bar.value = p.done / p.total if p.total else (None if p.status == "running" else 1)
        elapsed = (p.finished or time.monotonic()) - p.started
        self.info.value = (f"{p.done} / {p.total}   ·   " + t("push_done", sent=p.sent, skipped=p.skipped)
                           + f"   ·   {t('elapsed')} {th.fmt_time(elapsed)}")
        self.current.value = f"▶ {p.current}" if p.current and p.status == "running" else ""
        self.current.visible = bool(self.current.value)
        self.error.value = p.error
        self.error.visible = bool(p.error)
        self.cancel_btn.visible = p.status == "running"
        self.remove_btn.visible = not self.cancel_btn.visible

    def _cancel(self, e):
        self.job.cancel = True

    def _remove(self, e):
        self.panel.remove_push(self.job)


class DownloadsPanel:
    def __init__(self, downloader: Downloader, input_row: ft.Control, on_history):
        self.downloader = downloader
        self.pushes: list[PushTask] = []
        self.cards: dict[int, JobCard | PushCard] = {}
        self.list = ft.ListView(expand=True, spacing=8, padding=ft.Padding.symmetric(horizontal=16, vertical=4))
        self.empty = ft.Container(
            expand=True, alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Container(
                        width=72, height=72, shape=ft.BoxShape.CIRCLE, border=ft.Border.all(1, th.BORDER),
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=30, color=th.ACCENT),
                    ),
                    th.label(t("downloads_empty"), 12, th.MUTED, text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, tight=True,
            ),
        )
        self.pause_btn = th.capsule(t("pause_all"), self._toggle_pause, icon=ft.Icons.PAUSE_ROUNDED)
        self._paused_shown = False
        self.summary = th.label("", 11)
        self.body = ft.Stack([self.list, self.empty], expand=True)
        self.view = ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Container(
                    padding=ft.Padding.only(left=16, right=16, top=4),
                    content=ft.Row(
                        [
                            th.heading(t("downloads"), 11),
                            self.summary,
                            ft.Container(expand=True),
                            self.pause_btn,
                            th.capsule(t("history"), lambda e: on_history(), icon=ft.Icons.HISTORY_ROUNDED),
                            th.capsule(t("clear_done"), self._clear, icon=ft.Icons.CLEAR_ALL_ROUNDED),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                self.body,
                input_row,
            ],
        )

    def _toggle_pause(self, e):
        self.downloader.set_paused(not self.downloader.paused.is_set())

    def _clear(self, e):
        self.pushes = [p for p in self.pushes if p.status == "running"]
        self.downloader.clear_finished()

    def add_push(self, task: PushTask) -> None:
        self.pushes.insert(0, task)

    def remove_push(self, task: PushTask) -> None:
        if task in self.pushes:
            self.pushes.remove(task)
        self.sync()
        self.view.update()

    def sync(self) -> None:
        """Rebuild the list from current jobs, reusing cards."""
        entries: list[JobCard | PushCard] = []
        alive = set()
        for p in self.pushes:
            key = id(p)
            alive.add(key)
            card = self.cards.get(key) or PushCard(self, p)
            card.refresh()
            self.cards[key] = card
            entries.append(card)
        for j in self.downloader.jobs:
            key = id(j)
            alive.add(key)
            card = self.cards.get(key) or JobCard(self, j)
            card.refresh()
            self.cards[key] = card
            entries.append(card)
        for key in list(self.cards):
            if key not in alive:
                del self.cards[key]
        views = [c.view for c in entries]
        if len(views) != len(self.list.controls) or any(a is not b for a, b in zip(views, self.list.controls)):
            self.list.controls = views
        self.empty.visible = not entries

        paused = self.downloader.paused.is_set()
        if paused != self._paused_shown:
            self._paused_shown = paused
            new_btn = th.capsule(t("resume_all") if paused else t("pause_all"), self._toggle_pause,
                                 icon=ft.Icons.PLAY_ARROW_ROUNDED if paused else ft.Icons.PAUSE_ROUNDED,
                                 selected=paused)
            self.pause_btn.content, self.pause_btn.bgcolor, self.pause_btn.border = (
                new_btn.content, new_btn.bgcolor, new_btn.border)
        jobs = self.downloader.jobs
        active = sum(1 for j in jobs if j.status in ("running", "resolving", "queued"))
        done = sum(j.count("done") for j in jobs)
        self.summary.value = f"{active} · {done} ✓" if jobs else ""
