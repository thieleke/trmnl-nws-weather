import io
import struct

from dataclasses import replace

from trmnl_nws_weather import render
from trmnl_nws_weather.config import Device, Settings, Theme, Units


def test_device_preset_overrides_dimensions():
    # The X preset expands to its fixed panel and wins over individual flags.
    s = Settings(device=Device.X, width=800, height=480, bit_depth=2)
    assert (s.width, s.height, s.bit_depth) == (1872, 1404, 4)
    og = Settings(device=Device.OG)
    assert (og.width, og.height, og.bit_depth) == (800, 480, 2)


def test_no_device_keeps_individual_dimensions():
    s = Settings(width=1024, height=768, bit_depth=4)
    assert (s.device, s.width, s.height, s.bit_depth) == (None, 1024, 768, 4)


def test_device_x_renders_expected_panel(sample_forecast):
    img = render.render(sample_forecast, Settings(device=Device.X))
    assert img.size == (1872, 1404)
    assert set(img.get_flattened_data()) <= set(range(16))


def test_render_dimensions_and_palette(sample_forecast):
    img = render.render(sample_forecast, Settings())
    assert img.mode == "P"
    assert img.size == (800, 480)
    # Only the four 2-bit grey levels may be used.
    assert set(img.get_flattened_data()) <= {0, 1, 2, 3}


def test_render_scales_to_proportional_panel(sample_forecast):
    # A 5:3 panel larger than the default fills exactly: same aspect, no border.
    img = render.render(sample_forecast, replace(Settings(), width=1600, height=960))
    assert img.size == (1600, 960)
    assert set(img.get_flattened_data()) <= {0, 1, 2, 3}


def test_render_letterboxes_offaspect_panel(sample_forecast):
    # A 4:3 panel (the 1872x1404 hardware target) keeps the 5:3 content and frames
    # the surrounding whitespace; the image still fills the whole panel.
    img = render.render(sample_forecast, replace(Settings(), width=1872, height=1404))
    assert img.size == (1872, 1404)
    # The letterboxed corners are background: in the light theme that is white,
    # which is the brightest entry of the 2-bit ramp (palette index 3).
    px = img.load()
    assert px[0, 0] == 3
    # The light-theme frame is drawn in the foreground (black, index 0) somewhere
    # down the centre of the top letterbox band.
    cx = img.size[0] // 2
    assert any(px[cx, y] == 0 for y in range(180))


def test_dark_mode_hides_letterbox_border(sample_forecast):
    # In dark mode the frame would be a bright white line on the black letterbox;
    # it is suppressed, so the top band is entirely background (black, index 0).
    img = render.render(
        sample_forecast, replace(Settings(), width=1872, height=1404, theme=Theme.DARK))
    px = img.load()
    cx = img.size[0] // 2
    assert all(px[cx, y] == 0 for y in range(180))


def test_render_4bit_depth(sample_forecast):
    img = render.render(sample_forecast, replace(Settings(), bit_depth=4))
    assert img.size == (800, 480)
    # 4-bit allows up to sixteen grey levels.
    assert set(img.get_flattened_data()) <= set(range(16))
    assert max(img.get_flattened_data()) > 3  # actually uses the deeper ramp


def test_saved_png_honours_bit_depth(sample_forecast, tmp_path):
    img = render.render(sample_forecast, replace(Settings(), bit_depth=4))
    out = tmp_path / "out.png"
    img.save(out, format="PNG", bits=4)
    data = out.read_bytes()
    i = data.index(b"IHDR")
    _w, _h, bit_depth, color_type = struct.unpack(">IIBB", data[i + 4 : i + 14])
    assert bit_depth == 4
    assert color_type == 3  # palette


def test_saved_png_is_2bit(sample_forecast, tmp_path):
    img = render.render(sample_forecast, Settings())
    out = tmp_path / "out.png"
    img.save(out, format="PNG", bits=2)
    data = out.read_bytes()
    i = data.index(b"IHDR")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[i + 4 : i + 14])
    assert (width, height) == (800, 480)
    assert bit_depth == 2
    assert color_type == 3  # palette


def test_render_variants_all_succeed(sample_forecast):
    for theme in Theme:
        for unit in Units:
            settings = Settings(theme=theme, units=unit)
            img = render.render(sample_forecast, settings)
            assert img.size == (800, 480)
