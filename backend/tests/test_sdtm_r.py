import pytest

from app.agents.runtime import verify_result
from app.schemas import SDTMRuleAugmentationPlan
from app.sdtm_r import normalize_r_mapping_expression


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'dplyr::if_else(is.na(AESTDTC), NA_character_, AESTDTC) /* TODO: confirm partial dates */',
            'dplyr::if_else(is.na(AESTDTC), NA_character_, AESTDTC)',
        ),
        ('NA_character_ # TODO: source unavailable', 'NA_character_'),
        ('paste("# retained inside string", STUDYID)', 'paste("# retained inside string", STUDYID)'),
        ('dplyr::case_when(`_SRC_` == "DM" ~ AGE, TRUE ~ NA_real_)', 'dplyr::case_when(`_SRC_` == "DM" ~ AGE, TRUE ~ NA_real_)'),
        ('TODO_convert_to_ISO8601(PRSTDAT)', 'TODO_convert_to_ISO8601(PRSTDAT)'),
        ('ave(seq_along(USUBJID), USUBJID, FUN = seq_along)', 'ave(seq_along(USUBJID), USUBJID, FUN = seq_along)'),
        ('TODO: transpose source records after sponsor review', 'NA'),
    ],
)
def test_normalize_r_mapping_expression_accepts_pure_rhs(source: str, expected: str) -> None:
    assert normalize_r_mapping_expression(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        'system("whoami")',
        'read.csv("outside.csv")',
        'A <- 1',
        'A; B',
        'base::identity(A)',
        'dplyr:::if_else(TRUE, A, B)',
        'obj$run()',
        'dplyr::mutate(A = 1)',
        'ifelse(is.na(A), A, B',
        "AETERM is not null",
        "SubjectID is not missing",
        "A and B",
        "A ne B",
        "PRYN1 indicates no procedures occurred",
    ],
)
def test_normalize_r_mapping_expression_rejects_unsafe_or_non_rhs_code(source: str) -> None:
    with pytest.raises(ValueError):
        normalize_r_mapping_expression(source)


def test_rule_augmentation_validation_names_the_unsafe_rule() -> None:
    plan = SDTMRuleAugmentationPlan.model_validate(
        {
            "study_name": "SYN-101",
            "record_plans": [{
                "target_domain": "DM",
                "record_plan": {
                    "steps": [{
                        "step_id": "read_dm", "operation": "read", "description": "Read DM",
                        "output": "dm_source", "source_dataset": "RAW_DM",
                    }],
                    "output_step": "read_dm",
                },
            }],
            "rule_augmentations": [
                {
                    "rule_id": "DM-AGE",
                    "target_domain": "DM",
                    "target_variable": "AGE",
                    "description": "Unsafe draft",
                    "logic": "Unsafe draft",
                    "r_expression": 'system("whoami")',
                    "sas_expression": "AGE",
                }
            ],
        }
    )

    problems = verify_result("sdtm-rule-augmentation", plan)

    assert len(problems) == 1
    assert "DM-AGE" in problems[0]
    assert "unapproved call system()" in problems[0]
