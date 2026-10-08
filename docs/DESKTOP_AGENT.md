# Native Windows companion

C++17, CMake; no third-party runtime library. WinHTTP, User32 and Rpcrt4 are system dependencies.

## Design

- GetForegroundWindow and GetWindowThreadProcessId identify the foreground process.
- OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) and QueryFullProcessImageNameW obtain only an executable basename. The full temporary path is never transmitted.
- GetLastInputInfo and wrapping DWORD tick subtraction estimate idle time for the current interactive session.
- Sampling every five seconds approximates the preceding interval using its initial snapshot. Rapid switches between samples can be missed.
- Missing/denied foreground information becomes unknown, not a false productivity classification.
- UUID event IDs permit safe retries if a successful response is lost.
- WinHTTP timeouts bound connection failures. HTTP redirects are disabled and backend host selection is loopback-only.
- The in-memory buffer holds at most 240 intervals. Backoff caps at 120 seconds; oldest unsent intervals are dropped if it fills.
- Suspend/clock-change gaps over five minutes are discarded rather than fabricated as observed activity.
- Ctrl+C stops sampling. No startup entry, background service or disk activity log is installed.

Two opt-ins are required: backend Settings and the explicit --enable CLI flag. A disabled backend rejects activity and the process stops when it next reports. Token rejection also stops sampling.

## Validation

The local CMake/Ninja release build was performed on Windows using Clang 20 via Zig 0.15.2's C++ driver. CTest validates JSON escaping, UTC serialization, tick rollover, local URL restrictions and refusal to start without opt-in. Reachable and unreachable backend probes exercise native WinHTTP GET.

--test-report sends a synthetic unknown 30-second interval without calling foreground or idle APIs. backend/scripts/agent_smoke.py creates an isolated temporary API/database and verifies the native WinHTTP POST persisted that event. No real monitoring is enabled for this check.

The GitHub Actions Windows job builds using MSVC and runs CTest. Its native ingestion smoke check uses the same synthetic event path. Sustained real-user monitoring, suspend/resume behavior and MSVC execution still need validation on a user's machine.

References: [GetLastInputInfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo), [WinHTTP](https://learn.microsoft.com/en-us/windows/win32/winhttp/about-winhttp).
