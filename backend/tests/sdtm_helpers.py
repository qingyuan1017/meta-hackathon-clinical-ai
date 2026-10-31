from app.schemas import SDTMRecordPlan, SDTMRecordStep, SDTMSourceReference


def source(dataset: str, variable: str, role: str = "value") -> SDTMSourceReference:
    return SDTMSourceReference(dataset=dataset, variable=variable, role=role)


def read_plan(domain: str, source_dataset: str) -> SDTMRecordPlan:
    step_id = f"read-{source_dataset.lower()}"
    return SDTMRecordPlan(
        steps=[
            SDTMRecordStep(
                step_id=step_id,
                operation="read",
                description=f"Read {source_dataset} for {domain}.",
                output=f"{domain.lower()}_source",
                source_dataset=source_dataset,
            )
        ],
        output_step=step_id,
    )
