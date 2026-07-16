"""Reusable custom assertions for test verification."""


def assert_status_code(status_code: int, expected: int) -> None:
    """Assert status code is as expected."""
    assert status_code == expected
