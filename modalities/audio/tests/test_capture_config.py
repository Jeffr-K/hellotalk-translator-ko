from pathlib import Path

import pytest

from capture import CaptureConfig


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_seconds", 0),
        ("channels", 0),
        ("block_duration_ms", 10),
        ("queue_seconds", 0),
    ],
)
def test_capture_config_rejects_invalid_values(field: str, value: int) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError):
        CaptureConfig(output=Path("capture.wav"), **kwargs)
