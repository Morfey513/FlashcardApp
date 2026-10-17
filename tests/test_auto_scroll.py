"""Guard Qt auto-scroll setup against widgets deleted during a re-render."""

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from src.ui.auto_scroll import AutoScrollArea, AutoScrollTextBrowser


@pytest.mark.parametrize("scroll_type", [AutoScrollArea, AutoScrollTextBrowser])
def test_deleted_content_is_ignored(scroll_type):
    scroll = scroll_type()
    content = QWidget()
    sip.delete(content)

    scroll.track_auto_scroll_content(content)
