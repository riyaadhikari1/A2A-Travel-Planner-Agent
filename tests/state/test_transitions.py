# tests/state/test_transitions.py

import pytest
from shared.schemas.task import TaskStatus
from state.transitions import VALID_TRANSITIONS


class TestValidTransitions:

    def test_queued_can_transition_to_running(self):
        assert TaskStatus.RUNNING in VALID_TRANSITIONS[TaskStatus.QUEUED]

    def test_running_can_transition_to_completed(self):
        assert TaskStatus.COMPLETED in VALID_TRANSITIONS[TaskStatus.RUNNING]

    def test_running_can_transition_to_failed(self):
        assert TaskStatus.FAILED in VALID_TRANSITIONS[TaskStatus.RUNNING]

    def test_queued_cannot_transition_to_completed(self):
        assert TaskStatus.COMPLETED not in VALID_TRANSITIONS[TaskStatus.QUEUED]

    def test_queued_cannot_transition_to_failed(self):
        assert TaskStatus.FAILED not in VALID_TRANSITIONS[TaskStatus.QUEUED]

    def test_completed_has_no_valid_transitions(self):
        assert VALID_TRANSITIONS.get(TaskStatus.COMPLETED, set()) == set()

    def test_failed_has_no_valid_transitions(self):
        assert VALID_TRANSITIONS.get(TaskStatus.FAILED, set()) == set()

    def test_all_terminal_states_have_no_transitions(self):
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED}
        for status in terminal:
            assert VALID_TRANSITIONS.get(status, set()) == set()

    def test_transitions_cover_all_active_statuses(self):
        active = {TaskStatus.QUEUED, TaskStatus.RUNNING}
        assert set(VALID_TRANSITIONS.keys()) == active