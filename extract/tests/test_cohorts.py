from extract.cohorts import assign_overlap_group, is_known, all_groups


def test_exact_cohort_name():
    assert assign_overlap_group("ABCD") == "ABCD"
    assert assign_overlap_group("UK Biobank") == "UK Biobank"


def test_alias_match():
    assert assign_overlap_group("Adolescent Brain Cognitive Development Study") == "ABCD"
    assert assign_overlap_group("Avon Longitudinal Study of Parents and Children") == "ALSPAC"


def test_match_in_text_when_name_absent():
    got = assign_overlap_group(None, text="Participants were drawn from the ALSPAC cohort.")
    assert got == "ALSPAC"


def test_unknown_returns_none():
    assert assign_overlap_group("Springfield Youth Study") is None
    assert assign_overlap_group(None, text="a local convenience sample") is None


def test_registry_helpers():
    assert is_known("ABCD")
    assert not is_known("Nope")
    assert "Dunedin" in all_groups()


def test_khandle_and_star_registered():
    assert assign_overlap_group("KHANDLE") == "KHANDLE"
    assert assign_overlap_group(
        "Kaiser Healthy Aging and Diverse Life Experiences Study") == "KHANDLE"
    assert assign_overlap_group(
        None, text="the Study of Healthy Aging in African Americans (STAR)") == "STAR"
