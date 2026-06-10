"""Tests for the procedurally drawn icons, including the render cache.

``icons.render`` / ``icons.glyph`` are ``lru_cache``-d: their results are used
only as immutable paste masks, so a shared instance is returned for repeated
calls with the same arguments.
"""

from trmnl_nws_weather import icons
from trmnl_nws_weather.models import Sky


def test_render_is_cached_per_arguments():
    a = icons.render(Sky.RAIN, 40)
    b = icons.render(Sky.RAIN, 40)
    assert a is b  # same object served from the cache


def test_render_distinguishes_night_and_size():
    day = icons.render(Sky.SUNNY, 40, night=False)
    night = icons.render(Sky.SUNNY, 40, night=True)
    bigger = icons.render(Sky.SUNNY, 48, night=False)
    assert day is not night
    assert day is not bigger


def test_render_returns_expected_image():
    img = icons.render(Sky.THUNDERSTORM, 32)
    assert img.mode == "L"
    assert img.size == (32, 32)


def test_glyph_is_cached_per_arguments():
    assert icons.glyph("wind", 18) is icons.glyph("wind", 18)
    assert icons.glyph("wind", 18) is not icons.glyph("droplet", 18)
