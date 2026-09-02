from screen.aggregate import aggregate, agreement
from screen.schema import Decision


def D(decision, conf=0.9, hits=None):
    return Decision(decision=decision, criteria_hit=hits or [], reason="r",
                    confidence=conf)


def test_agree_include_advances():
    a = aggregate(D("include"), D("include"))
    assert a.final == "include" and not a.routed_to_queue


def test_agree_exclude_high_conf_excludes():
    a = aggregate(D("exclude", 0.9), D("exclude", 0.95))
    assert a.final == "exclude" and not a.routed_to_queue


def test_agree_exclude_low_conf_queues():
    a = aggregate(D("exclude", 0.9), D("exclude", 0.6))
    assert a.final == "queued" and a.queue_reason == "low_confidence_exclude"


def test_disagreement_queues():
    a = aggregate(D("include"), D("exclude"))
    assert a.final == "queued" and a.queue_reason == "pass_disagreement"


def test_both_uncertain_queues():
    a = aggregate(D("uncertain", 0.5), D("uncertain", 0.4))
    assert a.final == "queued" and a.queue_reason == "model_uncertain"


def test_one_uncertain_queues_as_disagreement():
    a = aggregate(D("include"), D("uncertain", 0.5))
    assert a.final == "queued" and a.queue_reason == "pass_disagreement"


def test_include_low_conf_still_advances():
    # only excludes are confidence-gated; includes are provisional
    a = aggregate(D("include", 0.4), D("include", 0.4))
    assert a.final == "include" and not a.routed_to_queue


def test_refmine_flag_when_both_exclude_review():
    a = aggregate(D("exclude", 0.95, ["review_or_meta"]),
                  D("exclude", 0.95, ["review_or_meta"]))
    assert a.final == "exclude" and a.is_refmine_target


def test_no_refmine_flag_on_ordinary_exclude():
    a = aggregate(D("exclude", 0.95, ["animal"]), D("exclude", 0.95, ["animal"]))
    assert not a.is_refmine_target


def test_agreement_helper():
    assert agreement(D("include"), D("include"))
    assert not agreement(D("include"), D("exclude"))
