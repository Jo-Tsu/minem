import AppKit

final class Launcher: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow?
    private var task: Process?
    private let address = URL(string: "http://127.0.0.1:8790/")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 1
        let session = URLSession(configuration: configuration)
        session.dataTask(with: address.appendingPathComponent("api/version")) { data, response, _ in
            let payload = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let release = payload?["release"] as? [String: Any]
            let ready = (response as? HTTPURLResponse)?.statusCode == 200 && release?["product"] as? String == "MineM"
            DispatchQueue.main.async {
                if ready {
                    NSWorkspace.shared.open(self.address)
                    NSApp.terminate(nil)
                } else {
                    self.start()
                }
            }
        }.resume()
    }

    private func start() {
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 130),
            styleMask: [.titled, .closable], backing: .buffered, defer: false
        )
        panel.title = "MineM"
        panel.delegate = self
        panel.isReleasedWhenClosed = false
        let spinner = NSProgressIndicator(frame: NSRect(x: 26, y: 53, width: 28, height: 28))
        spinner.style = .spinning
        spinner.startAnimation(nil)
        panel.contentView?.addSubview(spinner)
        let title = NSTextField(labelWithString: "正在打开 MineM…")
        title.font = .systemFont(ofSize: 17, weight: .semibold)
        title.frame = NSRect(x: 72, y: 68, width: 260, height: 24)
        panel.contentView?.addSubview(title)
        let detail = NSTextField(labelWithString: "准备就绪后自动打开浏览器")
        detail.font = .systemFont(ofSize: 13)
        detail.textColor = .secondaryLabelColor
        detail.frame = NSRect(x: 72, y: 42, width: 270, height: 22)
        panel.contentView?.addSubview(detail)
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = panel

        guard let script = Bundle.main.object(forInfoDictionaryKey: "MineMLaunchScript") as? String else {
            finish("启动脚本路径丢失，请重新安装桌面入口。")
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [script]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = pipe
        process.standardError = pipe
        process.terminationHandler = { completed in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let message = String(data: data, encoding: .utf8) ?? "启动未完成"
            DispatchQueue.main.async {
                self.finish(completed.terminationStatus == 0 ? nil : message)
            }
        }
        task = process
        do { try process.run() }
        catch { finish(error.localizedDescription) }
    }

    private func finish(_ error: String?) {
        window?.close()
        window = nil
        if let error = error {
            let alert = NSAlert()
            alert.messageText = "MineM 启动失败"
            alert.informativeText = error
            alert.runModal()
        }
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let app = NSApplication.shared
let launcher = Launcher()
app.delegate = launcher
app.setActivationPolicy(.accessory)
app.run()
