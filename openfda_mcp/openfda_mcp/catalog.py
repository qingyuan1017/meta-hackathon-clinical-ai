"""Supported openFDA datasets and model-facing discovery metadata."""

from __future__ import annotations

from typing import TypedDict


class EndpointInfo(TypedDict):
    title: str
    category: str
    description: str
    documentation_url: str
    useful_fields: list[str]
    example_searches: list[str]


def _endpoint(
    title: str,
    category: str,
    description: str,
    useful_fields: list[str],
    example_searches: list[str],
    *,
    documentation_slug: str,
) -> EndpointInfo:
    return {
        "title": title,
        "category": category,
        "description": description,
        "documentation_url": f"https://open.fda.gov/apis/{documentation_slug}/",
        "useful_fields": useful_fields,
        "example_searches": example_searches,
    }


ENDPOINTS: dict[str, EndpointInfo] = {
    "animalandveterinary/event": _endpoint(
        "Animal adverse events",
        "animalandveterinary",
        "Adverse events associated with veterinary medicines.",
        ["unique_aer_id_number", "original_receive_date", "primary_reporter", "animal.species"],
        ["primary_reporter:Veterinarian", 'animal.species:"Dog"'],
        documentation_slug="animalandveterinary/event",
    ),
    "drug/event": _endpoint(
        "Drug adverse events",
        "drug",
        "FAERS adverse event reports for drugs and therapeutic biologics.",
        [
            "safetyreportid",
            "receivedate",
            "serious",
            "patient.reaction.reactionmeddrapt",
            "patient.drug.medicinalproduct",
            "patient.drug.openfda.generic_name",
        ],
        [
            'patient.drug.openfda.generic_name.exact:"IBUPROFEN"',
            'patient.reaction.reactionmeddrapt.exact:"HEADACHE"',
        ],
        documentation_slug="drug/event",
    ),
    "drug/label": _endpoint(
        "Drug labeling",
        "drug",
        "Structured product labeling submitted to FDA.",
        [
            "id",
            "effective_time",
            "openfda.brand_name",
            "openfda.generic_name",
            "indications_and_usage",
            "warnings",
            "drug_interactions",
        ],
        ['openfda.brand_name.exact:"LIPITOR"', 'openfda.generic_name.exact:"METFORMIN"'],
        documentation_slug="drug/label",
    ),
    "drug/ndc": _endpoint(
        "National Drug Code directory",
        "drug",
        "Currently marketed drug products in the FDA NDC Directory.",
        ["product_ndc", "brand_name", "generic_name", "labeler_name", "active_ingredients"],
        ['brand_name.exact:"LIPITOR"', 'generic_name:"metformin"'],
        documentation_slug="drug/ndc",
    ),
    "drug/drugsfda": _endpoint(
        "Drugs@FDA",
        "drug",
        "FDA-approved drug products, applications, and regulatory actions.",
        ["application_number", "sponsor_name", "products", "submissions", "openfda"],
        ['openfda.brand_name.exact:"LIPITOR"', 'application_number:"NDA020702"'],
        documentation_slug="drug/drugsfda",
    ),
    "drug/enforcement": _endpoint(
        "Drug enforcement reports",
        "drug",
        "Drug recall enforcement reports monitored by FDA.",
        ["recall_number", "status", "classification", "report_date", "product_description"],
        ['status:"Ongoing"', 'classification:"Class I"'],
        documentation_slug="drug/enforcement",
    ),
    "device/event": _endpoint(
        "Device adverse events",
        "device",
        "Medical device reports describing deaths, serious injuries, and malfunctions.",
        ["mdr_report_key", "date_received", "event_type", "device", "patient"],
        ['device.device_report_product_code:"DQY"', 'event_type:"Death"'],
        documentation_slug="device/event",
    ),
    "device/510k": _endpoint(
        "Device 510(k) clearances",
        "device",
        "Premarket notification decisions and associated products and sponsors.",
        ["k_number", "decision_date", "decision_description", "device_name", "applicant"],
        ['k_number:"K123456"', 'device_name:"catheter"'],
        documentation_slug="device/510k",
    ),
    "device/classification": _endpoint(
        "Device classification",
        "device",
        "Device product codes, regulatory classes, panels, and regulation numbers.",
        ["product_code", "device_name", "device_class", "regulation_number", "medical_specialty"],
        ['product_code:"DQY"', 'device_class:"3"'],
        documentation_slug="device/classification",
    ),
    "device/enforcement": _endpoint(
        "Device enforcement reports",
        "device",
        "Medical device recall enforcement reports monitored by FDA.",
        ["recall_number", "status", "classification", "report_date", "product_description"],
        ['status:"Ongoing"', 'classification:"Class I"'],
        documentation_slug="device/enforcement",
    ),
    "device/pma": _endpoint(
        "Device premarket approvals",
        "device",
        "Premarket approval decisions for class III medical devices.",
        ["pma_number", "decision_date", "decision_code", "trade_name", "applicant"],
        ['pma_number:"P170019"', 'trade_name:"pacemaker"'],
        documentation_slug="device/pma",
    ),
    "device/recall": _endpoint(
        "Device recalls",
        "device",
        "CDRH medical device recall records.",
        ["res_event_number", "product_code", "product_res_number", "root_cause_description"],
        ['product_code:"DQY"', 'recall_status:"Open"'],
        documentation_slug="device/recall",
    ),
    "device/registrationlisting": _endpoint(
        "Device registrations and listings",
        "device",
        "Registered device establishments and devices listed at those establishments.",
        ["registration", "proprietary_name", "products", "establishment_type"],
        ['registration.registration_number:"1234567"', 'products.product_code:"DQY"'],
        documentation_slug="device/registrationlisting",
    ),
    "device/udi": _endpoint(
        "Unique device identifiers",
        "device",
        "Global Unique Device Identification Database device identifiers.",
        ["identifiers", "brand_name", "company_name", "version_or_model_number", "product_codes"],
        ['brand_name:"pacemaker"', 'company_name:"Medtronic"'],
        documentation_slug="device/udi",
    ),
    "device/covid19serology": _endpoint(
        "COVID-19 serology evaluations",
        "device",
        "FDA performance evaluations of COVID-19 serological tests.",
        ["manufacturer", "device", "lot_number", "control", "evaluation_id"],
        ['manufacturer:"Abbott"'],
        documentation_slug="device/covid19serology",
    ),
    "food/event": _endpoint(
        "Food adverse events",
        "food",
        "CAERS adverse event reports for foods, dietary supplements, and cosmetics.",
        ["report_number", "date_created", "products", "reactions", "outcomes"],
        ['products.name_brand:"protein"', 'reactions.exact:"NAUSEA"'],
        documentation_slug="food/event",
    ),
    "food/enforcement": _endpoint(
        "Food enforcement reports",
        "food",
        "Food recall enforcement reports monitored by FDA.",
        ["recall_number", "status", "classification", "report_date", "product_description"],
        ['status:"Ongoing"', 'classification:"Class I"'],
        documentation_slug="food/enforcement",
    ),
    "cosmetic/event": _endpoint(
        "Cosmetic adverse events",
        "cosmetic",
        "Adverse event reports involving cosmetic products.",
        ["report_number", "initial_received_date", "products", "reactions", "outcomes"],
        ['products.name_brand:"shampoo"'],
        documentation_slug="cosmetic/event",
    ),
    "tobacco/problem": _endpoint(
        "Tobacco problem reports",
        "tobacco",
        "Consumer, manufacturer, and health professional tobacco product problem reports.",
        [
            "report_id",
            "date_submitted",
            "tobacco_products",
            "reported_health_problems",
            "reported_product_problems",
        ],
        ['tobacco_products.product_type:"Electronic Cigarettes"'],
        documentation_slug="tobacco/problem",
    ),
}


def endpoint_ids(category: str | None = None) -> list[str]:
    """Return sorted endpoint IDs, optionally restricted to one category."""
    if category is None:
        return sorted(ENDPOINTS)
    normalized = category.strip().lower()
    return sorted(key for key, value in ENDPOINTS.items() if value["category"] == normalized)

