from html import escape

from pathlib import Path

from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QInputDialog, QTabWidget, QWidget, QTreeWidget, QTreeWidgetItem, QSplitter, QFrame, QScrollArea
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from src.storage.moderation_repository import ModerationRepository
from src.logic.access_control import (
    CONTENT_STATUSES,
    CONTENT_STATUS_LABELS,
    ROLE_LABELS,
    ROLES,
    VISIBILITIES,
    VISIBILITY_LABELS,
)
from src.ui.auto_scroll import AutoScrollTextBrowser
from src.utils.paths import resolve_stored_path


class ZoomableImageScrollArea(QScrollArea):
    """Keep normal scrolling, but reserve Ctrl + wheel for image zooming."""

    def __init__(self, zoom_callback, parent=None):
        super().__init__(parent)
        self._zoom_callback = zoom_callback

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_callback(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)


class ImagePreviewDialog(QDialog):
    """Resizable, bounded image preview with scroll and Ctrl-wheel zoom."""

    MIN_WINDOW_SIZE = (420, 320)
    MAX_WINDOW_SIZE = (1600, 1200)
    MAX_INITIAL_IMAGE_SIZE = (920, 640)
    MIN_INITIAL_IMAGE_SIZE = (480, 360)

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Image preview — {image_path.name}")
        self.setMinimumSize(*self.MIN_WINDOW_SIZE)
        self.setMaximumSize(*self.MAX_WINDOW_SIZE)
        self.source_pixmap = QPixmap(str(image_path))
        self._initial_scale = self._choose_initial_scale()
        self._zoom = self._initial_scale
        self._min_zoom = max(0.12, self._initial_scale * 0.25)
        self._max_zoom = min(5.0, max(2.0, self._initial_scale * 5.0))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.viewer = ZoomableImageScrollArea(self._zoom_by, self)
        self.viewer.setWidgetResizable(False)
        self.viewer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer.setWidget(self.image)
        layout.addWidget(self.viewer)
        self._render_image()

        scaled_size = self.image.size()
        self.resize(
            min(self.MAX_WINDOW_SIZE[0], max(self.MIN_WINDOW_SIZE[0], scaled_size.width() + 40)),
            min(self.MAX_WINDOW_SIZE[1], max(self.MIN_WINDOW_SIZE[1], scaled_size.height() + 60)),
        )

    def _choose_initial_scale(self):
        if self.source_pixmap.isNull():
            return 1.0
        width, height = self.source_pixmap.width(), self.source_pixmap.height()
        max_width, max_height = self.MAX_INITIAL_IMAGE_SIZE
        min_width, min_height = self.MIN_INITIAL_IMAGE_SIZE
        fit_max = min(max_width / width, max_height / height, 1.0)
        # Upscale a small image only enough to make it comfortably reviewable.
        fit_min = min(min_width / width, min_height / height)
        return max(fit_max, min(fit_min, 1.8))

    def _zoom_by(self, factor):
        self._zoom = max(self._min_zoom, min(self._max_zoom, self._zoom * factor))
        self._render_image()

    def _render_image(self):
        if self.source_pixmap.isNull():
            self.image.setText("This image could not be loaded.")
            return
        target_width = max(1, round(self.source_pixmap.width() * self._zoom))
        target_height = max(1, round(self.source_pixmap.height() * self._zoom))
        pixmap = self.source_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image.setPixmap(pixmap)
        self.image.resize(pixmap.size())


class ModerationDialog(QDialog):
    # Calm semantic colors shared by content lifecycle and account states.
    STATUS_COLORS = {
        "published": ("#DCFCE7", "#15803D"),
        "pending_review": ("#E0F2FE", "#0369A1"),
        "draft": ("#F3F4F6", "#4B5563"),
        "rejected": ("#FEF3C7", "#B45309"),
        "banned": ("#FEE2E2", "#B91C1C"),
        "active": ("#DCFCE7", "#15803D"),
    }
    def __init__(self, actor_id, parent=None):
        super().__init__(parent)
        self.actor_id = actor_id
        self.repo = ModerationRepository()
        self.audio_output = QAudioOutput(self)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        self.setWindowTitle("Moderation")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._build_content_tab()
        self._build_users_tab()
        self.refresh()

    def _build_content_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Filter:"))
        self.content_status_filter = QComboBox()
        self.content_status_filter.addItem(CONTENT_STATUS_LABELS["pending_review"], "pending_review")
        self.content_status_filter.addItem("All statuses", "all")
        for status in CONTENT_STATUSES:
            if status != "pending_review":
                self.content_status_filter.addItem(CONTENT_STATUS_LABELS[status], status)
        self.content_status_filter.currentIndexChanged.connect(self._refresh_content)
        filters.addWidget(self.content_status_filter)
        filters.addWidget(QLabel("Visibility:"))
        self.content_visibility_filter = QComboBox()
        self.content_visibility_filter.addItem("All visibility", "all")
        for visibility in VISIBILITIES:
            self.content_visibility_filter.addItem(VISIBILITY_LABELS[visibility], visibility)
        self.content_visibility_filter.currentIndexChanged.connect(self._refresh_content)
        filters.addWidget(self.content_visibility_filter)
        self.content_search = QLineEdit()
        self.content_search.setPlaceholderText("Search content title or author…")
        self.content_search.textChanged.connect(self._refresh_content)
        filters.addWidget(self.content_search, 1)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_content_filters)
        filters.addWidget(clear_button)
        layout.addLayout(filters)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        queue_panel = QWidget()
        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        self.content_list_heading = QLabel("PENDING REVIEW")
        queue_layout.addWidget(self.content_list_heading)
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._show_content_detail)
        queue_layout.addWidget(self.items)
        splitter.addWidget(queue_panel)

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("moderation_detail")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        self.detail_title = QLabel("Select a submission")
        self.detail_title.setObjectName("moderation_detail_title")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("moderation_detail_meta")
        self.detail_meta.setWordWrap(True)
        detail_layout.addWidget(self.detail_meta)
        self.detail_preview = AutoScrollTextBrowser()
        self.detail_preview.setObjectName("moderation_detail_preview")
        self.detail_preview.setOpenLinks(False)
        self.detail_preview.setOpenExternalLinks(False)
        self.detail_preview.setReadOnly(True)
        self.detail_preview.setToolTip("Middle-click to auto-scroll; press Escape to stop")
        self.detail_preview.anchorClicked.connect(self._handle_preview_link)
        self.detail_preview.setHtml("Choose a pending quiz or deck to review its questions/cards.")
        # Let the scrollable review content use the remaining panel height;
        # a separate stretch here left an empty visual gap above the decision.
        detail_layout.addWidget(self.detail_preview, 1)
        self.content_action_heading = QLabel("DECISION")
        detail_layout.addWidget(self.content_action_heading)
        controls = QHBoxLayout()
        self.publish_button = QPushButton("Publish")
        self.reject_button = QPushButton("Reject")
        self.ban_button = QPushButton("Ban")
        self.unban_button = QPushButton("Unban to Draft")
        for button, status in (
            (self.publish_button, "published"), (self.reject_button, "rejected"),
            (self.ban_button, "banned"), (self.unban_button, "draft"),
        ):
            button.clicked.connect(lambda _=False, value=status: self.change_status(value))
            controls.addWidget(button)
        detail_layout.addLayout(controls)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([280, 420])
        layout.addWidget(splitter)
        self.tabs.addTab(tab, "Content")

    def _build_users_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Account management"))
        self.users = QTreeWidget()
        self.users.setColumnCount(5)
        self.users.setHeaderLabels(["Login", "Role", "Status", "Banned at", "Reason"])
        self.users.setColumnWidth(0, 130)
        self.users.setColumnWidth(1, 90)
        self.users.setColumnWidth(2, 85)
        self.users.setColumnWidth(3, 165)
        self.users.currentItemChanged.connect(
            lambda current, _previous: self._sync_selected_user_role(current)
        )
        layout.addWidget(self.users)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.view_content_button = QPushButton("View User's Content")
        self.view_content_button.clicked.connect(self.view_selected_user_content)
        controls.addWidget(self.view_content_button, 1)
        controls.addWidget(QLabel("Role:"))
        self.role_selector = QComboBox()
        self.role_selector.setMinimumWidth(115)
        for role in ROLES:
            self.role_selector.addItem(ROLE_LABELS[role], role)
        controls.addWidget(self.role_selector)
        self.apply_role_button = QPushButton("Apply Role")
        self.apply_role_button.setObjectName("publish_btn")
        self.apply_role_button.clicked.connect(self.apply_selected_role)
        self.apply_role_button.setMinimumWidth(150)
        controls.addWidget(self.apply_role_button)
        self.ban_toggle_button = QPushButton("Ban / Unban")
        self.ban_toggle_button.setObjectName("danger")
        self.ban_toggle_button.clicked.connect(lambda: self.update_user("toggle"))
        self.ban_toggle_button.setMinimumWidth(180)
        controls.addWidget(self.ban_toggle_button)
        layout.addLayout(controls)
        self.tabs.addTab(tab, "Users")

    def refresh(self):
        self.content = [
            item for item in self.repo.get_all_content()
            if item["status"] == "pending_review"
        ]
        self.items.clear()
        for item in self.content:
            icon = "📝" if item["kind"] == "quiz" else "🎴"
            self.items.addItem(f"{icon} {item['name']}")
        self._show_content_detail(self.items.currentRow())
        from src.storage.user_repository import UserRepository
        self.user_data = UserRepository().get_all_users()
        self.users.clear()
        for user in self.user_data:
            banned_at = user.get("banned_at") or "—"
            if "T" in banned_at:
                banned_at = banned_at.replace("T", " ").split("+")[0]
            row = QTreeWidgetItem([
                user["login"], user["role"], user.get("status", "active"),
                banned_at, user.get("ban_reason") or "—",
            ])
            background, foreground = self.STATUS_COLORS.get(
                user.get("status", "active"), ("#F3F4F6", "#4B5563")
            )
            row.setBackground(2, QColor(background))
            row.setForeground(2, QColor(foreground))
            row.setData(0, Qt.ItemDataRole.UserRole, user)
            self.users.addTopLevelItem(row)
        self.users_by_id = {str(user["id"]): user for user in self.user_data}
        self._sync_selected_user_role(self.users.currentItem())
        self._refresh_content()

    def _sync_selected_user_role(self, row):
        """Keep the role selector aligned with the selected account."""
        if not hasattr(self, "role_selector"):
            return
        user = row.data(0, Qt.ItemDataRole.UserRole) if row is not None else None
        is_current_user = bool(user and str(user["id"]) == str(self.actor_id))
        if user:
            self.role_selector.setCurrentIndex(
                max(0, self.role_selector.findData(user.get("role", "student")))
            )
        self.role_selector.setEnabled(bool(user) and not is_current_user)
        self.apply_role_button.setEnabled(bool(user) and not is_current_user)
        self.ban_toggle_button.setEnabled(bool(user) and not is_current_user)

    def apply_selected_role(self):
        self.update_user(self.role_selector.currentData())

    def _refresh_content(self):
        """Apply lifecycle, title, and author filters to the review list."""
        if not hasattr(self, "content_status_filter"):
            return
        status_filter = self.content_status_filter.currentData()
        visibility_filter = self.content_visibility_filter.currentData()
        search = self.content_search.text().strip().casefold()
        self.content = []
        for item in self.repo.get_all_content():
            if status_filter != "all" and item["status"] != status_filter:
                continue
            if visibility_filter != "all" and item.get("visibility") != visibility_filter:
                continue
            author = self._author_login(item.get("owner_id", ""))
            searchable = " ".join((item["name"], str(item.get("owner_id", "")), author)).casefold()
            if search and search not in searchable:
                continue
            self.content.append(item)
        self.items.clear()
        for item in self.content:
            kind = "Quiz" if item["kind"] == "quiz" else "Flashcard"
            row = QListWidgetItem(
                f"{kind}: {item['name']}  "
                f"[{CONTENT_STATUS_LABELS[item['status']]} · {VISIBILITY_LABELS[item['visibility']]}]"
            )
            self._apply_status_colors(row, item["status"])
            self.items.addItem(row)
        label = "ALL STATUSES" if status_filter == "all" else CONTENT_STATUS_LABELS[status_filter].upper()
        if visibility_filter != "all":
            label += f" · {VISIBILITY_LABELS[visibility_filter].upper()}"
        self.content_list_heading.setText(label)
        self._show_content_detail(self.items.currentRow())

    @classmethod
    def _apply_status_colors(cls, item, status):
        background, foreground = cls.STATUS_COLORS.get(status, ("#F3F4F6", "#4B5563"))
        item.setBackground(QColor(background))
        item.setForeground(QColor(foreground))

    def _clear_content_filters(self):
        self.content_status_filter.setCurrentIndex(0)
        self.content_visibility_filter.setCurrentIndex(0)
        self.content_search.clear()

    def _author_login(self, owner_id):
        user = getattr(self, "users_by_id", {}).get(str(owner_id))
        return user["login"] if user else str(owner_id)

    def view_selected_user_content(self):
        row = self.users.currentItem()
        if row is None:
            return
        user = row.data(0, Qt.ItemDataRole.UserRole)
        self.tabs.setCurrentIndex(0)
        self.content_status_filter.setCurrentIndex(1)  # All content
        self.content_search.setText(user["login"])

    def change_status(self, status):
        index = self.items.currentRow()
        if index < 0:
            return
        current_status = self.content[index].get("status")
        if status == "published":
            if self.repo.update_status(self.content[index], status, self.actor_id):
                self.refresh()
            return

        if status == "draft" and current_status == "banned":
            note = "Unbanned by an administrator. Edit the content and submit it for review again."
            if self.repo.update_status(self.content[index], status, self.actor_id, note):
                self.refresh()
            return

        prompt = "Reason for this decision:"
        note, accepted = QInputDialog.getText(self, "Moderation decision", prompt)
        if accepted and not note.strip():
            return
        if accepted and self.repo.update_status(self.content[index], status, self.actor_id, note):
            self.refresh()

    def _show_content_detail(self, index):
        if index < 0 or index >= len(getattr(self, "content", [])):
            self.detail_title.setText("Select a submission")
            self.detail_meta.setText("")
            self.detail_preview.setHtml("Choose a pending quiz or deck to review its questions/cards.")
            self._update_content_actions(None)
            return
        item = self.content[index]
        preview, count = self.repo.get_preview(item)
        self.detail_title.setText(item["name"])
        submitted = (item.get("reviewed_at") or "Unknown").replace("T", " ").split("+")[0]
        status = CONTENT_STATUS_LABELS[item.get("status", "draft")]
        visibility = VISIBILITY_LABELS[item.get("visibility", "private")]
        self.detail_meta.setText(
            f"{item['kind'].title()}  |  Status: {status}  |  Visibility: {visibility}  |  "
            f"Author: {self._author_login(item.get('owner_id', 'Unknown'))}  |  Submitted: {submitted}"
        )
        html = self._format_preview(item["kind"], preview, count)
        reason = (item.get("review_note") or "").strip()
        if reason and item.get("status") in {"rejected", "banned"}:
            html = f"<p><b>Moderator reason:</b> {escape(reason)}</p>" + html
        self.detail_preview.setHtml(html)
        self._update_content_actions(item.get("status"))

    def _update_content_actions(self, status):
        pending = status == "pending_review"
        banned = status == "banned"
        for button in (self.publish_button, self.reject_button, self.ban_button):
            button.setVisible(pending)
        self.unban_button.setVisible(banned)
        self.content_action_heading.setVisible(pending or banned)

    @staticmethod
    def _format_preview(kind, entries, count):
        """Create a concise but complete visual review of submitted content."""
        label = "QUESTIONS" if kind == "quiz" else "CARDS"
        if not entries:
            return f"<b>{label} (0)</b><br>No items in this submission."

        if kind == "flashcard":
            body = []
            for number, card in enumerate(entries, 1):
                hint = str(card.get("hint", "")).strip()
                description = str(card.get("description", "")).strip()
                optional_fields = ""
                if hint:
                    optional_fields += f"<br><b>Hint:</b> {escape(hint)}"
                if description:
                    optional_fields += f"<br><b>Description:</b> {escape(description)}"
                body.append(
                    f"<p><b>Card {number}.</b> {escape(str(card.get('front', 'Untitled')))}<br>"
                    f"<b>Back:</b> {escape(str(card.get('back', '')))}"
                    f"{optional_fields}"
                    f"{ModerationDialog._media_html(card)}</p>"
                )
            return f"<b>{label} ({count})</b>" + "".join(body)

        body = []
        names = {
            "single_choice": "Single Choice",
            "multiple_choice": "Multiple Choice",
            "true_false": "True / False",
            "short_answer": "Short Answer",
            "matching": "Matching",
            "ordering": "Ordering",
        }
        for number, question in enumerate(entries, 1):
            question_type = question.get("type", "short_answer")
            heading = (
                f"<p><b>Q{number}. {escape(str(question.get('question', 'Untitled')))}</b> "
                f"<span style='color:#2467a3'>[{names.get(question_type, question_type)}]</span><br>"
            )
            answer = question.get("answer", "")
            if question_type in {"single_choice", "multiple_choice"}:
                correct = set(answer) if isinstance(answer, list) else {answer}
                lines = []
                for choice in question.get("choices", []):
                    is_correct = choice in correct
                    prefix = "&#9989;" if is_correct else "&bull;"
                    suffix = " <b>(Correct Answer)</b>" if is_correct else ""
                    lines.append(f"{prefix} {escape(str(choice))}{suffix}")
                detail = "<br>".join(lines)
            elif question_type == "true_false":
                detail = f"Answer: &#9989; <b>{'TRUE' if answer else 'FALSE'}</b>"
            elif question_type == "short_answer":
                detail = f"Expected Answer: &quot;{escape(str(answer))}&quot;"
            elif question_type == "matching":
                detail = "<br>".join(
                    f"&bull; {escape(str(pair.get('prompt', '')))} &nbsp;&#10132;&nbsp; {escape(str(pair.get('answer', '')))}"
                    for pair in question.get("pairs", [])
                )
            elif question_type == "ordering":
                detail = "<b>Correct Sequence:</b><br>" + " &nbsp;&#10132;&nbsp; ".join(
                    f"{position}. {escape(str(value))}"
                    for position, value in enumerate(answer if isinstance(answer, list) else [], 1)
                )
            else:
                detail = f"Expected Answer: {escape(str(answer))}"
            body.append(heading + detail + ModerationDialog._media_html(question) + "</p>")
        return f"<b>{label} ({count})</b>" + "".join(body)

    @staticmethod
    def _media_html(entry):
        """Add clickable image previews and a control for every recorded file."""
        parts = []
        image_path = resolve_stored_path(entry.get("image_path") or entry.get("image"))
        if image_path and image_path.is_file():
            uri = escape(image_path.as_uri(), quote=True)
            parts.append(
                f"<br><a href='{uri}' title='Open full-size image'>"
                f"<img src='{uri}' width='110'></a>"
            )

        for field, audio_path in ModerationDialog._recorded_audio_paths(entry):
            uri = escape(audio_path.as_uri(), quote=True)
            label = escape(field.replace("_", " ").title())
            filename = escape(audio_path.name)
            parts.append(
                f"<br><a href='{uri}' title='Play recorded audio'>"
                f"&#9654; Play {label} audio: {filename}</a>"
            )
        return "".join(parts)

    @staticmethod
    def _recorded_audio_paths(entry):
        """Return every valid recorded audio file, labelled by its content field."""
        audio = entry.get("audio") or entry.get("audio_paths") or entry.get("audio_path")
        if isinstance(audio, str):
            audio = {"audio": audio}
        if not isinstance(audio, dict):
            return []
        files = []
        for field, stored_path in audio.items():
            path = resolve_stored_path(stored_path)
            if path and path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a"}:
                files.append((str(field), path))
        return files

    def _handle_preview_link(self, url):
        """Open an image, or play exactly the recorded file that was clicked."""
        if not url.isLocalFile():
            return
        path = Path(url.toLocalFile())
        if not path.is_file():
            return
        if path.suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a"}:
            self.audio_player.stop()
            self.audio_player.setSource(QUrl.fromLocalFile(str(path)))
            self.audio_player.play()
            return
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
            ImagePreviewDialog(path, self).exec()

    def update_user(self, action):
        row = self.users.currentItem()
        if row is None:
            return
        user = row.data(0, Qt.ItemDataRole.UserRole)
        if str(user['id']) == str(self.actor_id):
            return
        from src.storage.user_repository import UserRepository
        repository = UserRepository()
        if action == "toggle":
            if user.get("status") == "active":
                reason, accepted = QInputDialog.getText(self, "Suspend account", "Reason for suspension:")
                if not accepted:
                    return
                repository.update_status(user['id'], "banned", reason)
            else:
                repository.update_status(user['id'], "active")
        else:
            repository.update_role(user['id'], action)
        self.refresh()
