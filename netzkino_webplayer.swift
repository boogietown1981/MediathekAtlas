// MediathekAtlas local Netzkino viewer: loads the official page in WKWebView.
// No script injection, playback extraction, stream recording, DRM or ad bypass.
import Foundation
import AppKit
import WebKit

let arguments = CommandLine.arguments
func validPage(_ url: URL) -> Bool {
    guard url.scheme?.lowercased() == "https" else { return false }
    guard let host = url.host?.lowercased() else { return false }
    return host == "netzkino.de" || host == "www.netzkino.de"
}
guard arguments.count == 2, let page = URL(string: arguments[1]), validPage(page) else { exit(2) }

final class NetzkinoWindow: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow?
    var webview: WKWebView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let frame = NSRect(x: 0, y: 0, width: 1180, height: 780)
        let window = NSWindow(contentRect: frame,
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Netzkino · MediathekAtlas"
        window.center()
        window.delegate = self
        let config = WKWebViewConfiguration()
        config.websiteDataStore = WKWebsiteDataStore.default()
        config.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: frame, configuration: config)
        view.navigationDelegate = self
        view.uiDelegate = self
        window.contentView = view
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        view.load(URLRequest(url: page))
        self.window = window
        self.webview = view
    }
    func windowWillClose(_ notification: Notification) { NSApp.terminate(nil) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { return true }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.navigationType == .linkActivated,
           let url = navigationAction.request.url,
           !validPage(url) {
            // User-selected off-domain links never launch Safari automatically.
            decisionHandler(.cancel)
        } else { decisionHandler(.allow) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        // Provider pop-ups are not needed for normal playback; do not redirect outside MediathekAtlas.
        if let url = navigationAction.request.url, validPage(url) { webView.load(URLRequest(url: url)) }
        return nil
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let viewer = NetzkinoWindow()
app.delegate = viewer
app.run()
