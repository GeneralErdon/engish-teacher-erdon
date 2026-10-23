// AudioWorklet processor (audio thread): microphone samples -> PCM16, mono, 16 kHz, 20 ms frames.
//
// The AudioContext runs at the device rate (44.1 or 48 kHz): Firefox and WebKit refuse to connect
// a microphone to a context at another rate. So this resamples itself, averaging the input
// samples that fall in each output sample (a box filter: cheap, and enough for speech
// recognition).
//
// Plain JavaScript in public/: worklets load as separate modules, outside the app bundle.

const TARGET_RATE = 16000
const FRAME_SAMPLES = 320 // 20 ms

class PcmRecorder extends AudioWorkletProcessor {
  constructor() {
    super()
    this.step = sampleRate / TARGET_RATE // input samples per output sample
    this.position = 0
    this.sum = 0
    this.count = 0
    this.frame = new Int16Array(FRAME_SAMPLES)
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i]
      this.count += 1
      this.position += 1
      if (this.position < this.step) continue
      this.position -= this.step
      const sample = Math.max(-1, Math.min(1, this.sum / this.count))
      this.sum = 0
      this.count = 0
      this.frame[this.filled++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      if (this.filled === FRAME_SAMPLES) {
        const buffer = this.frame.buffer.slice(0)
        this.port.postMessage(buffer, [buffer])
        this.filled = 0
      }
    }
    return true
  }
}

registerProcessor('pcm-recorder', PcmRecorder)
