from __future__ import annotations

from app.core_conformance import CORE_USDM4_RULE_COUNT, evaluate_core_report


def _report(statuses: dict[int, str] | None = None, *, technical_skip: int | None = None) -> dict:
    statuses = statuses or {}
    rules = []
    raw = []
    for index in range(CORE_USDM4_RULE_COUNT):
        core_id = f"CORE-{index:06d}"
        status = statuses.get(index, "SUCCESS")
        rules.append({"core_id": core_id, "status": status, "message": f"Rule {index}"})
        raw_item = {
            "id": core_id,
            "execution_status": status.lower(),
            "message": f"Rule {index}",
            "results": [],
        }
        if status == "SKIPPED":
            reason = "Column not found in data" if index == technical_skip else "Outside scope"
            raw_item["results"] = [
                {
                    "executionStatus": "skipped",
                    "message": reason,
                    "errors": [{"error": reason, "message": reason}],
                }
            ]
        raw.append(raw_item)
    return {
        "Conformance_Details": {
            "CORE_Engine_Version": "0.17.1",
            "Standard": "USDM",
            "Version": "V4.0",
        },
        "Rules_Report": rules,
        "results_data": raw,
    }


def test_complete_report_allows_explicitly_out_of_scope_rules() -> None:
    decision = evaluate_core_report(_report({3: "SKIPPED"}))

    assert decision["conformant"] is True
    assert decision["ruleset"]["reported_rule_count"] == CORE_USDM4_RULE_COUNT
    assert decision["allowed_non_applicable_skips"] == ["CORE-000003"]
    assert decision["blocking_rules"] == []


def test_findings_and_technical_skips_fail_conformance() -> None:
    decision = evaluate_core_report(
        _report({4: "ISSUE REPORTED", 5: "EXECUTION ERROR", 6: "SKIPPED"}, technical_skip=6)
    )

    assert decision["conformant"] is False
    blocked = {item["core_id"]: item["status"] for item in decision["blocking_rules"]}
    assert blocked["CORE-000004"] == "ISSUE REPORTED"
    assert blocked["CORE-000005"] == "EXECUTION ERROR"
    assert blocked["CORE-000006"] == "SKIPPED"


def test_incomplete_or_mismatched_report_fails_closed() -> None:
    report = _report()
    report["Rules_Report"].pop()
    report["Conformance_Details"]["CORE_Engine_Version"] = "unexpected"

    decision = evaluate_core_report(report)

    assert decision["conformant"] is False
    statuses = {item["status"] for item in decision["blocking_rules"]}
    assert "INCOMPLETE RULESET" in statuses
    assert "INCONSISTENT RULESET" in statuses
    assert "METADATA MISMATCH" in statuses
