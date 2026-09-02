from screen.prompts import load_prompt, load_all, PASSES


def test_all_passes_load():
    prompts = load_all()
    assert set(prompts) == set(PASSES)


def test_hash_is_stable_across_loads():
    assert load_prompt("A").prompt_hash == load_prompt("A").prompt_hash


def test_passes_have_distinct_hashes():
    assert load_prompt("A").prompt_hash != load_prompt("B").prompt_hash


def test_render_fills_fields():
    p = load_prompt("A")
    body = p.render("MY TITLE", "MY ABSTRACT")
    assert "MY TITLE" in body and "MY ABSTRACT" in body
    assert "{title}" not in body and "{abstract}" not in body


def test_render_tolerates_braces_in_abstract():
    p = load_prompt("B")
    # abstracts with literal braces must not break rendering
    body = p.render("t", "effect {beta} was 0.2 {ns}")
    assert "effect {beta} was 0.2 {ns}" in body


def test_prompt_instructs_no_inference():
    # the anti-inference instruction is load-bearing and must be present
    for name in PASSES:
        template = load_prompt(name).template.lower()
        assert "do not infer it" in template
        assert "uncertain" in template
