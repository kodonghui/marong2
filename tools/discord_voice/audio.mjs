import { Readable } from 'node:stream';

export const FRAME_MS = 20;
export const DISCORD_FRAME_BYTES = 3840;
const PREBUFFER_BYTES = 8 * DISCORD_FRAME_BYTES;
const MAX_OUTPUT_BYTES = 300 * DISCORD_FRAME_BYTES;

// Discord uses 48 kHz stereo. Average each three stereo samples for 16 kHz mono.
export function microphonePcm(pcm) {
  const length = Math.floor(pcm.length / 12);
  const mono = Buffer.allocUnsafe(length * 2);
  for (let sample = 0; sample < length; sample++) {
    let sum = 0;
    for (let offset = 0; offset < 12; offset += 2) {
      sum += pcm.readInt16LE(sample * 12 + offset);
    }
    mono.writeInt16LE(Math.round(sum / 6), sample * 2);
  }
  return mono;
}

// Interpolate between adjacent samples, keeping the edge sample across chunks.
export class PlaybackPcm {
  previous = null;

  convert(pcm) {
    const output = Buffer.allocUnsafe(pcm.length * 4);
    for (let offset = 0; offset < pcm.length; offset += 2) {
      const next = pcm.readInt16LE(offset);
      const previous = this.previous ?? next;
      const middle = Math.round((previous + next) / 2);
      output.writeInt16LE(middle, offset * 4);
      output.writeInt16LE(middle, offset * 4 + 2);
      output.writeInt16LE(next, offset * 4 + 4);
      output.writeInt16LE(next, offset * 4 + 6);
      this.previous = next;
    }
    return output;
  }
}

// The Discord audio player pulls 20 ms frames. Silence keeps the Opus stream
// alive between turns and during short upstream gaps. No old audio is replayed.
export class CallPlayback extends Readable {
  #chunks = [];
  #queued = 0;
  #timer = null;
  #prebuffer = true;
  #finished = false;
  #drained = false;
  #sequence = 0;
  #epoch = 0;
  #pcm = new PlaybackPcm();

  constructor(encode, onMetric) {
    super({ objectMode: true, highWaterMark: 1 });
    this.encode = encode;
    this.onMetric = onMetric;
  }

  clear(epoch = this.#epoch) {
    this.#chunks.length = 0;
    this.#queued = 0;
    this.#prebuffer = true;
    this.#finished = false;
    this.#drained = false;
    this.#sequence = 0;
    this.#epoch = epoch;
    this.#pcm = new PlaybackPcm();
  }

  add(packet) {
    if (packet.length < 26 || packet.toString('ascii', 0, 4) !== 'MRG2') return;
    const epoch = packet.readUInt32BE(4);
    const sequence = packet.readUInt32BE(12);
    if (packet.length !== 24 + 2 * packet.readUInt32BE(20) || epoch < this.#epoch) return;
    if (epoch > this.#epoch) this.clear(epoch);
    if (sequence <= this.#sequence) return;
    this.#sequence = sequence;
    this.#finished = false;
    this.#drained = false;
    const pcm = this.#pcm.convert(packet.subarray(24));
    if (this.#queued + pcm.length > MAX_OUTPUT_BYTES) {
      this.onMetric('output_overflow');
      this.#chunks.length = 0;
      this.#queued = 0;
      this.#prebuffer = true;
    }
    if (pcm.length > MAX_OUTPUT_BYTES) return;
    this.#chunks.push(pcm);
    this.#queued += pcm.length;
  }

  finish() { this.#finished = true; }

  _read() {
    if (this.#timer !== null) return;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      try {
        this.push(this.encode(this.#nextFrame()));
      } catch (error) {
        this.destroy(error);
      }
    }, FRAME_MS - 2);
  }

  _destroy(error, done) {
    clearTimeout(this.#timer);
    this.#timer = null;
    this.clear();
    done(error);
  }

  #nextFrame() {
    const frame = Buffer.alloc(DISCORD_FRAME_BYTES);
    if (this.#prebuffer) {
      if (!this.#queued || (this.#queued < PREBUFFER_BYTES && !this.#finished)) return frame;
      this.#prebuffer = false;
    }
    if (!this.#queued) {
      if (!this.#drained) {
        this.onMetric(this.#finished ? 'turn_played' : 'output_underflow');
        this.#drained = true;
      }
      return frame;
    }
    let written = 0;
    while (this.#queued && written < frame.length) {
      const chunk = this.#chunks[0];
      const size = Math.min(frame.length - written, chunk.length);
      chunk.copy(frame, written, 0, size);
      written += size;
      this.#queued -= size;
      if (size === chunk.length) this.#chunks.shift();
      else this.#chunks[0] = chunk.subarray(size);
    }
    return frame;
  }
}
