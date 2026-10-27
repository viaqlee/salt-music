"""Left sidebar: local music grouped by artist -> album -> track."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from .. import naming
from ..i18n import t
from ..library import LibAlbum, LibArtist, LibTrack
from . import theme as th


class LibraryPanel:
    def __init__(self, on_play: Callable, on_select: Callable[[], None]):
        self.on_play = on_play
        self.on_select = on_select
        self.artists: list[LibArtist] = []
        self.selected: set[Path] = set()  # track files picked for the phone
        # tiles are reused between rescans so open artists / albums stay open
        self._artist_tiles: dict[str, ft.ExpansionTile] = {}
        self._album_tiles: dict[tuple[str, str], ft.ExpansionTile] = {}
        self._opened: set = set()
        self.filter = th.field(hint_text=t("filter"), prefix_icon=ft.Icons.SEARCH_ROUNDED, on_change=self._on_filter,
                               border_radius=th.CAPSULE, content_padding=ft.Padding.symmetric(horizontal=12, vertical=6))
        self.count = th.label("", 10)
        self.list = ft.ListView(expand=True, spacing=2, padding=ft.Padding.only(left=4, right=4, bottom=8))
        self.view = ft.Column(
            expand=True,
            spacing=8,
            controls=[
                ft.Container(
                    padding=ft.Padding.only(left=12, right=12, top=4),
                    content=ft.Row([th.heading(t("library"), 11), self.count],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ),
                ft.Container(self.filter, padding=ft.Padding.symmetric(horizontal=10)),
                self.list,
            ],
        )

    def set_artists(self, artists: list[LibArtist]) -> None:
        self.artists = artists
        alive = {tr.path for a in artists for tr in a.tracks}
        if not self.selected <= alive:
            self.selected &= alive
            self.on_select()
        self._render()

    def selected_tracks(self) -> list[LibTrack]:
        return [tr for a in self.artists for tr in a.tracks if tr.path in self.selected]

    def clear_selection(self) -> None:
        self.selected.clear()
        self._render()
        self.list.update()
        self.on_select()

    def _toggle(self, tracks: list[LibTrack]) -> None:
        paths = {tr.path for tr in tracks}
        if paths <= self.selected:
            self.selected -= paths
        else:
            self.selected |= paths
        self._render()
        self.list.update()
        self.on_select()

    def _circle(self, tracks: list[LibTrack], size: float = 16) -> ft.Control:
        """Selection mark: empty, partly picked (dot) or fully picked (check)."""
        n = sum(1 for tr in tracks if tr.path in self.selected)
        icon = (ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED if n == 0 else
                ft.Icons.CHECK_CIRCLE_ROUNDED if n == len(tracks) else ft.Icons.ADJUST_ROUNDED)
        return th.icon_btn(icon, lambda e, tr=tracks: self._toggle(tr), tooltip=t("select_for_phone"),
                           color=th.ACCENT if n else th.FAINT, size=size)

    def _on_filter(self, e):
        self._render()
        self.list.update()

    def _render(self) -> None:
        q = naming.key(self.filter.value or "")
        shown = [a for a in self.artists if not q or q in naming.key(a.name)
                 or any(q in naming.key(al.title) for al in a.albums.values())]
        total = sum(len(a.tracks) for a in self.artists)
        self.count.value = f"{len(self.artists)} · {total}"
        if not shown:
            self.list.controls = [ft.Container(th.label(t("library_empty"), 11, th.FAINT), padding=12)]
            return
        self.list.controls = [self._artist_tile(a) for a in shown]
        alive = {naming.key(a.name) for a in self.artists}
        self._artist_tiles = {k: v for k, v in self._artist_tiles.items() if k in alive}
        self._album_tiles = {k: v for k, v in self._album_tiles.items() if k[0] in alive}

    def _remember(self, key, e) -> None:
        opened = str(e.data).lower() == "true"
        e.control.expanded = opened  # keep Python in sync, or the next update would collapse it
        if opened:
            self._opened.add(key)
        else:
            self._opened.discard(key)

    def _artist_tile(self, a: LibArtist) -> ft.Control:
        key = naming.key(a.name)
        avatar = ft.Container(
            width=30, height=30, shape=ft.BoxShape.CIRCLE, bgcolor=th.SURFACE_HI,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS, alignment=ft.Alignment.CENTER,
            content=(ft.Image(src=str(a.image), width=30, height=30, fit=ft.BoxFit.COVER) if a.image
                     else ft.Text(a.name[:1].upper(), size=12, color=th.TEXT, font_family=th.FONT_BOLD)),
        )
        tracks = a.tracks
        albums = sorted(a.albums.values(), key=lambda al: naming.key(al.title))
        subtitle = th.label(f"{len(albums)} · {len(tracks)}", 10)
        trailing = ft.Row(
                [
                    th.icon_btn(ft.Icons.PLAY_ARROW_ROUNDED, lambda e, tr=tracks: self.on_play(tr, 0),
                                tooltip=t("play_all"), size=16),
                    self._circle(tracks),
                ],
                tight=True, spacing=0,
            )
        children = [self._album_tile(a, al) for al in albums]
        tile = self._artist_tiles.get(key)
        if tile:
            tile.leading, tile.subtitle, tile.trailing, tile.controls = avatar, subtitle, trailing, children
            return tile
        tile = self._artist_tiles[key] = ft.ExpansionTile(
            leading=avatar,
            title=ft.Text(a.name, size=12, color=th.TEXT, font_family=th.FONT_MEDIUM, max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS),
            subtitle=subtitle,
            trailing=trailing,
            expanded=key in self._opened,
            on_change=lambda e, k=key: self._remember(k, e),
            tile_padding=ft.Padding.only(left=8, right=0),
            controls_padding=ft.Padding.only(left=14),
            shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            collapsed_shape=ft.RoundedRectangleBorder(radius=th.SHARP),
            bgcolor=th.SURFACE,
            dense=True,
            controls=children,
        )
        return tile

    def _album_tile(self, a: LibArtist, al: LibAlbum) -> ft.Control:
        key = (naming.key(a.name), naming.key(al.title))
        subtitle = th.label(str(len(al.tracks)), 10)
        trailing = ft.Row(
                [
                    th.icon_btn(ft.Icons.PLAY_ARROW_ROUNDED, lambda e, tr=al.tracks: self.on_play(tr, 0), size=15),
                    self._circle(al.tracks, 15),
                ],
                tight=True, spacing=0,
            )
        rows = [self._track_row(al.tracks, i) for i in range(len(al.tracks))]
        # buttons live in the title row: in a narrow sidebar the tile's trailing slot gets clipped
        title = ft.Row([
            ft.Column([ft.Text(al.title, size=11, color=th.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                       subtitle], spacing=0, expand=True),
            trailing,
        ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        tile = self._album_tiles.get(key)
        if tile:
            tile.title, tile.controls = title, rows
            return tile
        tile = self._album_tiles[key] = ft.ExpansionTile(
            title=title,
            leading=ft.Icon(ft.Icons.ALBUM_ROUNDED, size=16, color=th.MUTED),
            show_trailing_icon=False,
            expanded=key in self._opened,
            on_change=lambda e, k=key: self._remember(k, e),
            tile_padding=ft.Padding.only(left=4, right=0),
            dense=True,
            controls=rows,
        )
        return tile

    def _track_row(self, tracks: list[LibTrack], i: int) -> ft.Control:
        tr = tracks[i]
        return ft.Container(
            padding=ft.Padding.only(left=10, right=0, top=0, bottom=0),
            border_radius=th.SHARP,
            ink=True,
            on_click=lambda e: self.on_play(tracks, i),
            content=ft.Row(
                [
                    ft.Text(f"{tr.number:02}" if tr.number else "··", size=10, color=th.FAINT, width=22),
                    ft.Text(tr.title, size=11, color=th.TEXT, expand=True, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    self._circle([tr], 14),
                ],
                spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
