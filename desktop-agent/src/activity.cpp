#include <deque>
#include "activity.hpp"
#include <windows.h>
#include <rpc.h>
#include <algorithm>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace dayplan_agent {
std::uint32_t idle_elapsed(std::uint32_t now, std::uint32_t last) {
    // LASTINPUTINFO uses a wrapping DWORD; unsigned subtraction preserves elapsed time.
    return (now - last) / 1000;
}

Snapshot sample(std::uint32_t idle_threshold) {
    Snapshot result;
    LASTINPUTINFO input{};
    input.cbSize = sizeof(input);
    if (!GetLastInputInfo(&input)) return result;
    result.idle_seconds = idle_elapsed(GetTickCount(), input.dwTime);
    if (result.idle_seconds >= idle_threshold) {
        result.state = "idle";
        return result;
    }
    HWND window = GetForegroundWindow();
    DWORD pid = 0;
    if (!window || !GetWindowThreadProcessId(window, &pid)) return result;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) return result;
    wchar_t path[32768]{};
    DWORD size = static_cast<DWORD>(std::size(path));
    const bool success = QueryFullProcessImageNameW(process, 0, path, &size) != 0;
    CloseHandle(process);
    if (!success) return result;
    std::wstring full(path, size);
    const auto slash = full.find_last_of(L"\\/");
    const std::wstring name = full.substr(slash == std::wstring::npos ? 0 : slash + 1);
    const int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, name.data(),
                                         static_cast<int>(name.size()), nullptr, 0, nullptr, nullptr);
    if (length <= 0) return result;
    result.app.resize(static_cast<std::size_t>(length));
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, name.data(), static_cast<int>(name.size()),
                        result.app.data(), length, nullptr, nullptr);
    if (result.app.size() > 120) {
        result.app.clear();
        return result;
    }
    result.state = "active";
    return result;
}

std::string new_id() {
    UUID id{};
    const auto status = UuidCreate(&id);
    if (status != RPC_S_OK && status != RPC_S_UUID_LOCAL_ONLY) throw std::runtime_error("Cannot create event ID");
    RPC_CSTR output = nullptr;
    if (UuidToStringA(&id, &output) != RPC_S_OK) throw std::runtime_error("Cannot encode event ID");
    std::string result(reinterpret_cast<const char*>(output));
    RpcStringFreeA(&output);
    return result;
}

std::string escape_json(const std::string& value) {
    std::ostringstream output;
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') output << '\\' << static_cast<char>(c);
        else if (c < 0x20) output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c);
        else output << static_cast<char>(c);
    }
    return output.str();
}

std::string utc_timestamp(Time value) {
    const auto stamp = std::chrono::system_clock::to_time_t(value);
    std::tm utc{};
    gmtime_s(&utc, &stamp);
    std::ostringstream output;
    output << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return output.str();
}

std::string event_json(const Event& event) {
    std::ostringstream output;
    output << "{\"id\":\"" << event.id << "\",\"starts_at\":\"" << utc_timestamp(event.start)
           << "\",\"ends_at\":\"" << utc_timestamp(event.end) << "\",\"app_name\":";
    if (event.activity.app.empty()) output << "null";
    else output << '"' << escape_json(event.activity.app) << '"';
    output << ",\"state\":\"" << event.activity.state << "\",\"idle_seconds\":"
           << event.activity.idle_seconds << '}';
    return output.str();
}

std::string batch_json(const std::deque<Event>& events, std::size_t count) {
    std::string result = "{\"events\":[";
    for (std::size_t i = 0; i < std::min(count, events.size()); ++i) {
        if (i) result += ',';
        result += event_json(events[i]);
    }
    return result + "]}";
}
}
