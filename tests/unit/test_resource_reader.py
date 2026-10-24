import pytest

from app.services.resource_reader import resource_reader_url


@pytest.mark.parametrize("chapter", ["capabilities", "risks", "strategies", "governance"])
def test_curriculum_chapters_are_readable(chapter):
    url = f"https://ai-safety-atlas.com/chapters/v1/{chapter}/introduction/"
    assert resource_reader_url(url) == url


@pytest.mark.parametrize("suffix", ["", "introduction/", "current-capabilities/#examples", "introduction#section-1.2"])
def test_chapter_paths_and_safe_anchors_are_preserved(suffix):
    url = f"https://ai-safety-atlas.com/chapters/v1/capabilities/{suffix}"
    assert resource_reader_url(url) == url


def test_explicit_default_https_port_is_allowed():
    url = "https://ai-safety-atlas.com:443/chapters/v1/risks/introduction/"
    assert resource_reader_url(url) == url


@pytest.mark.parametrize("url", [
    "",
    None,
    "http://ai-safety-atlas.com/chapters/v1/capabilities/introduction/",
    "//ai-safety-atlas.com/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com.evil.test/chapters/v1/capabilities/introduction/",
    "https://www.ai-safety-atlas.com/chapters/v1/capabilities/introduction/",
    "https://user@ai-safety-atlas.com/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com@evil.test/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com:444/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com:/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com:garbage/chapters/v1/capabilities/introduction/",
    "https://[ai-safety-atlas.com/chapters/v1/capabilities/introduction/",
    "https://ai-safety-atlas.com/chapters/v1/evaluations/introduction/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities-elsewhere/introduction/",
    "https://ai-safety-atlas.com/chapters/v2/capabilities/introduction/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/../risks/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/./introduction/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/%2e%2e/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/%252e%252e/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/%69ntroduction/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/%2f%2fevil.test/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities//introduction/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/\\evil.test/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/?redirect=https://evil.test",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/#%0a",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/#unsafe anchor",
    " https://ai-safety-atlas.com/chapters/v1/capabilities/",
    "\nhttps://ai-safety-atlas.com/chapters/v1/capabilities/",
    "https://ai-safety-atlas.com/chapters/v1/capa\tbilities/",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/\n",
    "https://ai-safety-atlas.com/chapters/v1/capabilities/\x00",
])
def test_unknown_or_ambiguous_urls_do_not_embed(url):
    assert resource_reader_url(url) is None
