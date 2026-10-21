import numpy as np

from metrics import CaptureMetrics


def test_capture_metrics_measure_signal_and_failures() -> None:
    metrics = CaptureMetrics()
    pcm = np.array([[-32_768], [0], [16_384], [32_767]], dtype=np.int16)

    metrics.record_callback(frame_count=4, has_status=True)
    metrics.record_written(pcm)
    metrics.record_queue_overflow()
    metrics.record_sequence_gap(2)

    snapshot = metrics.snapshot()
    assert snapshot.callbacks == 1
    assert snapshot.frames_received == 4
    assert snapshot.frames_written == 4
    assert snapshot.callback_status_events == 1
    assert snapshot.queue_overflows == 1
    assert snapshot.sequence_gaps == 2
    assert snapshot.clipped_samples == 2
    assert snapshot.peak == 1.0
    assert 0.74 < snapshot.rms < 0.76
