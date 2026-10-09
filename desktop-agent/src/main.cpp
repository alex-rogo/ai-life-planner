#include <deque>
#include "activity.hpp"
#include "http.hpp"
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <thread>

namespace {
std::atomic<bool> running{true};
BOOL WINAPI stop(DWORD signal) {
    if (signal == CTRL_C_EVENT || signal == CTRL_BREAK_EVENT || signal == CTRL_CLOSE_EVENT) {
        running = false;
        return TRUE;
    }
    return FALSE;
}
void usage() {
    std::cout << "ai schedular Windows companion\n"
              << "  --enable              Explicitly opt into foreground-app and idle sampling\n"
              << "  --backend URL         HTTP loopback URL (default http://127.0.0.1:8000)\n"
              << "  --idle-seconds N      Idle threshold, 30-3600 (default 300)\n"
              << "  --report-seconds N    Report interval, 10-120 (default 30)\n"
              << "  --once                Send one sampled interval and exit\n"
              << "  --probe               Check backend health without sampling\n"
              << "  --test-report         Send synthetic unknown activity; no foreground sampling\n"
              << "  --self-test           Validate serialization and clock rollover without sampling\n"
              << "AGENT_TOKEN must match the backend. Monitoring must also be enabled in Settings.\n"
              << "Press Ctrl+C to stop. No screenshots, titles, keys or history are collected.\n";
}
int self_test() {
    using namespace dayplan_agent;
    if (idle_elapsed(500, 0xfffffe0cU) != 1) return 1;
    if (escape_json("a\"\\\n") != "a\\\"\\\\\\u000a") return 1;
    Event event{"00000000-0000-0000-0000-000000000001", Time{}, Time{} + std::chrono::seconds(30),
                Snapshot{"", "unknown", 0}};
    const auto body = batch_json(std::deque<Event>{event}, 100);
    if (body.find("\"app_name\":null") == std::string::npos ||
        body.find("1970-01-01T00:00:30Z") == std::string::npos) return 1;
    try { HttpClient invalid(L"https://example.com"); return 1; } catch (const std::invalid_argument&) {}
    std::cout << "Self-test passed. No activity sampled or transmitted.\n";
    return 0;
}
}

int main(int argc, char** argv) {
    try {
        bool enabled = false, once = false, probe = false, test_report = false;
        unsigned idle_threshold = 300, report_seconds = 30;
        std::wstring backend = L"http://127.0.0.1:8000";
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (option == "--help") { usage(); return 0; }
            if (option == "--self-test") return self_test();
            if (option == "--enable") enabled = true;
            else if (option == "--once") once = true;
            else if (option == "--probe") probe = true;
            else if (option == "--test-report") test_report = true;
            else if (option == "--backend" && i + 1 < argc) {
                const std::string value = argv[++i]; backend.assign(value.begin(), value.end());
            } else if ((option == "--idle-seconds" || option == "--report-seconds") && i + 1 < argc) {
                const std::string text = argv[++i];
                std::size_t parsed = 0;
                const auto value = std::stoul(text, &parsed);
                if (parsed != text.size()) throw std::invalid_argument("Invalid numeric option");
                if (option == "--idle-seconds") {
                    if (value < 30 || value > 3600) throw std::invalid_argument("Idle threshold must be 30-3600");
                    idle_threshold = static_cast<unsigned>(value);
                } else {
                    if (value < 10 || value > 120) throw std::invalid_argument("Report interval must be 10-120");
                    report_seconds = static_cast<unsigned>(value);
                }
            } else throw std::invalid_argument("Unknown or incomplete option: " + option);
        }
        dayplan_agent::HttpClient client(backend);
        if (probe) {
            const auto response = client.request(L"GET", L"/health", "", "");
            std::cout << (response.ok() ? "Backend reachable\n" : response.error + " HTTP " + std::to_string(response.status) + "\n");
            return response.ok() ? 0 : 1;
        }
        if (test_report) {
            const char* test_token = std::getenv("AGENT_TOKEN");
            if (!test_token || !*test_token) throw std::invalid_argument("Set AGENT_TOKEN for a synthetic test report");
            const auto end = std::chrono::system_clock::now();
            dayplan_agent::Event event{dayplan_agent::new_id(), end - std::chrono::seconds(30), end,
                                      dayplan_agent::Snapshot{"", "unknown", 0}};
            const auto response = client.request(L"POST", L"/api/activity",
                                                  dayplan_agent::batch_json({event}, 1), test_token);
            std::cout << "Synthetic test event: HTTP " << response.status << " (no activity sampled).\n";
            return response.ok() ? 0 : 1;
        }
        if (!enabled) { usage(); std::cerr << "Monitoring is off. Supply --enable to opt in.\n"; return 2; }
        const char* token_value = std::getenv("AGENT_TOKEN");
        if (!token_value || !*token_value) throw std::invalid_argument("Set AGENT_TOKEN before enabling monitoring");
        const std::string token = token_value;
        SetConsoleCtrlHandler(stop, TRUE);
        std::cout << "Monitoring enabled. Press Ctrl+C to stop. Reports are loopback-only.\n";
        std::deque<dayplan_agent::Event> pending;
        auto last = std::chrono::system_clock::now();
        auto activity = dayplan_agent::sample(idle_threshold);
        auto next_report = std::chrono::steady_clock::now() + std::chrono::seconds(report_seconds);
        unsigned failures = 0;
        while (running) {
            // Short sleeps make stop responsive while avoiding busy polling.
            for (int tick = 0; tick < 50 && running; ++tick)
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            if (!running) break;
            const auto current = std::chrono::system_clock::now();
            const auto elapsed = current - last;
            if (elapsed >= std::chrono::seconds(1) && elapsed <= std::chrono::seconds(300)) {
                pending.push_back({dayplan_agent::new_id(), last, current, activity});
                if (pending.size() > 240) {
                    pending.pop_front();
                    std::cerr << "Offline buffer full; oldest activity interval discarded.\n";
                }
            }
            // Clock jumps or suspend gaps are unknown; never fabricate long activity intervals.
            last = current;
            activity = dayplan_agent::sample(idle_threshold);
            if (std::chrono::steady_clock::now() < next_report) continue;
            if (!pending.empty()) {
                const auto count = std::min<std::size_t>(100, pending.size());
                const auto response = client.request(L"POST", L"/api/activity",
                                                       dayplan_agent::batch_json(pending, count), token);
                if (response.ok()) {
                    for (std::size_t i = 0; i < count; ++i) pending.pop_front();
                    failures = 0;
                    std::cout << "Reported " << count << " intervals.\n";
                } else if (response.status == 403) {
                    std::cerr << "Backend monitoring disabled. Sampling stopped.\n"; return 0;
                } else if (response.status == 401) {
                    std::cerr << "Agent token rejected. Sampling stopped.\n"; return 1;
                } else if (response.status >= 400 && response.status < 500) {
                    for (std::size_t i = 0; i < count; ++i) pending.pop_front();
                    std::cerr << "Rejected invalid batch; sampling continues. HTTP " << response.status << "\n";
                } else {
                    ++failures;
                    std::cerr << "Backend unavailable; bounded retry buffer retained.\n";
                }
                if (once) return response.ok() ? 0 : 1;
            }
            const unsigned delay = std::min(120U, report_seconds * (1U << std::min(failures, 2U)));
            next_report = std::chrono::steady_clock::now() + std::chrono::seconds(delay);
        }
        std::cout << "Monitoring stopped. Unsent in-memory activity discarded.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n"; return 1;
    }
}
