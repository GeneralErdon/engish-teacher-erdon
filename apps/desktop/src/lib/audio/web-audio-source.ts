import type { AudioSource } from './source'

const WORKLET_URL = '/pcm-recorder.worklet.js'

/** `getUserMedia` + an AudioWorklet that turns the microphone into PCM16 frames. */
export function createWebAudioSource(workletUrl = WORKLET_URL): AudioSource {
  let stream: MediaStream | undefined
  let context: AudioContext | undefined

  const stop = async () => {
    for (const track of stream?.getTracks() ?? []) track.stop()
    const open = context
    stream = undefined
    context = undefined
    await open?.close()
  }

  return {
    async start(onFrame) {
      // Undefined outside secure contexts: the microphone needs HTTPS or localhost.
      if (!(navigator.mediaDevices as MediaDevices | undefined)) {
        throw new Error('the microphone needs HTTPS or localhost')
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
        context = new AudioContext()
        await context.audioWorklet.addModule(workletUrl)
        const recorder = new AudioWorkletNode(context, 'pcm-recorder')
        recorder.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
          onFrame(event.data)
        }
        context.createMediaStreamSource(stream).connect(recorder)
      } catch (error) {
        await stop()
        throw error
      }
    },
    stop,
  }
}
