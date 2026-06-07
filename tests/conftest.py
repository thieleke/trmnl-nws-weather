from pathlib import Path

import pytest

from trmnl_nws_weather import nws
from trmnl_nws_weather.models import Forecast

SAMPLE_XML = Path(__file__).resolve().parents[1] / "docs" / "MapClick.php.xml"


@pytest.fixture(scope="session")
def sample_forecast() -> Forecast:
    return nws.parse(SAMPLE_XML.read_bytes())
