"""Fixtures every test of the review bench uses."""

import os
from collections.abc import Iterator
from unittest import mock

import pytest

from tests.conftest import HERMETIC_GIT


@pytest.fixture(autouse=True)
def hermetic_git() -> Iterator[None]:
    """Commit as canopy's test author and read no git config of the machine's: the bench writes commits of its own."""
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        yield
