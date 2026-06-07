import io
import struct

from trmnl_nws_weather import render
from trmnl_nws_weather.config import Settings, Theme, Units


def test_render_dimensions_and_palette(sample_forecast):
    img = render.render(sample_forecast, Settings())
    assert img.mode == "P"
    assert img.size == (800, 480)
    # Only the four 2-bit grey levels may be used.
    assert set(img.get_flattened_data()) <= {0, 1, 2, 3}


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
