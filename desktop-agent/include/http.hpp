#pragma once
#include <string>

namespace dayplan_agent {
struct HttpResult {
    unsigned long status = 0;
    std::string body;
    std::string error;
    bool ok() const { return status >= 200 && status < 300; }
};
class HttpClient {
public:
    explicit HttpClient(const std::wstring& base_url);
    HttpResult request(const std::wstring& method, const std::wstring& path,
                       const std::string& body, const std::string& token) const;
private:
    std::wstring host_;
    unsigned short port_ = 8000;
};
}
