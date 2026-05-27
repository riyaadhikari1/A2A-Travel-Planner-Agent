"""
Test script for all agents in the A2A travel planning system.
Run with: uv run python test_all_agents.py
All agents must be running (uv run python main.py) before running this.
"""

import json
import time
import uuid
import threading
import httpx

GATEWAY_URL     = "http://localhost:8000"
WEATHER_URL     = "http://localhost:8001"
DOM_FLIGHT_URL  = "http://localhost:8002"
INTL_FLIGHT_URL = "http://localhost:8003"
HOTEL_URL       = "http://localhost:8004"
BUDGET_URL      = "http://localhost:8005"

A2A_HEADERS = {"A2A-Version": "1.0"}

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []


# ── Helpers ────────────────────────────────────────────────────────────────

def record(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    icon   = "OK" if passed else "FAIL"
    print(f"  [{icon}] {name}" + (f": {detail}" if detail else ""))
    results.append((name, status, detail))


def send_streaming_message(base_url: str, text: str, timeout: int = 30) -> dict:
    message_id = str(uuid.uuid4())
    body = {
        "jsonrpc": "2.0",
        "method":  "SendStreamingMessage",
        "id":      message_id,
        "params":  {
            "message": {
                "messageId": message_id,
                "role":      "ROLE_USER",
                "parts":     [{"text": text}],
            }
        },
    }

    artifact_payload = {}
    states           = []
    error            = None

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST", base_url, json=body, headers=A2A_HEADERS
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str:
                        continue
                    try:
                        envelope = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    result = envelope.get("result", {})

                    art_update = result.get("artifactUpdate")
                    if art_update:
                        artifact = art_update.get("artifact", {})
                        for part in artifact.get("parts", []):
                            data = part.get("data")
                            if data is not None:
                                artifact_payload = data if isinstance(data, dict) else {}
                                break

                    status_update = result.get("statusUpdate")
                    if status_update:
                        state = status_update.get("status", {}).get("state", "")
                        if state:
                            states.append(state)
                        if state in (
                            "TASK_STATE_COMPLETED",
                            "TASK_STATE_FAILED",
                            "TASK_STATE_CANCELED",
                        ):
                            break

                    if "error" in envelope:
                        error = envelope["error"].get("message", "unknown error")
                        break

    except Exception as e:
        error = str(e)

    return {"artifact": artifact_payload, "states": states, "error": error}


def send_gateway_chat(message: str, timeout: int = 120) -> dict:
    events       = []
    has_artifact = False
    has_error    = False
    error        = None

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{GATEWAY_URL}/chat",
                json={"message": message},
            ) as resp:
                resp.raise_for_status()
                current_event = None
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        current_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if data and current_event:
                            events.append(f"{current_event}:{data}")
                            if current_event == "artifact":
                                has_artifact = True
                            if current_event == "status" and data in ("completed", "failed"):
                                has_error    = data == "failed"
                                current_event = None
                                break
                            current_event = None
    except Exception as e:
        error = str(e)

    return {
        "events":       events,
        "has_artifact": has_artifact,
        "has_error":    has_error,
        "error":        error,
    }


# ── 1. Health checks ───────────────────────────────────────────────────────

def test_health() -> None:
    print("\n[1] Health Checks")
    agents = {
        "Gateway        (8000)": GATEWAY_URL,
        "Weather        (8001)": WEATHER_URL,
        "Domestic Flight(8002)": DOM_FLIGHT_URL,
        "Intl Flight    (8003)": INTL_FLIGHT_URL,
        "Hotel          (8004)": HOTEL_URL,
        "Budget         (8005)": BUDGET_URL,
    }
    for label, url in agents.items():
        try:
            resp = httpx.get(f"{url}/health", timeout=5)
            record(label, resp.status_code == 200, str(resp.status_code))
        except Exception as e:
            record(label, False, str(e))


# ── 2. Agent cards ─────────────────────────────────────────────────────────

def test_agent_cards() -> None:
    print("\n[2] Agent Cards (/.well-known/agent-card.json)")
    urls = {
        "Weather":         WEATHER_URL,
        "Domestic Flight": DOM_FLIGHT_URL,
        "Intl Flight":     INTL_FLIGHT_URL,
        "Hotel":           HOTEL_URL,
        "Budget":          BUDGET_URL,
    }
    for label, url in urls.items():
        try:
            resp = httpx.get(f"{url}/.well-known/agent-card.json", timeout=5)
            ok   = resp.status_code == 200
            if ok:
                card   = resp.json()
                name   = card.get("name", "?")
                skills = [s.get("id") for s in card.get("skills", [])]
                detail = f"name={name}, skills={skills}"
            else:
                detail = str(resp.status_code)
            record(f"Card: {label}", ok, detail)
        except Exception as e:
            record(f"Card: {label}", False, str(e))


# ── 3. Weather agent ───────────────────────────────────────────────────────

def test_weather_agent() -> None:
    print("\n[3] Weather Agent")
    res = send_streaming_message(WEATHER_URL, "Get weather in Kathmandu")
    completed = "TASK_STATE_COMPLETED" in res["states"]
    has_data  = bool(res["artifact"].get("location") or res["artifact"].get("current"))
    has_daily = "daily" in res["artifact"]
    record("Weather: task completed",     completed, str(res["states"]))
    record("Weather: artifact has data",  has_data,  str(list(res["artifact"].keys()))[:80])
    record("Weather: has daily forecast", has_daily, "")
    if res["error"]:
        record("Weather: no error", False, res["error"])


# ── 4. Domestic flight agent ───────────────────────────────────────────────

def test_domestic_flight_agent() -> None:
    print("\n[4] Domestic Flight Agent")
    res = send_streaming_message(
        DOM_FLIGHT_URL,
        "Find flights from KTM to PKR on 2026-07-15 for 1 adult economy",
    )
    completed  = "TASK_STATE_COMPLETED" in res["states"]
    has_data   = "origin" in res["artifact"] or "flights" in res["artifact"]
    has_offers = isinstance(res["artifact"].get("offers"), list)
    record("Dom Flight: task completed",    completed,  str(res["states"]))
    record("Dom Flight: artifact has data", has_data,   str(list(res["artifact"].keys()))[:80])
    record("Dom Flight: offers is a list",  has_offers, f"{len(res['artifact'].get('offers', []))} offers")
    if res["error"]:
        record("Dom Flight: no error", False, res["error"])


# ── 5. International flight agent ──────────────────────────────────────────

def test_intl_flight_agent() -> None:
    print("\n[5] International Flight Agent")
    res = send_streaming_message(
        INTL_FLIGHT_URL,
        "Find international flights from KTM to BKK from 2026-07-15 to 2026-07-20",
    )
    completed      = "TASK_STATE_COMPLETED" in res["states"]
    has_data       = bool(res["artifact"])
    has_fares      = bool(res["artifact"].get("fares"))
    correct_origin = res["artifact"].get("origin") == "KTM"
    record("Intl Flight: task completed",    completed,      str(res["states"]))
    record("Intl Flight: artifact has data", has_data,       str(list(res["artifact"].keys()))[:80])
    record("Intl Flight: has fares",         has_fares,      "")
    record("Intl Flight: origin is KTM",     correct_origin, res["artifact"].get("origin", "?"))
    if res["error"]:
        record("Intl Flight: no error", False, res["error"])


# ── 6. Hotel agent ─────────────────────────────────────────────────────────

def test_hotel_agent() -> None:
    print("\n[6] Hotel Agent")
    res = send_streaming_message(HOTEL_URL, "Find hotels in Bangkok")
    completed   = "TASK_STATE_COMPLETED" in res["states"]
    has_data    = bool(res["artifact"])
    has_hotels  = isinstance(res["artifact"].get("hotels"), list)
    hotel_count = len(res["artifact"].get("hotels", []))
    record("Hotel: task completed",    completed,        str(res["states"]))
    record("Hotel: artifact has data", has_data,         str(list(res["artifact"].keys()))[:80])
    record("Hotel: hotels is a list",  has_hotels,       f"{hotel_count} hotels")
    record("Hotel: at least 1 result", hotel_count > 0,  f"{hotel_count} found")
    if res["error"]:
        record("Hotel: no error", False, res["error"])


# ── 7. Budget agent ────────────────────────────────────────────────────────

def test_budget_agent() -> None:
    print("\n[7] Budget Agent")
    instruction = (
        "Estimate budget for trip with the following data: "
        '{"intl_flight": {"fares": {"status": true, "data": [{"carrier": "UL", "price": 27832}]}, "origin": "KTM", "destination": "BKK"}, '
        '"hotel": {"hotels": [{"name": "Test Hotel"}], "city": "Bangkok"}, '
        '"weather": {"location": "Bangkok", "current": {"temperature_2m": 30}}}'
    )
    res = send_streaming_message(BUDGET_URL, instruction, timeout=15)
    completed = "TASK_STATE_COMPLETED" in res["states"]
    has_total = "total" in res["artifact"]
    has_currency = res["artifact"].get("currency") == "USD"
    record("Budget: task completed",    completed,    str(res["states"]))
    record("Budget: has total",         has_total,    str(res["artifact"].get("total", "?")))
    record("Budget: currency is USD",   has_currency, res["artifact"].get("currency", "?"))
    if res["error"]:
        record("Budget: no error", False, res["error"])


# ── 8. Gateway registry ────────────────────────────────────────────────────

def test_gateway_registry() -> None:
    print("\n[8] Gateway Registry")
    try:
        resp = httpx.get(f"{GATEWAY_URL}/agents", timeout=10)
        ok   = resp.status_code == 200
        if ok:
            agents = resp.json()
            names  = [a.get("name") for a in agents] if isinstance(agents, list) else []
            record("Registry: responds 200",       ok,               "")
            record("Registry: returns agent list", isinstance(agents, list), str(names))
            record("Registry: has 5 agents",       len(agents) == 5, f"{len(agents)} agents")
        else:
            record("Registry: responds 200", False, str(resp.status_code))
    except Exception as e:
        record("Registry", False, str(e))


# ── 9. Gateway /chat ───────────────────────────────────────────────────────

def test_gateway_chat() -> None:
    print("\n[9] Gateway /chat endpoint")
    res = send_gateway_chat("Plan a trip from KTM to Bangkok on 2026-07-15")

    if res["error"]:
        record("Gateway /chat", False, res["error"])
        return

    record("Gateway /chat: responded",     len(res["events"]) > 0,  f"{len(res['events'])} events")
    record("Gateway /chat: got status",    any("status" in e for e in res["events"]), str(res["events"][:3]))
    record("Gateway /chat: got artifact",  res["has_artifact"],      "")
    record("Gateway /chat: no task error", not res["has_error"],     "")


# ── 10. Gateway /tasks/send + /tasks/{id} ─────────────────────────────────

def test_gateway_tasks_send() -> None:
    print("\n[10] Gateway /tasks/send + /tasks/{id}")
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/tasks/send",
            json={"input": "Get weather in Pokhara"},
            timeout=10,
        )
        ok = resp.status_code == 200
        if not ok:
            record("Tasks/send: responds 200", False, str(resp.status_code))
            return

        body    = resp.json()
        task_id = body.get("task_id")
        status  = body.get("status")
        record("Tasks/send: responds 200", True,          "")
        record("Tasks/send: has task_id",  bool(task_id), str(task_id)[:36])
        record("Tasks/send: has status",   bool(status),  str(status))

        if task_id:
            time.sleep(5)
            resp2 = httpx.get(f"{GATEWAY_URL}/tasks/{task_id}", timeout=10)
            ok2   = resp2.status_code == 200
            record("Tasks/get: responds 200", ok2, str(resp2.status_code))
            if ok2:
                task = resp2.json()
                record(
                    "Tasks/get: status is completed or running",
                    task.get("status") in ("completed", "running", "failed"),
                    str(task.get("status")),
                )
    except Exception as e:
        record("Tasks/send", False, str(e))


# ── 11. Gateway /tasks/{id}/stream ────────────────────────────────────────

def test_gateway_task_stream() -> None:
    print("\n[11] Gateway /tasks/{id}/stream")
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/tasks/send",
            json={"input": "Get weather in Kathmandu"},
            timeout=10,
        )
        if resp.status_code != 200:
            record("Task stream: setup", False, str(resp.status_code))
            return

        task_id = resp.json().get("task_id")
        if not task_id:
            record("Task stream: setup", False, "no task_id")
            return

        events = []
        with httpx.Client(timeout=60) as client:
            with client.stream(
                "GET", f"{GATEWAY_URL}/tasks/{task_id}/stream"
            ) as stream_resp:
                stream_resp.raise_for_status()
                current_event = None
                for line in stream_resp.iter_lines():
                    if line.startswith("event:"):
                        current_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if data and current_event:
                            events.append(f"{current_event}:{data}")
                            if current_event == "status" and data in ("completed", "failed"):
                                current_event = None
                                break
                            current_event = None

        record("Task stream: received events", len(events) > 0,                          f"{len(events)} events")
        record("Task stream: has status event", any("status" in e for e in events),      str(events[:3]))

    except Exception as e:
        record("Task stream", False, str(e))


# ── 12. Concurrent load test ───────────────────────────────────────────────

def test_concurrent() -> None:
    print("\n[12] Concurrent requests (3x weather in parallel)")
    time.sleep(1.0)
    errors:  list[str]   = []
    timings: list[float] = []
    lock = threading.Lock()

    def run_one() -> None:
        t0  = time.time()
        res = send_streaming_message(WEATHER_URL, "Get weather in Bangkok", timeout=45)
        dt  = time.time() - t0
        with lock:
            timings.append(dt)
            if res["error"] or "TASK_STATE_COMPLETED" not in res["states"]:
                errors.append(res.get("error") or str(res["states"]))

    threads = [threading.Thread(target=run_one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    avg = sum(timings) / len(timings) if timings else 0
    record(
        "Concurrent: all succeeded",
        len(errors) == 0,
        f"{len(timings)} requests, avg {avg:.2f}s" +
        (f", errors: {errors}" if errors else ""),
    )


# ── 13. Unknown task 404 ───────────────────────────────────────────────────

def test_unknown_task() -> None:
    print("\n[13] Unknown task returns 404")
    try:
        resp = httpx.get(
            f"{GATEWAY_URL}/tasks/00000000-0000-0000-0000-000000000000",
            timeout=5,
        )
        record("Unknown task: 404", resp.status_code == 404, str(resp.status_code))
    except Exception as e:
        record("Unknown task: 404", False, str(e))


# ── Summary ────────────────────────────────────────────────────────────────

def print_summary() -> None:
    print("\n" + "=" * 55)
    print("SUMMARY")
    print("=" * 55)
    passed = [r for r in results if r[1] == PASS]
    failed = [r for r in results if r[1] == FAIL]
    print(f"  Passed: {len(passed)}/{len(results)}")
    if failed:
        print("\n  Failed tests:")
        for name, _, detail in failed:
            print(f"    - {name}: {detail}")
    print("=" * 55)


if __name__ == "__main__":
    print("=" * 55)
    print("A2A Travel System — Full Test Suite")
    print("=" * 55)

    test_health()
    test_agent_cards()
    test_weather_agent()
    test_domestic_flight_agent()
    test_intl_flight_agent()
    test_hotel_agent()
    test_budget_agent()
    test_gateway_registry()
    test_gateway_chat()
    test_gateway_tasks_send()
    test_gateway_task_stream()
    test_concurrent()
    test_unknown_task()
    print_summary()