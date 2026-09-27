import AppKit
import CryptoKit
import Darwin
import Foundation
import Security

@main
final class OpenAgronomyDesktop: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let statusLabel = NSTextField(labelWithString: "Checking the local installation…")
    private let detailLabel = NSTextField(labelWithString: "")
    private let setupButton = NSButton(title: "Install local model", target: nil, action: nil)
    private let openButton = NSButton(title: "Open workspace", target: nil, action: nil)
    private let quitButton = NSButton(title: "Quit", target: nil, action: nil)
    private let spinner = NSProgressIndicator()
    private var operation: Process?
    private var backend: Process?
    private var backendGeneration = 0
    private var backendLog: FileHandle?
    private var lockDescriptor: Int32 = -1
    private var port = 0
    private var pairingToken = ""
    private var pairingURLUsed = false
    private var isQuitting = false

    static func main() {
        let app = NSApplication.shared
        let delegate = OpenAgronomyDesktop()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }

    private var runtimeRoot: URL {
        Bundle.main.resourceURL!.appendingPathComponent("runtime", isDirectory: true)
    }

    private var backendExecutable: URL {
        Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Helpers/OpenAgronomyBackend.app/Contents/MacOS/OpenAgronomyBackend"
        )
    }

    private var stateRoot: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenAgronomyAgent/desktop", isDirectory: true)
    }

    private func writeStatus(_ phase: String, browserOpened: Bool? = nil) {
        var row: [String: Any] = [
            "schema_version": "open_agronomy_agent.macos_launcher_status.v1",
            "phase": phase,
            "launcher_pid": Int(ProcessInfo.processInfo.processIdentifier),
            "backend_pid": backend?.isRunning == true ? Int(backend!.processIdentifier) : 0,
            "port": port,
            "updated_at": ISO8601DateFormatter().string(from: Date()),
        ]
        if !pairingToken.isEmpty {
            row["launch_id"] = SHA256.hash(data: Data(pairingToken.utf8))
                .map { String(format: "%02x", $0) }.joined()
        }
        if let browserOpened = browserOpened {
            row["browser_opened"] = browserOpened
        }
        let path = stateRoot.appendingPathComponent("launcher-status.json")
        do {
            let data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            try data.write(to: path, options: [.atomic])
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600], ofItemAtPath: path.path
            )
        } catch {
            // The status receipt is diagnostic; the visible window remains authoritative.
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildWindow()
        guard FileManager.default.fileExists(atPath: backendExecutable.path),
              FileManager.default.fileExists(
                atPath: runtimeRoot.appendingPathComponent("frontend/dist/index.html").path
              ) else {
            showFailure("The application bundle is incomplete. Reinstall this version.")
            return
        }
        do {
            try FileManager.default.createDirectory(
                at: stateRoot,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            guard acquireInstanceLock() else {
                showFailure("Open Agronomy is already running for this account.")
                return
            }
        } catch {
            showFailure("Could not prepare private application state: \(error.localizedDescription)")
            return
        }
        writeStatus("checking")
        checkModel()
    }

    func applicationWillTerminate(_ notification: Notification) {
        isQuitting = true
        stopOwnedProcess(operation)
        stopOwnedProcess(backend)
        backend = nil
        backendLog?.closeFile()
        writeStatus("stopped")
        if lockDescriptor >= 0 {
            flock(lockDescriptor, LOCK_UN)
            close(lockDescriptor)
        }
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.terminate(nil)
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 225),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Open Agronomy"
        window.center()
        window.delegate = self

        let title = NSTextField(labelWithString: "Open Agronomy")
        title.font = NSFont.boldSystemFont(ofSize: 22)
        statusLabel.font = NSFont.systemFont(ofSize: 15)
        detailLabel.font = NSFont.systemFont(ofSize: 12)
        detailLabel.textColor = .secondaryLabelColor
        detailLabel.lineBreakMode = .byWordWrapping
        detailLabel.maximumNumberOfLines = 3
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.startAnimation(nil)

        setupButton.target = self
        setupButton.action = #selector(installModelClicked)
        setupButton.isEnabled = false
        openButton.target = self
        openButton.action = #selector(openWorkspaceClicked)
        openButton.isEnabled = false
        quitButton.target = self
        quitButton.action = #selector(quitClicked)

        let buttons = NSStackView(views: [setupButton, openButton, quitButton])
        buttons.orientation = .horizontal
        buttons.spacing = 12
        let progress = NSStackView(views: [spinner, statusLabel])
        progress.orientation = .horizontal
        progress.spacing = 8
        let stack = NSStackView(views: [title, progress, detailLabel, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: window.contentView!.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: window.contentView!.bottomAnchor, constant: -24),
            detailLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 465),
        ])
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func acquireInstanceLock() -> Bool {
        let path = stateRoot.appendingPathComponent("launcher.lock").path
        lockDescriptor = open(path, O_RDWR | O_CREAT, S_IRUSR | S_IWUSR)
        return lockDescriptor >= 0 && flock(lockDescriptor, LOCK_EX | LOCK_NB) == 0
    }

    private func showFailure(_ message: String) {
        spinner.stopAnimation(nil)
        statusLabel.stringValue = "Could not open the workspace"
        detailLabel.stringValue = message
        setupButton.isEnabled = false
        openButton.isEnabled = false
        writeStatus("error")
    }

    private func setBusy(_ status: String, detail: String = "") {
        spinner.startAnimation(nil)
        statusLabel.stringValue = status
        detailLabel.stringValue = detail
        setupButton.isEnabled = false
        openButton.isEnabled = false
    }

    private func processArguments(_ command: String) -> [String] {
        [command, "--runtime-root", runtimeRoot.path, "--state-root", stateRoot.path,
         "--require-bundle-manifest"]
    }

    private func checkModel() {
        setBusy("Checking the pinned local model…")
        writeStatus("checking")
        runOneShot("status") { [weak self] code, output in
            guard let self = self, !self.isQuitting else { return }
            guard code == 0, let result = self.lastJSON(output),
                  let phase = result["phase"] as? String else {
                self.showFailure("Model check failed. See the application log or reinstall.")
                return
            }
            if phase == "ready" {
                self.startBackend()
            } else {
                self.spinner.stopAnimation(nil)
                self.statusLabel.stringValue = "One-time model setup required"
                self.detailLabel.stringValue = "The pinned local model will download after you choose Install local model."
                self.setupButton.isEnabled = true
                self.writeStatus("setup_required")
            }
        }
    }

    private func runOneShot(_ command: String, completion: @escaping (Int32, String) -> Void) {
        let process = Process()
        process.executableURL = backendExecutable
        process.arguments = processArguments(command)
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
        } catch {
            completion(1, error.localizedDescription)
            return
        }
        operation = process
        DispatchQueue.global(qos: .utility).async {
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let output = String(data: data, encoding: .utf8) ?? ""
            DispatchQueue.main.async {
                self.operation = nil
                completion(process.terminationStatus, output)
            }
        }
    }

    private func lastJSON(_ output: String) -> [String: Any]? {
        for line in output.split(whereSeparator: \.isNewline).reversed() {
            if let data = String(line).data(using: .utf8),
               let row = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return row
            }
        }
        return nil
    }

    @objc private func installModelClicked(_ sender: Any?) {
        setBusy("Installing the pinned local model…", detail: "This may take several minutes. Keep the app open.")
        writeStatus("installing_model")
        runOneShot("install-model") { [weak self] code, output in
            guard let self = self, !self.isQuitting else { return }
            if code == 0, self.lastJSON(output)?["phase"] as? String == "ready" {
                self.startBackend()
            } else {
                self.showFailure("Check the connection and free disk, then choose Install local model to retry.")
                self.setupButton.isEnabled = true
            }
        }
    }

    private func randomSecret() -> String? {
        var bytes = [UInt8](repeating: 0, count: 32)
        let result = bytes.withUnsafeMutableBytes { buffer in
            SecRandomCopyBytes(kSecRandomDefault, buffer.count, buffer.baseAddress!)
        }
        guard result == errSecSuccess else { return nil }
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func availablePort(_ requestedPort: Int = 0) -> Int? {
        let descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return nil }
        defer { Darwin.close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(requestedPort).bigEndian)
        _ = "127.0.0.1".withCString { inet_pton(AF_INET, $0, &address.sin_addr) }
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else { return nil }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let named = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.getsockname(descriptor, $0, &length)
            }
        }
        guard named == 0 else { return nil }
        return Int(UInt16(bigEndian: address.sin_port))
    }

    private func stablePort() throws -> Int {
        let path = stateRoot.appendingPathComponent("desktop-port.json")
        if FileManager.default.fileExists(atPath: path.path) {
            let data = try Data(contentsOf: path)
            let row = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard row?["schema_version"] as? String == "open_agronomy_agent.desktop_port.v1",
                  let saved = row?["port"] as? Int, 1024 <= saved, saved <= 65535 else {
                throw NSError(domain: "OpenAgronomyDesktop", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "The saved local port is invalid."])
            }
            guard availablePort(saved) == saved else {
                throw NSError(domain: "OpenAgronomyDesktop", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "The saved local port is in use. Close its owner and retry."])
            }
            return saved
        }
        guard let chosen = availablePort(), 1024 <= chosen, chosen <= 65535 else {
            throw NSError(domain: "OpenAgronomyDesktop", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "Could not reserve a local port."])
        }
        let data = try JSONSerialization.data(
            withJSONObject: ["schema_version": "open_agronomy_agent.desktop_port.v1", "port": chosen],
            options: [.sortedKeys]
        )
        try data.write(to: path, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        return chosen
    }

    private func startBackend() {
        backendGeneration += 1
        let generation = backendGeneration
        let selectedPort: Int
        do {
            selectedPort = try stablePort()
        } catch {
            showFailure(error.localizedDescription)
            openButton.title = "Retry opening"
            openButton.isEnabled = true
            return
        }
        guard let token = randomSecret(), let secret = randomSecret() else {
            showFailure("Could not create a private local session.")
            return
        }
        port = selectedPort
        pairingToken = token
        pairingURLUsed = false
        setBusy("Starting the local workspace…")
        let logs = stateRoot.appendingPathComponent("logs", isDirectory: true)
        do {
            backendLog?.closeFile()
            backendLog = nil
            try FileManager.default.createDirectory(
                at: logs, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let path = logs.appendingPathComponent("backend.log")
            if !FileManager.default.fileExists(atPath: path.path) {
                FileManager.default.createFile(atPath: path.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: path)
            handle.seekToEndOfFile()
            backendLog = handle
            let process = Process()
            process.executableURL = backendExecutable
            process.arguments = processArguments("serve") + ["--port", String(port)]
            var environment = ProcessInfo.processInfo.environment
            environment.removeValue(forKey: "PYTHONPATH")
            environment.removeValue(forKey: "PYTHONHOME")
            environment["AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN"] = token
            environment["AGRONOMY_AGENT_DESKTOP_SESSION_SECRET"] = secret
            process.environment = environment
            process.standardOutput = handle
            process.standardError = handle
            process.terminationHandler = { [weak self] terminated in
                DispatchQueue.main.async {
                    guard let self = self, !self.isQuitting,
                          self.backend === terminated else { return }
                    self.backend = nil
                    self.showFailure("The local service stopped. Check the private backend log, then retry opening it.")
                    self.openButton.title = "Retry opening"
                    self.openButton.isEnabled = true
                }
            }
            try process.run()
            backend = process
            writeStatus("starting")
            pollHealth(attemptsRemaining: 180, generation: generation)
        } catch {
            showFailure("Could not start the local service: \(error.localizedDescription)")
        }
    }

    private func pollHealth(attemptsRemaining: Int, generation: Int) {
        guard !isQuitting, generation == backendGeneration else { return }
        guard attemptsRemaining > 0, backend?.isRunning == true else {
            let failedBackend = backend
            backend = nil
            stopOwnedProcess(failedBackend)
            showFailure("The local service did not become ready. Check its private log, then retry opening it.")
            openButton.title = "Retry opening"
            openButton.isEnabled = true
            return
        }
        let url = URL(string: "http://127.0.0.1:\(port)/api/health")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { data, response, _ in
            DispatchQueue.main.async {
                guard !self.isQuitting, generation == self.backendGeneration else { return }
                let status = (response as? HTTPURLResponse)?.statusCode
                let payload = data.flatMap {
                    try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
                }
                let pairing = payload?["local_pairing"] as? [String: Any]
                let expected = SHA256.hash(data: Data(self.pairingToken.utf8))
                    .map { String(format: "%02x", $0) }.joined()
                if status == 200, payload?["status"] as? String == "ok",
                   pairing?["launch_id"] as? String == expected {
                    self.spinner.stopAnimation(nil)
                    self.statusLabel.stringValue = "Ready on this Mac"
                    self.detailLabel.stringValue = "Your fields and answers stay local. Reopen and reconnect starts a fresh private session."
                    self.openButton.title = "Reopen and reconnect"
                    self.openButton.isEnabled = true
                    let opened = self.openWorkspace()
                    if opened {
                        self.writeStatus("ready", browserOpened: true)
                    } else {
                        self.showFailure("Could not open the browser workspace. Retry opening it.")
                        self.openButton.title = "Retry opening"
                        self.openButton.isEnabled = true
                    }
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        self.pollHealth(attemptsRemaining: attemptsRemaining - 1, generation: generation)
                    }
                }
            }
        }.resume()
    }

    @discardableResult private func openWorkspace() -> Bool {
        let suffix = pairingURLUsed ? "" : "/#pair=\(pairingToken)"
        let url = URL(string: "http://127.0.0.1:\(port)\(suffix.isEmpty ? "/" : suffix)")!
        let opened = NSWorkspace.shared.open(url)
        pairingURLUsed = opened
        return opened
    }

    @objc private func openWorkspaceClicked(_ sender: Any?) {
        if backend?.isRunning == true {
            stopOwnedProcess(backend)
            backend = nil
        }
        startBackend()
    }

    @objc private func quitClicked(_ sender: Any?) {
        NSApp.terminate(nil)
    }

    private func stopOwnedProcess(_ process: Process?) {
        guard let process = process, process.isRunning else { return }
        process.terminate()
        let deadline = Date().addingTimeInterval(5)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
        }
        if process.isRunning {
            Darwin.kill(process.processIdentifier, SIGKILL)
            process.waitUntilExit()
        }
    }
}
