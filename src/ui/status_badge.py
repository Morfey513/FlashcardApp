"""Shared presentation helpers for content visibility/status badges."""

from PyQt6.QtWidgets import QMessageBox


_STATUS_ICONS = {
    "public": "🌐",
    "class_only": "🔑",
    "private": "🔒",
    "draft": "🔒",
    "locked": "🔒",
    "rejected": "⚠️",
    "banned": "⛔",
}


def format_status_badge(status, label=None):
    """Return the compact icon-plus-label text used by content badges."""
    normalized = str(status or "").lower().replace("-", "_").replace(" ", "_")
    display_label = label or normalized.replace("_", "-").title()
    return f"{_STATUS_ICONS.get(normalized, '•')} {display_label}"


def show_moderation_reason(parent, status, reason):
    """Display the owner-visible explanation for a moderation decision."""
    if status not in {"rejected", "banned"}:
        QMessageBox.information(
            parent, "Content status", f"Status: {status.replace('_', ' ').title()}"
        )
        return
    QMessageBox.information(
        parent,
        f"Content {status.title()}",
        f"Status: {status.title()}\n\nReason: {reason or 'No reason was provided by the moderator.'}",
    )
