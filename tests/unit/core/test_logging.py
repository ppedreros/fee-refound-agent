import json
import logging
import uuid
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api.middleware import RequestIdMiddleware
from backend.core.logging import DenyList, configure_logging

SALT = SecretStr("test-salt")


def log_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def app_that_logs() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/work")
    def work() -> dict[str, str]:
        structlog.get_logger().info("work_done", case_id=5012)
        return {"done": "yes"}

    return app


# Deny-list


def test_deny_list_drops_text_and_personal_fields() -> None:
    event = {
        "event": "conversation_loaded",
        "case_id": 5012,
        "message": "Please refund my $35 fee",
        "body": "raw body",
        "text": "raw text",
        "name": "Ana Torres",
        "first_name": "Ana",
        "last_name": "Torres",
        "account_number": "88104210",
        "email": "ana@example.com",
    }

    cleaned = DenyList(SALT)(None, "info", event)

    assert cleaned == {"event": "conversation_loaded", "case_id": 5012}


def test_deny_list_replaces_member_id_with_a_hash() -> None:
    cleaned = DenyList(SALT)(None, "info", {"event": "run_started", "member_id": 301})

    assert cleaned["member_id"] != 301
    assert "301" not in str(cleaned["member_id"])


def test_member_id_hash_is_stable_for_one_salt_and_differs_across_salts() -> None:
    first = DenyList(SALT)(None, "info", {"event": "e", "member_id": 301})
    again = DenyList(SALT)(None, "info", {"event": "e", "member_id": 301})
    other_salt = DenyList(SecretStr("other-salt"))(None, "info", {"event": "e", "member_id": 301})
    other_member = DenyList(SALT)(None, "info", {"event": "e", "member_id": 302})

    assert first["member_id"] == again["member_id"]
    assert first["member_id"] != other_salt["member_id"]
    assert first["member_id"] != other_member["member_id"]


def test_deny_list_also_cleans_nested_fields() -> None:
    event = {"event": "e", "details": {"email": "ana@example.com", "member_id": 301, "step": 2}}

    cleaned = DenyList(SALT)(None, "info", event)

    assert "email" not in cleaned["details"]
    assert cleaned["details"]["step"] == 2
    assert "301" not in str(cleaned["details"]["member_id"])


# JSON lines


def test_every_line_is_json_with_ts_level_event_and_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", SALT)

    structlog.get_logger().info("case_loaded", case_id=5012)
    logging.getLogger("uvicorn.error").warning("a line from a library")

    lines = log_lines(capsys.readouterr().out)
    assert len(lines) == 2
    for line in lines:
        assert {"ts", "level", "event", "request_id"} <= line.keys()
    assert lines[0]["event"] == "case_loaded"
    assert lines[1]["event"] == "a line from a library"


def test_the_deny_list_runs_on_every_logged_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", SALT)

    structlog.get_logger().info("member_checked", member_id=301, email="ana@example.com")

    (line,) = log_lines(capsys.readouterr().out)
    assert "email" not in line
    assert "301" not in json.dumps(line)


def test_an_exception_stays_on_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", SALT)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger().exception("step_failed")

    (line,) = log_lines(capsys.readouterr().out)
    assert line["event"] == "step_failed"
    assert "RuntimeError" in line["exception"]


def test_lines_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", SALT)

    structlog.get_logger().info("too_chatty")

    assert log_lines(capsys.readouterr().out) == []


# Request ids


def test_a_valid_request_id_is_echoed_and_bound_to_every_line_of_the_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", SALT)
    request_id = str(uuid.uuid4())

    with TestClient(app_that_logs()) as client:
        response = client.get("/work", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id
    lines = log_lines(capsys.readouterr().out)
    request_lines = [line for line in lines if line["event"] in {"work_done", "request"}]
    assert [line["event"] for line in request_lines] == ["work_done", "request"]
    assert all(line["request_id"] == request_id for line in request_lines)


def test_the_request_line_records_method_path_status_and_duration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", SALT)

    with TestClient(app_that_logs()) as client:
        client.get("/work")

    (line,) = [line for line in log_lines(capsys.readouterr().out) if line["event"] == "request"]
    assert line["method"] == "GET"
    assert line["path"] == "/work"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], int)


@pytest.mark.parametrize("header", [None, "not-a-uuid", "1; DROP TABLE cases"])
def test_a_missing_or_invalid_request_id_is_replaced_with_a_new_uuid(
    capsys: pytest.CaptureFixture[str], header: str | None
) -> None:
    configure_logging("INFO", SALT)
    headers = {} if header is None else {"X-Request-ID": header}

    with TestClient(app_that_logs()) as client:
        response = client.get("/work", headers=headers)

    returned = response.headers["X-Request-ID"]
    assert str(uuid.UUID(returned)) == returned
    (line,) = [line for line in log_lines(capsys.readouterr().out) if line["event"] == "request"]
    assert line["request_id"] == returned


def test_lines_outside_a_request_carry_no_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", SALT)

    with TestClient(app_that_logs()) as client:
        client.get("/work", headers={"X-Request-ID": str(uuid.uuid4())})
    structlog.get_logger().info("after_the_request")

    lines = log_lines(capsys.readouterr().out)
    assert lines[-1]["event"] == "after_the_request"
    assert lines[-1]["request_id"] is None
