// 쉬는 중 말소리 감지(AudioWorklet 방식). 기능 명세 3.3: 잡음 바닥보다 12dB 큰 소리가 350ms 넘게.
// 소리는 이 안에서 크기만 재고 어디에도 보내지 않아요. 5초마다 살아 있다는 신호만 보내요.
class Detector extends AudioWorkletProcessor {
  constructor() {
    super();
    this.win = Math.round(sampleRate * 0.02); // 20ms 창
    this.sum = 0;
    this.n = 0;
    this.floor = 0;
    this.above = 0;
    this.cool = 0;
    this.ticks = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) this.sum += ch[i] * ch[i];
      this.n += ch.length;
    } else {
      this.n += 128;
    }
    if (this.n >= this.win) {
      this.step(Math.sqrt(this.sum / this.n), this.n / sampleRate);
      this.sum = 0;
      this.n = 0;
    }
    return true;
  }

  step(x, dt) {
    if (this.floor === 0) this.floor = Math.max(x, 1e-4);
    const thr = Math.max(this.floor * 3.98, 0.008); // +12dB, 아주 조용한 방의 최소 문턱
    if (x > thr) {
      this.above += dt;
    } else {
      this.above = 0;
      if (x < this.floor) this.floor = Math.max(x, 1e-4);
      else this.floor = Math.min(x, this.floor * Math.pow(10, (3 * dt) / 20)); // 1초에 3dB씩만 올라감
    }
    if (this.cool > 0) this.cool -= dt;
    if (this.above >= 0.35 && this.cool <= 0) {
      this.port.postMessage({ type: "det", rms: x, floor: this.floor, at: currentTime });
      this.cool = 3;
      this.above = 0;
    }
    if (++this.ticks % 250 === 0) this.port.postMessage({ type: "alive", floor: this.floor, at: currentTime });
  }
}

registerProcessor("detector", Detector);
