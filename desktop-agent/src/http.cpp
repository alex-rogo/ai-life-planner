#include "http.hpp"
#include <windows.h>
#include <winhttp.h>
#include <stdexcept>

namespace dayplan_agent {
namespace {
class InternetHandle {
public:
    explicit InternetHandle(HINTERNET handle) : handle_(handle) {}
    ~InternetHandle() { if (handle_) WinHttpCloseHandle(handle_); }
    InternetHandle(const InternetHandle&) = delete;
    InternetHandle& operator=(const InternetHandle&) = delete;
    operator HINTERNET() const { return handle_; }
private:
    HINTERNET handle_;
};
}

HttpClient::HttpClient(const std::wstring& base_url) {
    URL_COMPONENTS parts{};
    parts.dwStructSize = sizeof(parts);
    parts.dwHostNameLength = static_cast<DWORD>(-1);
    parts.dwUrlPathLength = static_cast<DWORD>(-1);
    parts.dwExtraInfoLength = static_cast<DWORD>(-1);
    if (!WinHttpCrackUrl(base_url.c_str(), 0, 0, &parts))
        throw std::invalid_argument("Invalid backend URL");
    host_.assign(parts.lpszHostName, parts.dwHostNameLength);
    port_ = parts.nPort;
    // The agent deliberately cannot transmit activity to a remote host.
    if (parts.nScheme != INTERNET_SCHEME_HTTP ||
        (host_ != L"localhost" && host_ != L"127.0.0.1" && host_ != L"::1" && host_ != L"[::1]") ||
        (parts.dwUrlPathLength && std::wstring(parts.lpszUrlPath, parts.dwUrlPathLength) != L"/") ||
        parts.dwExtraInfoLength)
        throw std::invalid_argument("Use an HTTP loopback backend URL with no path or query");
}

HttpResult HttpClient::request(const std::wstring& method, const std::wstring& path,
                              const std::string& body, const std::string& token) const {
    HttpResult result;
    InternetHandle session(WinHttpOpen(L"DaylightAgent/0.1", WINHTTP_ACCESS_TYPE_NO_PROXY,
                                       WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0));
    if (!session) { result.error = "Cannot initialize WinHTTP"; return result; }
    WinHttpSetTimeouts(session, 2000, 2000, 3000, 3000);
    InternetHandle connection(WinHttpConnect(session, host_.c_str(), port_, 0));
    if (!connection) { result.error = "Cannot connect"; return result; }
    InternetHandle request(WinHttpOpenRequest(connection, method.c_str(), path.c_str(), nullptr,
                          WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0));
    if (!request) { result.error = "Cannot create request"; return result; }
    DWORD disable = WINHTTP_DISABLE_REDIRECTS;
    WinHttpSetOption(request, WINHTTP_OPTION_DISABLE_FEATURE, &disable, sizeof(disable));
    std::wstring headers = L"Content-Type: application/json\r\n";
    if (token.find_first_of("\r\n") != std::string::npos) { result.error = "Invalid token"; return result; }
    if (!token.empty()) {
        headers += L"X-Agent-Token: " + std::wstring(token.begin(), token.end()) + L"\r\n";
    }
    if (!WinHttpSendRequest(request, headers.c_str(), static_cast<DWORD>(headers.size()),
                           body.empty() ? WINHTTP_NO_REQUEST_DATA : const_cast<char*>(body.data()),
                           static_cast<DWORD>(body.size()), static_cast<DWORD>(body.size()), 0) ||
        !WinHttpReceiveResponse(request, nullptr)) {
        result.error = "Backend unreachable (WinHTTP " + std::to_string(GetLastError()) + ")";
        return result;
    }
    DWORD size = sizeof(DWORD);
    WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &result.status, &size, WINHTTP_NO_HEADER_INDEX);
    while (true) {
        DWORD available = 0;
        if (!WinHttpQueryDataAvailable(request, &available) || !available) break;
        if (result.body.size() + available > 1024 * 1024) {
            result.error = "Response too large"; result.status = 0; break;
        }
        std::string buffer(available, '\0');
        DWORD read = 0;
        if (!WinHttpReadData(request, buffer.data(), available, &read)) break;
        result.body.append(buffer.data(), read);
    }
    return result;
}
}
