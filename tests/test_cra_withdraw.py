"""CR-A: iedzīvotājs atsauc iesniegumu (POST /submissions/{id}/withdraw).

Sagaidāmās vērtības no tracker/CR-A.md pieņemšanas kritērijiem.
Sākuma dati (storage.SEED): 000001 RECEIVED, 000002 IN_PROGRESS, 000003 ANSWERED,
000004 FORWARDED, 000005 WITHDRAWN.
"""

import logging

import pytest

from app import storage

RECEIVED = "IES-2026-000001"
IN_PROGRESS = "IES-2026-000002"
ANSWERED = "IES-2026-000003"
FORWARDED = "IES-2026-000004"
WITHDRAWN = "IES-2026-000005"
REASON = "Problēma jau ir atrisināta"


@pytest.fixture
def seeded(client):
    storage.reset()
    return client


def withdraw(client, submission_id, body):
    return client.post(f"/submissions/{submission_id}/withdraw", json=body)


def status_of(client, submission_id):
    return client.get(f"/submissions/{submission_id}").json()["status"]


def test_cra_ac1_received_withdrawn(seeded):
    response = withdraw(seeded, RECEIVED, {"reason": REASON})

    assert response.status_code == 200
    assert response.json()["status"] == "WITHDRAWN"
    assert status_of(seeded, RECEIVED) == "WITHDRAWN"


def test_cra_ac1_due_date_unchanged(seeded):
    # Precizējums: pēc atsaukšanas dueDate nemainās.
    before = seeded.get(f"/submissions/{RECEIVED}").json()["dueDate"]

    response = withdraw(seeded, RECEIVED, {"reason": REASON})

    assert response.json()["dueDate"] == before == "2026-11-02"


def test_cra_ac2_in_progress_withdrawn(seeded):
    response = withdraw(seeded, IN_PROGRESS, {"reason": "Vairs nav aktuāli"})

    assert response.status_code == 200
    assert response.json()["status"] == "WITHDRAWN"


def test_cra_ac3_answered_409(seeded):
    response = withdraw(seeded, ANSWERED, {"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    assert status_of(seeded, ANSWERED) == "ANSWERED"


def test_cra_ac4_already_withdrawn_409(seeded):
    response = withdraw(seeded, WITHDRAWN, {"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"


def test_cra_ac4_second_withdraw_409_single_audit(seeded):
    assert withdraw(seeded, RECEIVED, {"reason": REASON}).status_code == 200

    response = withdraw(seeded, RECEIVED, {"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    actions = [e["action"] for e in seeded.get(f"/submissions/{RECEIVED}/audit").json()]
    assert actions.count("WITHDRAW") == 1


def test_cra_assumption_forwarded_409(seeded):
    # Atvērtais jautājums. Pieņēmums: FORWARDED nevar atsaukt (līgums atļauj tikai
    # RECEIVED un IN_PROGRESS). Sk. PR piezīmi.
    response = withdraw(seeded, FORWARDED, {"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    assert status_of(seeded, FORWARDED) == "FORWARDED"


def test_cra_ac5_unknown_id_404(seeded):
    response = withdraw(seeded, "IES-2026-999999", {"reason": REASON})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing"),
        pytest.param({"reason": None}, id="null"),
        pytest.param({"reason": ""}, id="empty"),
        pytest.param({"reason": "x" * 9}, id="9-chars"),
        pytest.param({"reason": " " * 20}, id="only-spaces"),
        pytest.param({"reason": "x" * 501}, id="501-chars"),
    ],
)
def test_cra_ac6_invalid_reason_400(seeded, body):
    response = withdraw(seeded, RECEIVED, body)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [d["field"] for d in error["details"]] == ["reason"]
    assert status_of(seeded, RECEIVED) == "RECEIVED"


@pytest.mark.parametrize("length", [10, 500])
def test_cra_ac6_boundary_lengths_accepted(seeded, length):
    response = withdraw(seeded, RECEIVED, {"reason": "x" * length})

    assert response.status_code == 200


def test_cra_ac7_audit_withdraw_with_reason(seeded):
    withdraw(seeded, RECEIVED, {"reason": REASON})

    entries = seeded.get(f"/submissions/{RECEIVED}/audit").json()

    assert entries[-1]["action"] == "WITHDRAW"
    assert entries[-1]["detail"] == REASON


def test_cra_ac8_no_personal_data_in_logs_or_errors(seeded, caplog):
    record = storage.get(RECEIVED)
    secrets = [record["personalCode"], record["fullName"], record["email"]]
    secrets.append(record["body"])

    with caplog.at_level(logging.DEBUG):
        responses = [
            withdraw(seeded, RECEIVED, {"reason": REASON}),
            withdraw(seeded, RECEIVED, {"reason": REASON}),
            withdraw(seeded, RECEIVED, {"reason": "short"}),
            withdraw(seeded, "IES-2026-999999", {"reason": REASON}),
        ]

    assert [r.status_code for r in responses] == [200, 409, 400, 404]
    errors = "".join(r.text for r in responses[1:])
    for value in secrets:
        assert value not in caplog.text
        assert value not in errors
