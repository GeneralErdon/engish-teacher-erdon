//! voice-tutor desktop shell: a native Tauri 2 window around the React UI in `../src`.

pub mod audio;
mod permissions;

/// Builds and runs the desktop app (called from `main.rs`).
///
/// # Panics
///
/// If the Tauri runtime cannot start, e.g. the system webview is missing.
pub fn run() {
    permissions::register(tauri::Builder::default())
        .setup(|app| {
            permissions::setup(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the voice-tutor desktop app");
}
