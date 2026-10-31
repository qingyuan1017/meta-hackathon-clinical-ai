from app.sdtm_review_migration import attach_legacy_batch_review_notes


def test_attaches_flattened_comments_using_preserved_batch_counts() -> None:
    result = {
        "domain_mapping": {
            "domain_mappings": [
                {"source_dataset": "RAW_DM", "target_domain": "DM"},
                {"source_dataset": "RAW_AE", "target_domain": "AE"},
                {"source_dataset": "RAW_LB", "target_domain": "LB"},
            ]
        },
        "variable_mapping": {
            "datasets": [{"domain": "DM"}, {"domain": "AE"}, {"domain": "LB"}],
            # The AE batch emitted two assumptions, but one duplicated an earlier string
            # and was removed by the historical plan-level de-duplication.
            "assumptions": ["General baseline", "DM mapping", "AE mapping", "target LB mapping"],
            "unresolved_mappings": ["DM decision", "AE decision", "LB decision"],
        },
    }
    migrated = attach_legacy_batch_review_notes(
        result,
        assumption_counts=[2, 2, 1],
        unresolved_counts=[1, 1, 1],
    )
    datasets = migrated["variable_mapping"]["datasets"]
    assert datasets[0]["review_assumptions"] == ["General baseline", "DM mapping"]
    assert datasets[1]["review_assumptions"] == ["AE mapping"]
    assert datasets[2]["review_assumptions"] == ["target LB mapping"]
    assert datasets[1]["review_unresolved_mappings"] == ["AE decision"]


def test_short_domain_does_not_match_inside_an_ordinary_word() -> None:
    result = {
        "domain_mapping": {
            "domain_mappings": [
                {"source_dataset": "CM", "target_domain": "CM"},
                {"source_dataset": "CO", "target_domain": "CO"},
                {"source_dataset": "DA", "target_domain": "DA"},
            ]
        },
        "variable_mapping": {
            "datasets": [{"domain": "CM"}, {"domain": "CO"}, {"domain": "DA"}],
            # One duplicate was removed from the CO batch. "coded" must not be
            # mistaken for the start of the CO batch while finding that boundary.
            "assumptions": [
                "CM baseline",
                "Coded values require review",
                "CM date handling",
                "Approved mapping to CO",
                "CO variable review",
                "Approved mapping to DA",
            ],
            "unresolved_mappings": [],
        },
    }

    migrated = attach_legacy_batch_review_notes(
        result,
        assumption_counts=[3, 3, 1],
        unresolved_counts=[0, 0, 0],
    )

    datasets = migrated["variable_mapping"]["datasets"]
    assert datasets[0]["review_assumptions"] == [
        "CM baseline",
        "Coded values require review",
        "CM date handling",
    ]
    assert datasets[1]["review_assumptions"] == [
        "Approved mapping to CO",
        "CO variable review",
    ]
    assert datasets[2]["review_assumptions"] == ["Approved mapping to DA"]
