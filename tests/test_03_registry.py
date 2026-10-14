"""Unit test cho 03-production/registry_client.py — không cần server thật.

Registry được nạp từ file thật (`registry.json`) và từ dict in-memory để
kiểm tra các nhánh lỗi (JSON hỏng, thiếu field, server không tồn tại...).
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from .conftest import REPO_ROOT, load_module

registry_client = load_module(
    REPO_ROOT / "03-production" / "registry_client.py", "day26_registry_client"
)
ToolRegistry = registry_client.ToolRegistry
RegistryError = registry_client.RegistryError

REGISTRY_JSON = REPO_ROOT / "03-production" / "registry.json"


@pytest.fixture(scope="module")
def registry():
    return ToolRegistry(REGISTRY_JSON)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Đọc registry
# ─────────────────────────────────────────────────────────────────────────────


def test_loads_real_registry(registry):
    assert "get_weather" in registry.tools
    assert "get_weather_v2" in registry.tools
    assert "weather" in registry.servers
    assert "weather-v2" in registry.servers


def test_missing_file_raises_registry_error(tmp_path):
    with pytest.raises(RegistryError, match="Không tìm thấy registry"):
        ToolRegistry(tmp_path / "khong-ton-tai.json")


def test_malformed_json_raises_registry_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"tools": {  ,,, }', encoding="utf-8")
    with pytest.raises(RegistryError, match="không phải JSON hợp lệ"):
        ToolRegistry(bad)


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ([1, 2, 3], "phải là một JSON object"),
        ({"servers": {}}, "thiếu mục 'tools'"),
        ({"tools": {}}, "thiếu mục 'servers'"),
        ({"tools": [], "servers": {}}, "thiếu mục 'tools'"),
    ],
)
def test_invalid_structure_raises_registry_error(payload, fragment):
    with pytest.raises(RegistryError, match=fragment):
        ToolRegistry.from_dict(payload)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tìm theo tag / keyword
# ─────────────────────────────────────────────────────────────────────────────


def test_search_by_tag(registry):
    results = registry.search(tag="weather")
    assert {r["tool"] for r in results} == {"get_weather", "get_weather_v2"}
    assert all("server" in r and r["server"] for r in results)


def test_search_by_tag_no_match(registry):
    assert registry.search(tag="khong-co-tag-nay") == []


def test_search_by_keyword_matches_description(registry):
    results = registry.search(keyword="forecast")
    assert {r["tool"] for r in results} == {"get_weather_v2"}


def test_search_by_keyword_matches_tool_name_and_tags(registry):
    assert {r["tool"] for r in registry.search(keyword="query_db")} == {"query_db"}
    assert {r["tool"] for r in registry.search(keyword="analytics")} == {"query_db"}


def test_search_is_case_insensitive(registry):
    assert {r["tool"] for r in registry.search(keyword="FORECAST")} == {"get_weather_v2"}


def test_search_tolerates_malformed_entry():
    reg = ToolRegistry.from_dict(
        {
            "tools": {
                "good": {"description": "ok", "tags": ["x"], "server": "s", "version": "1.0.0"},
                "broken": "không phải dict",
                "no_version": {"description": "x", "tags": ["x"], "server": "khong-co"},
            },
            "servers": {"s": {"transport": "stdio"}},
        }
    )
    results = reg.search(tag="x")
    names = {r["tool"] for r in results}
    assert names == {"good", "no_version"}  # entry hỏng bị bỏ qua, không sập
    no_version = next(r for r in results if r["tool"] == "no_version")
    assert no_version["version"] == "0.0.0"
    assert no_version["server_missing"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. best_match — chọn version + ưu tiên không deprecated
# ─────────────────────────────────────────────────────────────────────────────


def test_best_match_prefers_highest_version_without_deprecation(registry):
    best = registry.best_match(tag="weather")
    assert best["tool"] == "get_weather_v2"
    assert best["version"] == "2.0.0"
    assert best["deprecated"] is False


def test_best_match_no_candidates_raises(registry):
    with pytest.raises(RegistryError, match="Không tìm thấy tool"):
        registry.best_match(tag="khong-co-tag-nay")


def test_best_match_falls_back_to_deprecated_when_only_option():
    reg = ToolRegistry.from_dict(
        {
            "tools": {
                "old": {"tags": ["x"], "server": "s", "version": "1.0.0", "deprecated": True}
            },
            "servers": {"s": {}},
        }
    )
    assert reg.best_match(tag="x")["tool"] == "old"


def test_best_match_prefers_non_deprecated_over_newer_deprecated():
    reg = ToolRegistry.from_dict(
        {
            "tools": {
                "new_but_dead": {
                    "tags": ["x"], "server": "s", "version": "9.0.0", "deprecated": True
                },
                "older_but_alive": {
                    "tags": ["x"], "server": "s", "version": "1.0.0", "deprecated": False
                },
            },
            "servers": {"s": {}},
        }
    )
    assert reg.best_match(tag="x")["tool"] == "older_but_alive"


def test_version_comparison_is_semantic_not_string():
    reg = ToolRegistry.from_dict(
        {
            "tools": {
                "v9": {"tags": ["x"], "server": "s", "version": "9.0.0"},
                "v10": {"tags": ["x"], "server": "s", "version": "10.0.0"},
            },
            "servers": {"s": {}},
        }
    )
    # So chuỗi thì "9.0.0" > "10.0.0"; so semantic version thì ngược lại.
    assert reg.best_match(tag="x")["tool"] == "v10"


def test_invalid_version_does_not_crash_best_match():
    reg = ToolRegistry.from_dict(
        {
            "tools": {
                "garbage": {"tags": ["x"], "server": "s", "version": "not-a-version"},
                "good": {"tags": ["x"], "server": "s", "version": "1.0.0"},
            },
            "servers": {"s": {}},
        }
    )
    assert reg.best_match(tag="x")["tool"] == "good"


# ─────────────────────────────────────────────────────────────────────────────
# 4. connect_and_call — xử lý server không tồn tại / transport lạ
# ─────────────────────────────────────────────────────────────────────────────


def test_connect_and_call_missing_server_raises():
    reg = ToolRegistry.from_dict(
        {
            "tools": {"ghost": {"tags": ["g"], "server": "khong-ton-tai", "version": "1.0.0"}},
            "servers": {},
        }
    )
    with pytest.raises(RegistryError, match="không có trong"):
        asyncio.run(registry_client.connect_and_call(reg.best_match(tag="g"), {}))


def test_connect_and_call_unsupported_transport_raises():
    match = {
        "tool": "t",
        "server_name": "s",
        "server": {"transport": "carrier-pigeon"},
    }
    with pytest.raises(RegistryError, match="Transport không được hỗ trợ"):
        asyncio.run(registry_client.connect_and_call(match, {}))


def test_connect_and_call_missing_stdio_script_raises():
    match = {
        "tool": "t",
        "server_name": "s",
        "server": {"transport": "stdio", "command": "python", "args": ["khong-ton-tai.py"]},
    }
    with pytest.raises(RegistryError, match="không tồn tại"):
        asyncio.run(registry_client.connect_and_call(match, {}))


def test_connect_and_call_http_without_token_env_raises(monkeypatch):
    monkeypatch.delenv("DAY26_MISSING_TOKEN", raising=False)
    match = {
        "tool": "t",
        "server_name": "internal",
        "server": {
            "transport": "streamable-http",
            "url": "http://internal:9000/mcp",
            "auth": {"type": "bearer", "token_env": "DAY26_MISSING_TOKEN"},
        },
    }
    with pytest.raises(RegistryError, match="chưa được đặt"):
        asyncio.run(registry_client.connect_and_call(match, {}))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Endpoint minh hoạ (email/db) không được coi là đang hoạt động
# ─────────────────────────────────────────────────────────────────────────────


def test_illustrative_servers_are_declared_but_unreachable(registry):
    assert registry_client.ILLUSTRATIVE_SERVERS <= set(registry.servers)
    assert registry.servers["email-service"]["url"].startswith("http://internal-")
    assert registry.servers["db-gateway"]["url"].startswith("http://internal-")


@pytest.mark.parametrize(("tag", "token_env"), [("email", "EMAIL_MCP_TOKEN"), ("database", "DB_MCP_TOKEN")])
def test_illustrative_endpoints_fail_loudly_not_silently(registry, monkeypatch, tag, token_env):
    """Chọn được tool minh hoạ, nhưng gọi nó PHẢI lỗi rõ ràng — không 'như đang chạy'."""
    monkeypatch.delenv(token_env, raising=False)
    best = registry.best_match(tag=tag)
    assert best["server_name"] in registry_client.ILLUSTRATIVE_SERVERS
    with pytest.raises(RegistryError):
        asyncio.run(registry_client.connect_and_call(best, {}))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Registry thật trỏ tới server thật đang tồn tại trên đĩa
# ─────────────────────────────────────────────────────────────────────────────


def test_registry_stdio_scripts_exist_on_disk(registry):
    for name, server in registry.servers.items():
        if server.get("transport") != "stdio":
            continue
        for arg in server.get("args", []):
            path = (registry_client.REGISTRY_DIR / arg).resolve()
            assert path.is_file(), f"server {name}: script {arg} không tồn tại"


def test_real_registry_weather_entry_is_json_serialisable(registry):
    assert json.dumps(registry.tools["get_weather"], ensure_ascii=False)


def test_module_main_is_not_run_on_import():
    # Nếu main() chạy lúc import, sys.exit sẽ nổ hoặc in rác — chỉ cần import sạch.
    assert callable(registry_client.main)
    assert sys.modules["day26_registry_client"] is registry_client
