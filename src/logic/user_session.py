# src/logic/user_session.py

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class UserSession:
    """Manages the current user session and permissions."""

    def __init__(self):
        self.current_user: Optional[Dict] = None
        self.is_guest = True

    def login(self, user_data: Dict):
        """Set current user from authentication."""
        self.current_user = user_data
        self.is_guest = False
        logger.info(f"Session started for: {user_data.get('name')}")

    def logout(self):
        """Clear current user session."""
        logger.info(f"Session ended for: {self.current_user.get('name') if self.current_user else 'guest'}")
        self.current_user = None
        self.is_guest = True

    def get_role(self) -> str:
        """Get current user role."""
        if self.is_guest or not self.current_user:
            return "guest"
        return self.current_user.get("role", "guest")

    def get_name(self) -> str:
        """Get current user name."""
        if self.is_guest or not self.current_user:
            return "Guest"
        return self.current_user.get("name", "User")

    def can_edit(self) -> bool:
        """Check if user has editor permissions."""
        return self.get_role() in ("teacher", "admin")

    def is_authenticated(self) -> bool:
        """Check if user is logged in."""
        return not self.is_guest and self.current_user is not None