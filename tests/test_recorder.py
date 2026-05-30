import numpy as np
import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder


@pytest.fixture(autouse=True)
def _no_sleep(mocker):
    # Keep retry tests fast — don't actually wait between attempts.
    mocker.patch.object(recorder.time, "sleep")


def _fake_stream(mocker):
    stream = mocker.MagicMock()
    return stream


def test_start_opens_stream_on_first_try(mocker):
    stream = _fake_stream(mocker)
    factory = mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    rec = AudioRecorder()
    rec.start()
    factory.assert_called_once()
    stream.start.assert_called_once()
    recorder.time.sleep.assert_not_called()


def test_start_retries_then_succeeds(mocker):
    good = _fake_stream(mocker)
    # First two opens fail, third succeeds.
    factory = mocker.patch.object(
        recorder.sd,
        "InputStream",
        side_effect=[RuntimeError("device busy"), RuntimeError("device busy"), good],
    )
    rec = AudioRecorder()
    rec.start()
    assert factory.call_count == 3
    good.start.assert_called_once()
    assert recorder.time.sleep.call_count == 2


def test_start_raises_after_all_attempts_fail(mocker):
    mocker.patch.object(recorder.sd, "InputStream", side_effect=RuntimeError("device busy"))
    rec = AudioRecorder()
    with pytest.raises(RuntimeError, match="Could not open microphone"):
        rec.start()


def test_stop_swallows_close_errors(mocker):
    stream = _fake_stream(mocker)
    stream.stop.side_effect = RuntimeError("already closed")
    mocker.patch.object(recorder.sd, "InputStream", return_value=stream)
    rec = AudioRecorder()
    rec.start()
    # Feed a chunk so stop() has audio to return.
    rec._callback(np.ones((10, 1), dtype=np.float32), 10, None, None)
    out = rec.stop()              # must not raise
    assert out.shape[0] == 10
