// OpenTicker for Mac: a native window around the local OpenTicker server.
//
// The server (Python) runs as a LaunchAgent so it keeps alerts and the brief warm even when this window is
// closed. This app makes sure it's running (via the `openticker` command whose path is in Info.plist under
// OTCLI), then shows it in a WKWebView. Links that leave the app open in your browser.
//
// Build: swiftc -O -swift-version 5 -o OpenTicker OpenTicker.swift   (`openticker setup` does this for you)

import Cocoa
import WebKit

let appName = "OpenTicker"
let repoURL = URL(string: "https://github.com/bin01/openticker")!

// MARK: - Settings shared with the CLI

func otHome() -> URL {
    if let h = ProcessInfo.processInfo.environment["OPENTICKER_HOME"], !h.isEmpty {
        return URL(fileURLWithPath: (h as NSString).expandingTildeInPath)
    }
    return FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/OpenTicker")
}

func otPort() -> Int {
    let url = otHome().appendingPathComponent("config.json")
    if let data = try? Data(contentsOf: url),
       let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
       let p = obj["port"] as? Int {
        return p
    }
    return 8765
}

func cliPath() -> String? {
    if let p = Bundle.main.object(forInfoDictionaryKey: "OTCLI") as? String,
       FileManager.default.isExecutableFile(atPath: p) {
        return p
    }
    for p in ["~/.local/bin/openticker", "/opt/homebrew/bin/openticker", "/usr/local/bin/openticker"] {
        let e = (p as NSString).expandingTildeInPath
        if FileManager.default.isExecutableFile(atPath: e) { return e }
    }
    return nil
}

// MARK: - Colors

extension NSColor {
    /// Parses "rgb(13, 16, 15)" / "rgba(...)" / "#0d100f".
    static func css(_ s: String) -> NSColor? {
        let t = s.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("#"), t.count == 7, let v = Int(t.dropFirst(), radix: 16) {
            return NSColor(srgbRed: CGFloat((v >> 16) & 255) / 255, green: CGFloat((v >> 8) & 255) / 255,
                           blue: CGFloat(v & 255) / 255, alpha: 1)
        }
        let nums = t.components(separatedBy: CharacterSet(charactersIn: "0123456789.").inverted)
            .compactMap { Double($0) }
        guard nums.count >= 3 else { return nil }
        return NSColor(srgbRed: CGFloat(nums[0]) / 255, green: CGFloat(nums[1]) / 255,
                       blue: CGFloat(nums[2]) / 255, alpha: 1)
    }
}

let lightBG = NSColor(srgbRed: 0xf4 / 255.0, green: 0xf5 / 255.0, blue: 0xf2 / 255.0, alpha: 1)
let darkBG = NSColor(srgbRed: 0x0d / 255.0, green: 0x10 / 255.0, blue: 0x0f / 255.0, alpha: 1)
let systemBG = NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? darkBG : lightBG }

// MARK: - The window

final class Controller: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, NSWindowDelegate {
    let window: NSWindow
    let web: WKWebView
    var home: URL { URL(string: "http://127.0.0.1:\(otPort())/")! }
    var starting = false

    override init() {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        cfg.applicationNameForUserAgent = "OpenTicker/\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "1") Version/18.0 Safari/605.1.15"
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: .zero, configuration: cfg)
        web.allowsBackForwardNavigationGestures = false
        web.allowsMagnification = true
        web.setValue(false, forKey: "drawsBackground")   // no white flash before the page paints

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 920),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        super.init()
        cfg.userContentController.add(self, name: "ot")
        web.navigationDelegate = self
        web.uiDelegate = self

        window.title = appName
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        if #available(macOS 11.0, *) { window.titlebarSeparatorStyle = .none }
        window.backgroundColor = systemBG
        window.minSize = NSSize(width: 820, height: 560)
        window.contentView = web
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.center()
        window.setFrameAutosaveName("OpenTickerMain")
        window.makeKeyAndOrderFront(nil)
        boot()
    }

    // MARK: Server

    func boot() {
        guard !starting else { return }
        starting = true
        showMessage("Starting OpenTicker", detail: nil, spinner: true)
        DispatchQueue.global(qos: .userInitiated).async {
            var ok = self.ping()
            var why: String? = nil
            if !ok {
                if let cli = cliPath() {
                    let p = Process()
                    p.executableURL = URL(fileURLWithPath: cli)
                    p.arguments = ["start", "--quiet"]
                    var env = ProcessInfo.processInfo.environment
                    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:" + (env["PATH"] ?? "")
                    p.environment = env
                    let err = Pipe()
                    p.standardError = err
                    p.standardOutput = FileHandle.nullDevice
                    do {
                        try p.run()
                        p.waitUntilExit()
                        if p.terminationStatus != 0 {
                            why = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)
                        }
                    } catch { why = error.localizedDescription }
                } else {
                    why = "The openticker command wasn't found. Reinstall with the one-line installer."
                }
                let end = Date().addingTimeInterval(30)
                while !ok && Date() < end {
                    ok = self.ping()
                    if !ok { Thread.sleep(forTimeInterval: 0.35) }
                }
            }
            DispatchQueue.main.async {
                self.starting = false
                if ok {
                    self.web.load(URLRequest(url: self.home))
                } else {
                    self.showMessage("OpenTicker didn't start",
                                     detail: (why?.trimmingCharacters(in: .whitespacesAndNewlines)).flatMap { $0.isEmpty ? nil : $0 }
                                        ?? "Run “openticker doctor” in Terminal to see what's wrong.",
                                     spinner: false)
                }
            }
        }
    }

    func ping() -> Bool {
        var req = URLRequest(url: home.appendingPathComponent("api/app"))
        req.timeoutInterval = 1.5
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            ok = (resp as? HTTPURLResponse)?.statusCode == 200
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 2)
        return ok
    }

    func showMessage(_ title: String, detail: String?, spinner: Bool) {
        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        }
        let html = """
        <!doctype html><meta charset="utf-8"><style>
        :root{color-scheme:light dark;--bg:#f4f5f2;--ink:#121513;--ink3:#7c847f;--acc:#2f9e68}
        @media (prefers-color-scheme:dark){:root{--bg:#0d100f;--ink:#eef1ee;--ink3:#7c857f;--acc:#41c585}}
        html,body{height:100%;margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,system-ui;
          -webkit-user-select:none;cursor:default}
        body{display:grid;place-items:center}
        .c{text-align:center;max-width:440px;padding:24px}
        svg{width:56px;height:56px;margin-bottom:18px}
        h1{font-size:17px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
        p{color:var(--ink3);margin:0 0 18px;white-space:pre-wrap;font-size:13px}
        .s{width:16px;height:16px;border-radius:50%;border:2px solid color-mix(in srgb,var(--ink3) 35%,transparent);
          border-top-color:var(--acc);margin:4px auto 0;animation:r .8s linear infinite}
        @keyframes r{to{transform:rotate(360deg)}}
        button{font:500 13px -apple-system;padding:7px 16px;border-radius:8px;border:0;background:var(--acc);color:#fff;cursor:pointer}
        </style><div class="c">
        <svg viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#121513"/><rect x="112" y="276" width="72" height="124" rx="14" fill="#5b6560"/><rect x="220" y="196" width="72" height="204" rx="14" fill="#2f9e68"/><rect x="328" y="112" width="72" height="288" rx="14" fill="#41c585"/></svg>
        <h1>\(esc(title))</h1>
        \(detail.map { "<p>\(esc($0))</p>" } ?? "")
        \(spinner ? "<div class=s></div>" : "<button onclick=\"webkit.messageHandlers.ot.postMessage({retry:1})\">Try again</button>")
        </div>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    // MARK: Page ↔ app

    func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if body["retry"] != nil { boot(); return }
        if let bg = body["bg"] as? String, let c = NSColor.css(bg) {
            window.backgroundColor = c
            let dark = (body["dark"] as? Bool) ?? false
            window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        }
    }

    func isInternal(_ url: URL?) -> Bool {
        guard let url = url else { return true }
        if ["about", "data", "blob"].contains(url.scheme ?? "") { return true }
        return (url.host == "127.0.0.1" || url.host == "localhost") && url.port == otPort()
    }

    /// Only web and mail links leave the app; any other scheme is dropped.
    func openOutside(_ url: URL) {
        if ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if !isInternal(action.request.url), let url = action.request.url,
           action.navigationType == .linkActivated || action.targetFrame?.isMainFrame == true {
            openOutside(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    // target=_blank and window.open
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isInternal(url) { web.load(URLRequest(url: url)) } else { openOutside(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")
        a.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    // <input type=file>: WKWebView shows no file dialog on its own
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        let done: (NSApplication.ModalResponse) -> Void = { r in
            completionHandler(r == .OK ? panel.urls : nil)
        }
        if let w = webView.window {
            panel.beginSheetModal(for: w, completionHandler: done)
        } else {
            panel.begin(completionHandler: done)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { lost(error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { lost(error) }

    func lost(_ error: Error) {
        let e = error as NSError
        if e.code == NSURLErrorCancelled { return }
        boot()   // the server restarted or went away: bring it back
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { web.reload() }

    // MARK: Menu actions

    @objc func reload(_ sender: Any?) { if web.url == nil || web.url?.scheme == "about" { boot() } else { web.reload() } }
    @objc func openInBrowser(_ sender: Any?) { NSWorkspace.shared.open(web.url.flatMap { isInternal($0) && $0.scheme == "http" ? $0 : nil } ?? home) }
    @objc func zoomIn(_ sender: Any?) { web.pageZoom = min(web.pageZoom + 0.1, 2) }
    @objc func zoomOut(_ sender: Any?) { web.pageZoom = max(web.pageZoom - 0.1, 0.6) }
    @objc func actualSize(_ sender: Any?) { web.pageZoom = 1 }
    @objc func showWindow(_ sender: Any?) { window.makeKeyAndOrderFront(nil) }
    @objc func openRepo(_ sender: Any?) { NSWorkspace.shared.open(repoURL) }
    @objc func openLogs(_ sender: Any?) { NSWorkspace.shared.open(otHome().appendingPathComponent("logs/server.log")) }
    @objc func openData(_ sender: Any?) { NSWorkspace.shared.open(otHome()) }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate {
    var c: Controller!

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        c = Controller()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { c.window.makeKeyAndOrderFront(nil) }
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    func item(_ title: String, _ action: Selector?, _ key: String = "", _ mods: NSEvent.ModifierFlags = .command,
              target: AnyObject? = nil) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
        i.keyEquivalentModifierMask = mods
        i.target = target
        return i
    }

    func buildMenu() {
        let main = NSMenu()
        func sub(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let top = NSMenuItem()
            let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            top.submenu = m
            main.addItem(top)
            return m
        }
        let me = self as AnyObject
        _ = sub(appName, [
            item("About \(appName)", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("Show Your Data in Finder", #selector(AppDelegate.openData(_:)), target: me),
            item("Show Server Log", #selector(AppDelegate.openLogs(_:)), target: me),
            .separator(),
            item("Hide \(appName)", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("Quit \(appName)", #selector(NSApplication.terminate(_:)), "q"),
        ])
        _ = sub("File", [
            item("Open in Browser", #selector(AppDelegate.openInBrowser(_:)), "o", [.command, .shift], target: me),
            .separator(),
            item("Close Window", #selector(NSWindow.performClose(_:)), "w"),
        ])
        _ = sub("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        _ = sub("View", [
            item("Reload", #selector(AppDelegate.reload(_:)), "r", target: me),
            .separator(),
            item("Actual Size", #selector(AppDelegate.actualSize(_:)), "0", target: me),
            item("Zoom In", #selector(AppDelegate.zoomIn(_:)), "=", target: me),
            item("Zoom Out", #selector(AppDelegate.zoomOut(_:)), "-", target: me),
            .separator(),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        let win = sub("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            .separator(),
            item(appName, #selector(AppDelegate.showWindow(_:)), "0", [.command, .option], target: me),
        ])
        NSApp.windowsMenu = win
        let help = sub("Help", [item("\(appName) on GitHub", #selector(AppDelegate.openRepo(_:)), target: me)])
        NSApp.helpMenu = help
        NSApp.mainMenu = main
    }

    @objc func reload(_ s: Any?) { c.reload(s) }
    @objc func openInBrowser(_ s: Any?) { c.openInBrowser(s) }
    @objc func zoomIn(_ s: Any?) { c.zoomIn(s) }
    @objc func zoomOut(_ s: Any?) { c.zoomOut(s) }
    @objc func actualSize(_ s: Any?) { c.actualSize(s) }
    @objc func showWindow(_ s: Any?) { c.showWindow(s) }
    @objc func openRepo(_ s: Any?) { c.openRepo(s) }
    @objc func openLogs(_ s: Any?) { c.openLogs(s) }
    @objc func openData(_ s: Any?) { c.openData(s) }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
