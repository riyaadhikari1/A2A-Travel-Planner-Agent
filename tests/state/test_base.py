# tests/state/test_base.py

import pytest
from state.base import Store
from state.memory_store import MemoryStore


class TestStoreProtocol:

    def test_memory_store_satisfies_protocol(self):
        assert isinstance(MemoryStore(), Store)

    def test_store_is_runtime_checkable(self):
        """Store protocol must be checkable with isinstance at runtime."""
        store = MemoryStore()
        assert isinstance(store, Store)

    def test_object_without_methods_does_not_satisfy_protocol(self):
        class Empty:
            pass
        assert not isinstance(Empty(), Store)

    def test_partial_implementation_does_not_satisfy_protocol(self):
        class Partial:
            async def create(self, task_id, user_input):
                pass
        assert not isinstance(Partial(), Store)