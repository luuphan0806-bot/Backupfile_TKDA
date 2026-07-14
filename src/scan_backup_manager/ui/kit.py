"""Cyan cyberpunk component kit.

One shared set of primitives every view builds from, so the whole app reads as
a single designed product instead of ad-hoc Flet defaults. Presentation only --
these helpers never own state or event logic.
"""
from __future__ import annotations

import flet as ft

from . import theme


# ---------------------------------------------------------------------------
# Atoms
# ---------------------------------------------------------------------------
def glow(color: str | None = None, *, blur: float = 24, opacity: float = 0.35, y: float = 8) -> ft.BoxShadow:
    color = color or theme.primary()
    return ft.BoxShadow(
        blur_radius=blur,
        spread_radius=0,
        color=ft.Colors.with_opacity(opacity, color),
        offset=ft.Offset(0, y),
    )


def eyebrow(text: str, *, color: str | None = None) -> ft.Text:
    """Uppercase, letter-spaced micro-label -- the app's 'techno' texture
    without a bundled display font."""
    return ft.Text(
        text.upper(),
        size=11,
        color=color or theme.primary(),
        style=ft.TextStyle(weight=ft.FontWeight.BOLD, letter_spacing=1.6),
    )


def title_text(text: str, *, size: int = 22, color: str | None = None) -> ft.Text:
    return ft.Text(text, size=size, weight=ft.FontWeight.BOLD, color=color or theme.text_primary())


def muted_text(text: str, *, size: int = 13) -> ft.Text:
    return ft.Text(text, size=size, color=theme.text_muted())


def logo_mark(size: int = 34) -> ft.Control:
    """Small glowing diamond brand mark."""
    return ft.Container(
        width=size,
        height=size,
        border_radius=9,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[theme.primary(), "#3D5AFE"],
        ),
        shadow=glow(theme.primary(), blur=18, opacity=0.35 if theme.is_light_mode() else 0.5, y=0),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(ft.Icons.SHIELD_MOON, color=theme.bg_base(), size=size * 0.56),
    )


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
def _primary_style() -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=theme.primary(),
        color="#FFFFFF" if theme.is_light_mode() else theme.bg_base(),
        shape=ft.RoundedRectangleBorder(radius=10),
        padding=ft.Padding.symmetric(vertical=16, horizontal=20),
        text_style=ft.TextStyle(weight=ft.FontWeight.BOLD, letter_spacing=0.4),
        elevation=0,
    )


def _ghost_style(*, accent: str | None = None) -> ft.ButtonStyle:
    accent = accent or theme.primary()
    return ft.ButtonStyle(
        color=accent,
        side=ft.BorderSide(1, ft.Colors.with_opacity(0.55, accent)),
        shape=ft.RoundedRectangleBorder(radius=10),
        padding=ft.Padding.symmetric(vertical=16, horizontal=18),
        text_style=ft.TextStyle(weight=ft.FontWeight.BOLD, letter_spacing=0.4),
    )


def primary_button(text: str, *, on_click=None, icon=None, **kwargs) -> ft.FilledButton:
    return ft.FilledButton(text, icon=icon, on_click=on_click, style=_primary_style(), **kwargs)


def ghost_button(text: str, *, on_click=None, icon=None, accent: str | None = None, **kwargs) -> ft.OutlinedButton:
    return ft.OutlinedButton(text, icon=icon, on_click=on_click, style=_ghost_style(accent=accent), **kwargs)


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
def card(
    content: ft.Control,
    *,
    glow_color: str | None = None,
    padding: int = 20,
    radius: int = 8,
    bgcolor: str | None = None,
    border_color: str | None = None,
    expand: bool | int | None = None,
) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        bgcolor=bgcolor or theme.surface(),
        border=ft.Border.all(1, border_color or theme.line()),
        shadow=glow(glow_color) if glow_color else None,
        expand=expand,
    )


def section(title: str, subtitle: str, content: ft.Control, *, icon=None) -> ft.Control:
    header_left: list[ft.Control] = [
        ft.Container(
            width=4,
            height=40,
            border_radius=4,
            bgcolor=theme.primary(),
            shadow=glow(theme.primary(), blur=12, opacity=0.30 if theme.is_light_mode() else 0.5, y=0),
        ),
    ]
    if icon is not None:
        header_left.append(ft.Icon(icon, color=theme.primary(), size=20))
    header_left.append(
        ft.Column(
            spacing=2,
            controls=[
                title_text(title, size=16),
                muted_text(subtitle, size=12) if subtitle else ft.Container(height=0),
            ],
        )
    )
    return card(
        ft.Column(
            spacing=14,
            controls=[
                ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=header_left),
                ft.Divider(height=1, color=theme.line()),
                content,
            ],
        ),
    )


def page_header(title: str, subtitle: str | None = None, *, eyebrow_text: str | None = None, actions: list[ft.Control] | None = None) -> ft.Control:
    left = ft.Column(
        spacing=3,
        controls=[
            *( [eyebrow(eyebrow_text)] if eyebrow_text else [] ),
            title_text(title, size=24),
            *( [muted_text(subtitle)] if subtitle else [] ),
        ],
    )
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[left, ft.Row(spacing=8, controls=actions or [])],
    )


# ---------------------------------------------------------------------------
# Data display
# ---------------------------------------------------------------------------
def stat_tile(title: str, value, color: str, *, icon=None) -> ft.Control:
    head: list[ft.Control] = []
    if icon is not None:
        head.append(ft.Icon(icon, color=color, size=16))
    head.append(
        ft.Text(title.upper(), size=11, color=color, style=ft.TextStyle(weight=ft.FontWeight.BOLD, letter_spacing=1.0))
    )
    return ft.Container(
        expand=True,
        padding=18,
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.10, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.35, color)),
        shadow=glow(color, blur=18, opacity=0.12, y=6),
        content=ft.Column(
            spacing=6,
            controls=[
                ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=head),
                ft.Text(str(value), size=28, weight=ft.FontWeight.BOLD, color=color),
            ],
        ),
    )


def badge(label: str, color: str) -> ft.Control:
    return ft.Container(
        padding=ft.Padding.symmetric(vertical=3, horizontal=10),
        border_radius=999,
        bgcolor=ft.Colors.with_opacity(0.15, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.45, color)),
        content=ft.Text(label, size=11, color=color, weight=ft.FontWeight.BOLD),
    )


def status_badge(status: str) -> ft.Control:
    return badge(theme.status_label(status), theme.status_color(status))


def tab_bar(items, selected_index: int, on_select) -> ft.Control:
    """Segmented control. `items` is a list of str or (label, icon) tuples.
    Active tab = filled cyan, others = ghost."""
    buttons: list[ft.Control] = []
    for index, item in enumerate(items):
        if isinstance(item, tuple):
            label, icon = item
        else:
            label, icon = item, None
        if index == selected_index:
            buttons.append(
                ft.FilledButton(label, icon=icon, style=_primary_style(), on_click=lambda _e, i=index: on_select(i))
            )
        else:
            buttons.append(
                ft.OutlinedButton(label, icon=icon, style=_ghost_style(), on_click=lambda _e, i=index: on_select(i))
            )
    return ft.Container(
        padding=8,
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.07, theme.primary()),
        border=ft.Border.all(1, theme.line()),
        content=ft.Row(spacing=8, wrap=True, controls=buttons),
    )


def style_table(table: ft.DataTable) -> ft.DataTable:
    """Apply consistent cyberpunk theming to a DataTable in place (cyan heading
    band, hairline row separators, no heavy outer border). Returns the same
    table for chaining."""
    table.heading_row_color = ft.Colors.with_opacity(0.11 if theme.is_light_mode() else 0.12, theme.primary())
    table.heading_text_style = ft.TextStyle(
        weight=ft.FontWeight.BOLD, color=theme.primary(), letter_spacing=0.5, size=12
    )
    table.horizontal_lines = ft.BorderSide(1, ft.Colors.with_opacity(0.14 if theme.is_light_mode() else 0.08, theme.primary()))
    table.border = ft.Border.all(0, ft.Colors.TRANSPARENT)
    table.heading_row_height = max(table.heading_row_height or 0, 46)
    return table


def dialog(
    title: str,
    content: ft.Control,
    actions: list[ft.Control],
    *,
    icon=None,
    width: int | None = None,
) -> ft.AlertDialog:
    """Themed AlertDialog: cyan-accented dark surface, rounded hairline
    border and consistent title/content padding, matching the rest of the
    cyberpunk design system instead of Flet's plain default popup."""
    title_controls: list[ft.Control] = []
    if icon is not None:
        title_controls.append(ft.Icon(icon, color=theme.primary(), size=20))
    title_controls.append(title_text(title, size=17))
    body = ft.Container(width=width, content=content) if width else content
    return ft.AlertDialog(
        modal=True,
        bgcolor=theme.surface_high(),
        shape=ft.RoundedRectangleBorder(
            radius=8,
            side=ft.BorderSide(1, theme.line_strong()),
        ),
        shadow_color=ft.Colors.with_opacity(0.35, theme.primary()),
        barrier_color=ft.Colors.with_opacity(0.55, theme.bg_base()),
        title=ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=title_controls),
        title_padding=ft.Padding.symmetric(horizontal=24, vertical=20),
        content=body,
        content_padding=ft.Padding.symmetric(horizontal=24, vertical=12),
        actions=actions,
        actions_padding=ft.Padding.symmetric(horizontal=20, vertical=16),
        actions_alignment=ft.MainAxisAlignment.END,
    )


def table_frame(table: ft.Control) -> ft.Control:
    """Styled + horizontally scrollable wrapper for a primary data table.
    Mutates the DataTable to apply consistent cyberpunk theming, then frames
    it in a bordered card."""
    if isinstance(table, ft.DataTable):
        style_table(table)
    return ft.Container(
        content=theme.scrollable_table(table),
        padding=6,
        bgcolor=theme.surface(),
        border_radius=8,
        border=ft.Border.all(1, theme.line()),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
