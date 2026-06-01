#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tray/status-bar integration for the packaged desktop app."""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw
import pystray


class WindowsTrayApp:
    """Tray/status-bar app backed by pystray."""

    def __init__(self, tooltip: str, on_open: Callable[[], None], on_exit: Callable[[], None]):
        self.tooltip = tooltip[:127]
        self.on_open = on_open
        self.on_exit = on_exit
        self._icon = None

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("打开界面", self._handle_open, default=True),
            pystray.MenuItem("退出", self._handle_exit),
        )
        self._icon = pystray.Icon(
            "OutlookEmail",
            self._build_icon(),
            self.tooltip,
            menu,
        )
        self._icon.run()

    def close(self) -> None:
        if self._icon is not None:
            self._icon.stop()

    def _handle_open(self, icon=None, item=None) -> None:
        self.on_open()

    def _handle_exit(self, icon=None, item=None) -> None:
        try:
            self.on_exit()
        finally:
            self.close()

    def _build_icon(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (18, 22, 33, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 10, 58, 54), radius=12, fill=(43, 122, 241, 255))
        draw.rectangle((16, 18, 48, 42), fill=(255, 255, 255, 255))
        draw.polygon([(16, 18), (32, 32), (48, 18)], fill=(214, 231, 255, 255))
        draw.rectangle((22, 40, 42, 46), fill=(214, 231, 255, 255))
        return image
