from extract.prompts import EXTRACT, load_prompt


def test_extract_prompt_is_v2():
    assert EXTRACT == "extract_v2"


def test_v2_requires_demographic_provenance():
    t = load_prompt(EXTRACT).template.lower()
    assert "mean_age and age_range are required" in t
    assert "sample-level" in t
    # the provenance example now shows the demographic fields
    assert '"mean_age":' in load_prompt(EXTRACT).template
    assert '"age_range":' in load_prompt(EXTRACT).template


def test_v2_keeps_no_inference_rule():
    t = " ".join(load_prompt(EXTRACT).template.lower().split())
    assert "do not compute, infer, or estimate" in t


def test_verify_prompt_is_v2_and_number_tolerant():
    from extract.prompts import VERIFY
    assert VERIFY == "verify_v2"
    t = " ".join(load_prompt(VERIFY).template.lower().split())
    assert "match on the number itself" in t
    assert "dash style" in t
