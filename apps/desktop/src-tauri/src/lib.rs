//! voice-tutor desktop shell: a native Tauri 2 window around the React UI in `../src`.
//!
//! Pure, unit-tested modules (`audio`, `permissions`) hold the logic; `shell` wires them into
//! Tauri.

pub mod audio;
mod permissions;
mod shell;

pub use shell::run;
