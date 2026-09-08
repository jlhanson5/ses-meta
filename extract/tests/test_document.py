from extract.document import Document, Segment, from_jats


JATS = """
<article>
  <sec><title>Methods</title><p>Participants from ABCD. N was 500.</p></sec>
  <sec><title>Results</title><p>Income related to hippocampal volume, r=0.2.</p></sec>
  <table-wrap><label>Table 2</label><caption><p>Volumes by SES</p></caption>
    <tr><td>r</td><td>0.20</td></tr></table-wrap>
</article>
"""


def test_jats_splits_sections_and_tables():
    doc = from_jats(JATS, study_id="s1")
    locs = doc.locators()
    assert "Methods" in locs
    assert "Results" in locs
    assert any("Table 2" in l for l in locs)


def test_jats_text_is_tag_stripped():
    doc = from_jats(JATS, study_id="s1")
    joined = " ".join(s.text for s in doc.segments)
    assert "<p>" not in joined and "<td>" not in joined
    assert "hippocampal volume" in joined


def test_render_tags_each_segment_with_locator():
    doc = Document("s1", "demo", [Segment("p.1", "hello"), Segment("Table 2", "cells")])
    out = doc.render()
    assert "[[p.1]]" in out and "[[Table 2]]" in out
    assert "hello" in out and "cells" in out


def test_jats_without_sections_falls_back_to_fulltext():
    doc = from_jats("<article><p>bare text with amygdala</p></article>", study_id="s2")
    assert doc.segments
    assert "amygdala" in doc.segments[0].text
