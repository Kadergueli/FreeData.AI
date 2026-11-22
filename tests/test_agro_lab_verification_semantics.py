from src.agro_engine import validate_field_assessment_qa


def _assessment(has_lab_measurements: bool) -> dict:
    return {
        "province_hub": "Moundou",
        "report_verification_code": "FD-TEST-001",
        "computed_scores": {
            "has_lab_measurements": has_lab_measurements,
            "crop_assessments": [{"crop": "millet"}],
            "provenance": {"sources": ["NASA POWER"], "licenses": ["CC BY 4.0"]},
            "limitations": ["Point GPS, not parcel-wide measurement."],
        },
    }


def test_declared_soil_inputs_are_not_treated_as_verified_lab_evidence():
    qa = validate_field_assessment_qa(_assessment(True))

    assert qa["qa_mode"] == "DECLARED_LAB_INPUTS_UNVERIFIED"
    assert qa["qa_badge"] == "MESURES DÉCLARÉES — NON VÉRIFIÉES"
    assert qa["dimensions"]["data_quality"] == "declared_unverified"


def test_satellite_only_assessment_remains_explicitly_estimated():
    qa = validate_field_assessment_qa(_assessment(False))

    assert qa["qa_mode"] == "SATELLITE_ESTIMATION"
    assert qa["qa_badge"] == "ESTIMATION SATELLITAIRE GPS"
    assert qa["dimensions"]["data_quality"] == "estimated_satellite"
