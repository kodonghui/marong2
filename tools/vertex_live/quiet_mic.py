"""Keep a 300 ms microphone lead-in and forward the next second after speech."""

from array import array
from collections import deque
from math import sqrt
from sys import byteorder

CHUNK = 640  # 320 signed 16-bit samples at 16 kHz


def level(pcm):
    samples = array("h")
    samples.frombytes(pcm)
    if byteorder == "big":
        samples.byteswap()
    return sqrt(sum(value * value for value in samples) / len(samples)) / 32768 if samples else 0.0


class QuietMic:
    def __init__(self, threshold):
        self.threshold = float(threshold)
        self.pending = bytearray()
        self.before = deque()
        self.open = False
        self.loud = 0
        self.quiet = 0
        self.sent_ms = 0
        self.held_ms = 0

    def counts(self):
        held = self.held_ms + 20 * len(self.before)
        result = self.sent_ms, held
        self.sent_ms = 0
        # Won't count a buffered frame in the next segment before it is released or evicted.
        self.held_ms = -20 * len(self.before)
        return result

    def feed(self, pcm):
        """Yield audio blocks and one None marker when the gate closes."""
        self.pending.extend(pcm)
        complete = len(self.pending) // CHUNK * CHUNK
        for offset in range(0, complete, CHUNK):
            frame = bytes(self.pending[offset:offset + CHUNK])
            loud = level(frame) >= self.threshold
            if self.open:
                self.quiet = 0 if loud else self.quiet + 1
                self.sent_ms += 20
                yield frame
                if self.quiet == 50:
                    self.open = False
                    self.loud = 0
                    yield None
                continue
            self.loud = self.loud + 1 if loud else 0
            if len(self.before) == 15:
                self.before.popleft()
                self.held_ms += 20
            self.before.append(frame)
            if self.loud >= 2:
                self.open, self.quiet = True, 0
                self.sent_ms += 20 * len(self.before)
                self.held_ms = max(0, self.held_ms)
                yield b"".join(self.before)
                self.before.clear()
        del self.pending[:complete]
