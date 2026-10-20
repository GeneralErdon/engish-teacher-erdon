//! Optional native microphone capture: the fallback for webviews where `getUserMedia` fails.
//!
//! **Not implemented yet.** Phase 0 decides whether it is needed (see `docs/roadmap.md`). If it
//! is, this module captures with `cpal`, downmixes and resamples to the client wire format below,
//! and emits 20 ms frames to the UI as Tauri events. The UI consumes them through the same
//! `AudioSource` interface as browser capture (`src/lib/audio/nativeSource.ts`), so the rest of
//! the app does not care where the audio came from.
//!
//! The constants mirror `vt_contracts.audio` (the Python source of truth).

/// Client to server sample rate: PCM16 little-endian, mono.
pub const SAMPLE_RATE_HZ: usize = 16_000;

/// Duration of one frame sent to the api.
pub const FRAME_MS: usize = 20;

/// Samples per frame: 320 at 16 kHz.
pub const FRAME_SAMPLES: usize = SAMPLE_RATE_HZ * FRAME_MS / 1000;

/// Bytes per frame (2 bytes per PCM16 sample): 640.
pub const FRAME_BYTES: usize = FRAME_SAMPLES * 2;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frame_matches_the_wire_contract() {
        assert_eq!(FRAME_SAMPLES, 320);
        assert_eq!(FRAME_BYTES, 640);
    }
}
