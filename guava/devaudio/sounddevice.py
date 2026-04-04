import asyncio
import fractions
import threading
import time
import logging

import numpy as np
import av
import sounddevice as sd

from typing import Literal
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
from aiortc import MediaStreamTrack

logger = logging.getLogger("guava.devaudio.sounddevice")

class SoundDeviceMicrophoneTrack(MediaStreamTrack):
    """
    Microphone input track using sounddevice.InputStream.

    Captures audio from the system's default input device and yields
    AudioFrame objects suitable for WebRTC transmission via aiortc.

    Output frames:
        - format: s16 (packed signed 16-bit)
        - layout: mono
        - sample_rate: 48000
        - samples per frame: 960 (20 ms)
    """

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._pts = 0
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()

        self._stream = sd.InputStream(
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._sample_rate = int(self._stream.samplerate)
        self._stream.start()

    def _callback(self, indata: np.ndarray, _frames: int, _time_info, _status):
        assert self._loop
        self._loop.call_soon_threadsafe(self._queue.put_nowait, indata.copy())

    def stop(self):
        super().stop()
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

    async def recv(self) -> AudioFrame:
        data = await self._queue.get()

        frame = AudioFrame.from_ndarray(data.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = self._sample_rate
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, self._sample_rate)

        self._pts += data.shape[0]
        return frame


class SoundDeviceAudioPlayer:
    """
    Audio player using sounddevice.OutputStream.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks = np.empty(0, dtype=np.int16)
        self._state: Literal["unopened", "open", "closed"] = "unopened"
        self._skip_callbacks = 0

        # blocksize=0 lets PortAudio choose a suitable callback size.
        self._stream = sd.OutputStream(
            samplerate=None,
            channels=1,
            dtype="int16",
            blocksize=0,
            callback=self._callback,
        )

        self._resampler = AudioResampler(
            format="s16",
            layout="mono",
            rate=self._stream.samplerate
        )

    def start(self):
        assert self._state == "unopened"
        self._stream.start()
        self._state = "open"

    def add_frame(self, frame: AudioFrame):
        assert self._state == "open"
        resampled: list[AudioFrame] = self._resampler.resample(frame)
        with self._lock:
            for f in resampled:
                self._chunks = np.concatenate([self._chunks, f.to_ndarray().reshape(-1)])

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        assert self._state == "open"
        try:
            self._stream.stop()
        finally:
            self._stream.close()
            self._state = "closed"

    def _callback(self, outdata: np.ndarray, frames: int, _time_info, _status):
        if self._skip_callbacks:
            self._skip_callbacks -= 1
            outdata.fill(0)
        
        with self._lock:
            n = min(len(self._chunks), frames)
            outdata[:n, 0] = self._chunks[:n]
            self._chunks = self._chunks[n:]

        if n < frames:
            outdata[n:, 0] = 0
            logger.debug("Audio player underflow. Skipping some callbacks to help catch up...")
            self._skip_callbacks = 1

if __name__ == "__main__":
    """
    Example usage:

        python player.py input.wav

    This demo decodes audio frames with PyAV and feeds them directly into the
    player. The source audio must already decode to:
        - s16
        - stereo
        - 48000 Hz

    If your real source is a socket, decode/reformat upstream and call
    player.add_frame(frame) for each frame you receive.
    """
    import sys

    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} input-audio-file")
        raise SystemExit(2)

    player = SoundDeviceAudioPlayer()
    player.start()

    try:
        container = av.open(sys.argv[1])
        stream = container.streams.audio[0]

        for frame in container.decode(stream):
            player.add_frame(frame)

        # Let buffered audio finish playing.
        while True:
            with player._lock:
                remaining = len(player._chunks)
            if remaining == 0:
                break
            time.sleep(0.05)

        time.sleep(0.2)

    finally:
        player.close()