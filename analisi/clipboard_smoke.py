"""External Windows clipboard fixture for desktop smoke tests."""

from base64 import b64decode, b64encode
import subprocess
import time


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[Console]::WriteLine('READY')
while ($null -ne ($request = [Console]::ReadLine())) {
    try {
        if ($request.StartsWith('SET:')) {
            $bytes = [Convert]::FromBase64String($request.Substring(4))
            [Windows.Forms.Clipboard]::SetText([Text.Encoding]::UTF8.GetString($bytes))
            [Console]::WriteLine('OK')
        } elseif ($request -eq 'GET') {
            $text = [Windows.Forms.Clipboard]::GetText()
            $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
            [Console]::WriteLine('DATA:' + $encoded)
        } else {
            throw 'Unknown clipboard fixture command'
        }
    } catch {
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_.Exception.Message))
        [Console]::WriteLine('ERROR:' + $encoded)
    }
}
"""


class WindowsClipboardFixture:
    """Keep one STA process alive and service Tk while it accesses the clipboard."""

    def __init__(self, worker, pump_events, diagnostics_path):
        self.worker = worker
        self.pump_events = pump_events
        self.diagnostics_path = diagnostics_path
        self.process = None

    def _response(self, request, timeout, operation):
        process = self.process

        def exchange():
            if request is not None:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            return process.stdout.readline().rstrip("\r\n")

        future = self.worker.submit(exchange)
        deadline = time.monotonic() + timeout
        while not future.done():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Windows clipboard fixture {operation} exceeded {timeout} seconds")
            # Tk renders its clipboard data on demand for the outside process.
            self.pump_events()
            time.sleep(.02)
        reply = future.result()
        if reply.startswith("ERROR:"):
            message = b64decode(reply[6:], validate=True).decode("utf-8")
            raise RuntimeError(f"Windows clipboard fixture {operation}: {message}")
        if not reply:
            raise RuntimeError(f"Windows clipboard fixture closed during {operation}; see {self.diagnostics_path.name}")
        return reply

    def _start(self):
        if self.process is not None:
            return
        encoded = b64encode(_SCRIPT.encode("utf-16le")).decode("ascii")
        # PowerShell can emit a progress record on stderr before the READY line.
        with self.diagnostics_path.open("wb") as diagnostics:
            self.process = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics,
                encoding="ascii", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
            )
        # Cold .NET/WinForms startup can be much slower than a clipboard operation.
        if self._response(None, 240, "startup") != "READY":
            raise RuntimeError("Windows clipboard fixture did not report readiness")

    def put(self, text):
        self._start()
        encoded = b64encode(text.encode("utf-8")).decode("ascii")
        if self._response(f"SET:{encoded}", 15, "write") != "OK":
            raise RuntimeError("Windows clipboard fixture did not acknowledge the write")

    def get(self):
        self._start()
        reply = self._response("GET", 15, "read")
        if not reply.startswith("DATA:"):
            raise RuntimeError("Windows clipboard fixture did not return data")
        return b64decode(reply[5:], validate=True).decode("utf-8")

    def close(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        finally:
            process.stdin.close()
            process.stdout.close()
