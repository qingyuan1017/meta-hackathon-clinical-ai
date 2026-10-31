from app.review_patches import diff_operations, propose_scope, scope_candidate, three_way_merge, validate_scope
from app.schemas.reviews import ReviewScope, ReviewVariableScope


def test_variable_scope_discards_unselected_domain_and_field_changes() -> None:
    baseline = {
        "source_spec": {},
        "domain_mapping": {},
        "variable_mapping": {
            "datasets": [
                {"domain": "DM", "description": "Demographics", "variables": [
                    {"name": "AGE", "label": "Age", "mapping_expression": "Direct", "origin": "CRF"},
                ]},
                {"domain": "AE", "description": "Adverse Events", "variables": [
                    {"name": "AETERM", "label": "Reported Term", "mapping_expression": "Direct", "origin": "CRF"},
                ]},
            ]
        },
    }
    candidate = {
        "source_spec": {},
        "domain_mapping": {},
        "variable_mapping": {
            "datasets": [
                {"domain": "DM", "description": "Changed out of scope", "variables": [
                    {"name": "AGE", "label": "Age in Years", "mapping_expression": "AGE", "origin": "Derived"},
                ]},
                {"domain": "AE", "description": "Changed out of scope", "variables": [
                    {"name": "AETERM", "label": "Changed", "mapping_expression": "strip(AETERM)", "origin": "CRF"},
                ]},
            ]
        },
    }
    scope = ReviewScope(variables=[ReviewVariableScope(domain="DM", variable="AGE", fields=["mapping_expression"])])
    proposed = scope_candidate("variable_mapping", baseline, candidate, scope)
    dm = proposed["variable_mapping"]["datasets"][0]
    ae = proposed["variable_mapping"]["datasets"][1]
    assert dm["description"] == "Demographics"
    assert dm["variables"][0]["label"] == "Age"
    assert dm["variables"][0]["mapping_expression"] == "AGE"
    assert ae == baseline["variable_mapping"]["datasets"][1]
    assert [item.path for item in diff_operations(baseline, proposed)] == [
        "/variable_mapping/datasets/domain=DM/variables/name=AGE/mapping_expression"
    ]


def test_three_way_merge_reports_same_path_conflict() -> None:
    base = {"mapping": {"expression": "Direct", "label": "Age"}}
    current = {"mapping": {"expression": "AGE * 1", "label": "Age in years"}}
    proposed = {"mapping": {"expression": "as.numeric(AGE)", "label": "Age"}}
    merged, conflicts = three_way_merge(base, current, proposed)
    assert merged["mapping"]["label"] == "Age in years"
    assert merged["mapping"]["expression"] == "AGE * 1"
    assert conflicts == ["/mapping/expression"]


def test_stable_entity_pointer_ignores_list_order() -> None:
    baseline = {
        "outputs": [
            {"output_id": "T-01", "title": "First", "population": "TODO"},
            {"output_id": "T-02", "title": "Second", "population": "ITT"},
        ]
    }
    candidate = {
        "outputs": [
            {"output_id": "T-02", "title": "Changed outside scope", "population": "ITT"},
            {"output_id": "T-01", "title": "Changed outside scope", "population": "Safety"},
        ]
    }
    scope = ReviewScope(paths=["/outputs/output_id=T-01/population"])
    validate_scope("tlf_inventory", scope, baseline)
    proposed = scope_candidate("tlf_inventory", baseline, candidate, scope)
    assert proposed["outputs"][0] == {"output_id": "T-01", "title": "First", "population": "Safety"}
    assert proposed["outputs"][1] == baseline["outputs"][1]


def test_scope_suggestion_recognizes_qualified_sdtm_variable() -> None:
    current = {
        "variable_mapping": {
            "datasets": [{"domain": "DM", "variables": [{"name": "AGE"}, {"name": "SEX"}]}]
        }
    }
    scope, matched, _ = propose_scope("variable_mapping", "Revise DM.AGE only.", current)
    assert scope.model_dump(mode="json")["variables"] == [{"domain": "DM", "variable": "AGE", "fields": []}]
    assert matched == ["DM.AGE", "DM"]
