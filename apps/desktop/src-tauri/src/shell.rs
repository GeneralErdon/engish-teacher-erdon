//! Tauri wiring: builds the app and connects the pure modules to the webview.
//!
//! Everything here needs a real window and webview, so unit tests cannot reach it and it is
//! excluded from the coverage gate (`just test-rust`). The decisions it delegates to live in
//! fully tested modules (`permissions`); this file is checked by clippy on Linux and Windows in
//! CI and by the manual microphone smoke test before each release (`docs/development.md`).

use tauri::webview::PermissionKind;
use tauri::{Manager, Runtime, Webview};

use crate::permissions;

/// Builds and runs the app: called from `main.rs` on desktop, and by Android through the
/// generated entry point.
///
/// # Panics
///
/// If the Tauri runtime cannot start, e.g. the system webview is missing.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .on_permission_request(|webview, kind| on_permission_request(&webview, kind))
        .setup(|app| {
            setup(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the voice-tutor desktop app");
}

fn on_permission_request<R: Runtime>(
    webview: &Webview<R>,
    kind: PermissionKind,
) -> tauri::webview::PermissionResponse {
    let dev_url = if cfg!(debug_assertions) {
        webview.config().build.dev_url.as_ref()
    } else {
        None
    };
    permissions::respond(kind, webview.url().ok().as_ref(), dev_url)
}

/// Per-webview settings that cannot be expressed through the builder. On Linux, turns on
/// WebKitGTK's `enable-media-stream`, which `getUserMedia` needs and wry leaves off.
#[cfg_attr(
    not(target_os = "linux"),
    expect(
        clippy::unnecessary_wraps,
        reason = "only Linux has per-webview work to do"
    )
)]
fn setup<R: Runtime>(app: &tauri::App<R>) -> tauri::Result<()> {
    #[cfg(target_os = "linux")]
    for window in app.webview_windows().into_values() {
        window.with_webview(|webview| {
            use webkit2gtk::{SettingsExt, WebViewExt};
            if let Some(settings) = WebViewExt::settings(&webview.inner()) {
                settings.set_enable_media_stream(true);
            }
        })?;
    }
    #[cfg(not(target_os = "linux"))]
    let _ = app;
    Ok(())
}
