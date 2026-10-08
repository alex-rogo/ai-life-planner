#pragma once
#include <chrono>
#include <deque>
#include <cstddef>
#include <cstdint>
#include <string>

namespace dayplan_agent {
using Time = std::chrono::system_clock::time_point;
struct Snapshot {
    std::string app;
    std::string state = "unknown";
    std::uint32_t idle_seconds = 0;
};
struct Event {
    std::string id;
    Time start;
    Time end;
    Snapshot activity;
};
Snapshot sample(std::uint32_t idle_threshold);
std::string new_id();
std::string escape_json(const std::string& value);
std::string event_json(const Event& event);
std::string batch_json(const std::deque<Event>& events, std::size_t count);
std::string utc_timestamp(Time value);
std::uint32_t idle_elapsed(std::uint32_t now, std::uint32_t last);
}
