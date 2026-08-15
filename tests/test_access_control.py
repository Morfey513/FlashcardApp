import pytest

from src.logic.access_control import (
    can_ban_accounts,
    can_create_content,
    can_edit_content,
    can_manage_class,
    can_moderate_content,
)


@pytest.mark.parametrize(
    ("role", "create", "edit_own", "edit_other", "manage_own_class", "moderate", "ban"),
    [
        ("guest", False, False, False, False, False, False),
        ("student", False, False, False, False, False, False),
        ("teacher", True, True, False, True, False, False),
        ("admin", True, True, True, False, True, True),
    ],
)
def test_permission_matrix(
    role, create, edit_own, edit_other, manage_own_class, moderate, ban
):
    assert can_create_content(role) is create
    assert can_edit_content(role, True) is edit_own
    assert can_edit_content(role, False) is edit_other
    assert can_manage_class(role, True) is manage_own_class
    assert can_manage_class(role, False) is False
    assert can_moderate_content(role) is moderate
    assert can_ban_accounts(role) is ban
