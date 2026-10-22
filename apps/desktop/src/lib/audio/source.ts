/**
 * Where microphone audio comes from. The web implementation works in browsers, WebView2 and
 * WebKitGTK; a native (Rust) source can replace it if a webview cannot capture.
 */
export interface AudioSource {
  /** Start capturing; `onFrame` receives 20 ms of PCM16 mono at 16 kHz (640 bytes). */
  start(onFrame: (pcm: ArrayBuffer) => void): Promise<void>
  stop(): Promise<void>
}

/** Loudness of a PCM16 frame, 0..1 (root mean square), for a level meter. */
export function level(pcm: ArrayBuffer): number {
  const samples = new Int16Array(pcm)
  if (samples.length === 0) return 0
  let sum = 0
  for (const sample of samples) sum += sample * sample
  return Math.sqrt(sum / samples.length) / 0x8000
}

/** A message the learner can act on, for errors from `getUserMedia` and friends. */
export function microphoneError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError') {
    return 'Microphone access was denied. Allow it in your browser or system settings.'
  }
  if (name === 'NotFoundError') return 'No microphone was found.'
  const detail = error instanceof Error ? error.message : String(error)
  return `Could not start the microphone: ${detail}`
}
