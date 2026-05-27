# sdk_audit.py
# Run: uv run python sdk_audit.py > sdk_audit.txt
# Read sdk_audit.txt before touching any file.

import json
import uuid
import inspect
from pathlib import Path

import a2a
from google.protobuf import json_format

SEPARATOR = "\n" + "="*60 + "\n"


def section(title):
    print(SEPARATOR)
    print(f"  {title}")
    print(SEPARATOR)


# ── 1. SDK version and location ───────────────────────────────
section("1. SDK PACKAGE INFO")
print("File:   ", a2a.__file__)
print("Version:", getattr(a2a, "__version__", "not set"))

# ── 2. All public exports from a2a.types ──────────────────────
section("2. a2a.types EXPORTS")
import a2a.types as types_mod
exports = [x for x in dir(types_mod) if not x.startswith("_")]
for name in sorted(exports):
    obj = getattr(types_mod, name)
    kind = type(obj).__name__
    print(f"  {name:<40} {kind}")

# ── 3. a2a.client exports ─────────────────────────────────────
section("3. a2a.client EXPORTS")
import a2a.client as client_mod
for name in sorted(dir(client_mod)):
    if not name.startswith("_"):
        print(f"  {name}")

# ── 4. SendMessageRequest wire format ─────────────────────────
section("4. SendMessageRequest — CONFIRMED WIRE FORMAT")
from a2a.types import SendMessageRequest, Message, Part, Role

part = Part()
part.text = "Get weather in Bangkok"

msg = Message()
msg.role = Role.Value("ROLE_USER")
msg.message_id = str(uuid.uuid4())
msg.parts.append(part)

req = SendMessageRequest()
req.message.CopyFrom(msg)
print(json_format.MessageToJson(req, indent=2))

# ── 5. StreamResponse structure ───────────────────────────────
section("5. StreamResponse FIELDS")
from a2a.types import StreamResponse
print("Fields:", list(StreamResponse.DESCRIPTOR.fields_by_name.keys()))
for field_name in StreamResponse.DESCRIPTOR.fields_by_name:
    field = StreamResponse.DESCRIPTOR.fields_by_name[field_name]
    print(f"  {field_name}: {field.type}")

# ── 6. TaskStatusUpdateEvent fields ──────────────────────────
section("6. TaskStatusUpdateEvent FIELDS")
from a2a.types import TaskStatusUpdateEvent
print(list(TaskStatusUpdateEvent.DESCRIPTOR.fields_by_name.keys()))

# ── 7. TaskArtifactUpdateEvent fields ────────────────────────
section("7. TaskArtifactUpdateEvent FIELDS")
from a2a.types import TaskArtifactUpdateEvent
print(list(TaskArtifactUpdateEvent.DESCRIPTOR.fields_by_name.keys()))

# ── 8. TaskState enum values ──────────────────────────────────
section("8. TaskState ENUM VALUES")
from a2a.types import TaskState
for k, v in TaskState.items():
    print(f"  {k} = {v}")

# ── 9. AgentCard confirmed fields ────────────────────────────
section("9. AgentCard FIELDS")
from a2a.types import AgentCard
print(list(AgentCard.DESCRIPTOR.fields_by_name.keys()))

# ── 10. AgentSkill confirmed fields ──────────────────────────
section("10. AgentSkill FIELDS")
from a2a.types import AgentSkill
print(list(AgentSkill.DESCRIPTOR.fields_by_name.keys()))

# ── 11. create_rest_routes — actual route paths ──────────────
section("11. A2A SERVER ROUTES")
from a2a.server.routes import create_rest_routes
routes = create_rest_routes(request_handler=None)
for r in routes:
    path = getattr(r, "path", "?")
    methods = getattr(r, "methods", {"?"})
    print(f"  {str(methods):<20} {path}")

# ── 12. DefaultRequestHandler signature ──────────────────────
section("12. DefaultRequestHandler.__init__ SIGNATURE")
from a2a.server.request_handlers import DefaultRequestHandler
sig = inspect.signature(DefaultRequestHandler.__init__)
print(sig)

# ── 13. TaskUpdater methods ───────────────────────────────────
section("13. TaskUpdater PUBLIC METHODS")
from a2a.server.tasks.task_updater import TaskUpdater
for name, method in inspect.getmembers(TaskUpdater, predicate=inspect.isfunction):
    if not name.startswith("_"):
        print(f"  {name}{inspect.signature(method)}")

# ── 14. create_client signature ───────────────────────────────
section("14. create_client SIGNATURE")
from a2a.client import create_client
print(inspect.signature(create_client))
print()
print(inspect.getsource(create_client))

# ── 15. ClientFactory ─────────────────────────────────────────
section("15. ClientFactory")
from a2a.client import ClientFactory
for name, method in inspect.getmembers(ClientFactory, predicate=inspect.isfunction):
    if not name.startswith("_"):
        try:
            print(f"  {name}{inspect.signature(method)}")
        except Exception:
            print(f"  {name} (signature unavailable)")

# ── 16. VERSION header constant ───────────────────────────────
section("16. VERSION HEADER CONSTANT")
from a2a.utils import constants
for name in sorted(dir(constants)):
    if not name.startswith("_"):
        val = getattr(constants, name)
        if isinstance(val, (str, int, float)):
            print(f"  {name} = {val!r}")

# ── 17. All a2a source files ──────────────────────────────────
section("17. A2A PACKAGE FILE TREE")
a2a_path = Path(a2a.__file__).parent
for f in sorted(a2a_path.rglob("*.py")):
    rel = f.relative_to(a2a_path.parent)
    size = f.stat().st_size
    print(f"  {size:>8} bytes  {rel}")

# ── 18. RequestContext confirmed attrs ────────────────────────
section("18. RequestContext ATTRIBUTES AND METHODS")
from a2a.server.agent_execution import RequestContext
for name in sorted(dir(RequestContext)):
    if not name.startswith("_"):
        val = getattr(RequestContext, name, None)
        kind = "method" if callable(val) else "attr"
        print(f"  [{kind}] {name}")

# ── 19. EventQueue confirmed methods ─────────────────────────
section("19. EventQueue METHODS")
from a2a.server.events.event_queue import EventQueue
for name, method in inspect.getmembers(EventQueue, predicate=inspect.isfunction):
    if not name.startswith("_"):
        try:
            print(f"  {name}{inspect.signature(method)}")
        except Exception:
            print(f"  {name}")

# ── 20. InMemoryTaskStore ─────────────────────────────────────
section("20. InMemoryTaskStore PUBLIC METHODS")
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
for name, method in inspect.getmembers(InMemoryTaskStore, predicate=inspect.isfunction):
    if not name.startswith("_"):
        try:
            print(f"  {name}{inspect.signature(method)}")
        except Exception:
            print(f"  {name}")

print(SEPARATOR)
print("  AUDIT COMPLETE")
print(SEPARATOR)