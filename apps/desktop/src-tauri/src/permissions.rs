//! Microphone permission policy for the UI's `getUserMedia`.
//!
//! Before a page can capture media, the webview asks the app. WebKitGTK (Linux) silently *denies*
//! when the app does not answer, so the UI would never hear the learner. The policy:
//!
//! - **Microphone**: allowed, only for the app's own origins: the bundled UI and, in debug
//!   builds, the Vite dev server (`build.devUrl`).
//! - **Everything else** (camera, screen capture, geolocation, notifications...): denied.
//!
//! This module is pure (no webview types) so every rule is unit tested. `shell.rs` wires it into
//! Tauri's cross-platform `Builder::on_permission_request` (WebKitGTK's `permission-request`
//! signal on Linux, `PermissionRequested` on WebView2, `WKUIDelegate` on macOS), so every OS gets
//! the same rules.
//!
//! Status: unit tested; the real microphone check on Linux and Windows is Phase 0
//! (`docs/roadmap.md`).

use tauri::Url;
use tauri::webview::{PermissionKind, PermissionResponse};

/// Where the bundled UI is served from: `tauri://localhost` on Linux and macOS,
/// `http://tauri.localhost` on Windows.
const BUNDLED_ORIGINS: [&str; 2] = ["tauri://localhost", "http://tauri.localhost"];

/// Answers one permission request.
///
/// `page` is the URL loaded in the webview (if known); `dev_url` is the Vite dev server, which
/// callers pass only in debug builds.
pub fn respond(
    kind: PermissionKind,
    page: Option<&Url>,
    dev_url: Option<&Url>,
) -> PermissionResponse {
    decide(kind, page, &TrustedOrigins::new(dev_url))
}

/// The decision itself, free of webview types so it can be unit tested.
fn decide(
    kind: PermissionKind,
    page: Option<&Url>,
    trusted: &TrustedOrigins,
) -> PermissionResponse {
    match (kind, page) {
        (PermissionKind::Microphone, Some(page)) if trusted.contains(page) => {
            PermissionResponse::Allow
        }
        _ => PermissionResponse::Deny,
    }
}

/// Origins allowed to use the microphone.
#[derive(Debug)]
struct TrustedOrigins(Vec<Url>);

impl TrustedOrigins {
    /// The bundled UI, plus `dev_url` (callers pass it only in debug builds).
    fn new(dev_url: Option<&Url>) -> Self {
        let bundled = BUNDLED_ORIGINS
            .iter()
            .map(|origin| Url::parse(origin).expect("bundled origins are valid URLs"));
        Self(bundled.chain(dev_url.cloned()).collect())
    }

    fn contains(&self, page: &Url) -> bool {
        self.0.iter().any(|origin| same_origin(origin, page))
    }
}

/// Scheme, host and port equality. `Url::origin()` does not work here: custom schemes such as
/// `tauri://` have opaque origins, and opaque origins never compare equal.
fn same_origin(a: &Url, b: &Url) -> bool {
    a.scheme() == b.scheme()
        && a.host_str() == b.host_str()
        && a.port_or_known_default() == b.port_or_known_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    fn release() -> TrustedOrigins {
        TrustedOrigins::new(None)
    }

    fn debug() -> TrustedOrigins {
        TrustedOrigins::new(Some(&url("http://localhost:1420")))
    }

    #[test]
    fn bundled_ui_may_use_the_microphone_on_every_os() {
        for page in ["tauri://localhost/", "http://tauri.localhost/index.html"] {
            let response = decide(PermissionKind::Microphone, Some(&url(page)), &release());
            assert_eq!(response, PermissionResponse::Allow, "{page}");
        }
    }

    #[test]
    fn dev_server_is_trusted_only_when_passed_in() {
        let page = url("http://localhost:1420/");

        assert_eq!(
            decide(PermissionKind::Microphone, Some(&page), &debug()),
            PermissionResponse::Allow
        );
        assert_eq!(
            decide(PermissionKind::Microphone, Some(&page), &release()),
            PermissionResponse::Deny
        );
    }

    #[test]
    fn other_origins_are_denied() {
        for page in [
            "https://example.com/",
            "tauri://evil/",
            "http://localhost:1421/",
            "http://tauri.localhost:8080/",
        ] {
            let response = decide(PermissionKind::Microphone, Some(&url(page)), &debug());
            assert_eq!(response, PermissionResponse::Deny, "{page}");
        }
    }

    #[test]
    fn respond_trusts_the_dev_server_only_when_given() {
        let page = url("http://localhost:1420/");
        let dev = url("http://localhost:1420");

        assert_eq!(
            respond(PermissionKind::Microphone, Some(&page), Some(&dev)),
            PermissionResponse::Allow
        );
        assert_eq!(
            respond(PermissionKind::Microphone, Some(&page), None),
            PermissionResponse::Deny
        );
    }

    #[test]
    fn unknown_page_is_denied() {
        assert_eq!(
            decide(PermissionKind::Microphone, None, &release()),
            PermissionResponse::Deny
        );
    }

    #[test]
    fn everything_but_the_microphone_is_denied() {
        let page = url("tauri://localhost/");
        for kind in [
            PermissionKind::Camera,
            PermissionKind::DisplayCapture,
            PermissionKind::Geolocation,
            PermissionKind::Notifications,
        ] {
            assert_eq!(
                decide(kind, Some(&page), &release()),
                PermissionResponse::Deny,
                "{kind:?}"
            );
        }
    }
}
