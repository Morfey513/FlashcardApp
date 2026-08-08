import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.flashcard_viewer import FlippableCard


def test_flip_animation_switches_the_visible_side_at_its_midpoint():
    app = QApplication.instance() or QApplication([])
    card = FlippableCard()

    assert card.front_widget.isHidden() is False
    assert card.back_widget.isHidden() is True

    card.flip()
    card.animation.stop()
    card.rotation = 91
    assert card.front_widget.isHidden() is True
    assert card.back_widget.isHidden() is False

    card.flip()
    card.animation.stop()
    card.rotation = 89
    assert card.front_widget.isHidden() is False
    assert card.back_widget.isHidden() is True

    # Keep a reference so the QApplication remains alive for this test.
    assert app is not None
