from pathlib import Path

import pytest

from blockstead.process import InvalidTransition, ProcessManager, ProcessState


def test_invalid_transition_is_rejected() -> None:
    manager = ProcessManager(Path("unused"))
    with pytest.raises(InvalidTransition):
        manager.transition(ProcessState.RUNNING, "no readiness")
