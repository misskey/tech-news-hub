from app.prefs import format_feeds, format_keywords, parse_preferences, preferences_from_dict


def _form(**overrides):
    data = {
        "keywords": "Rust:2\n开源",
        "blocked": "招聘\n招聘",
        "languages": "Python, Go",
        "sources": ["github", "rss"],
        "rss_feeds": "InfoQ 中文|https://www.infoq.cn/feed\n!草稿|https://example.com/feed.xml",
        "items_per_digest": "10",
        "digest_hour": "8",
        "digest_minute": "5",
        "timezone": "Asia/Shanghai",
        "digest_window_hours": "36",
        "channels": ["email"],
    }
    data.update(overrides)
    return data


def test_parse_preferences_roundtrip_text():
    prefs, errors = parse_preferences(_form())
    assert errors == []
    assert prefs is not None
    assert [(item.text, item.weight) for item in prefs.keywords] == [("Rust", 2), ("开源", 1)]
    assert prefs.blocked_keywords == ["招聘"]
    assert prefs.languages == ["Python", "Go"]
    assert prefs.rss_feeds[1].enabled is False
    assert prefs.channels["email"] is True
    assert prefs.channels["telegram"] is False
    assert "Rust:2" in format_keywords(prefs)
    assert "开源" in format_keywords(prefs).splitlines()
    assert format_feeds(prefs).splitlines()[1].startswith("!")


def test_parse_preferences_rejects_bad_weight_and_empty_sources():
    prefs, errors = parse_preferences(_form(keywords="AI:nope", sources=[]))
    assert prefs is None
    assert any("权重" in error for error in errors)
    assert any("来源" in error for error in errors)


def test_stored_preferences_ignore_unknown_and_bad_timezone():
    prefs = preferences_from_dict(
        {
            "keywords": [{"text": "LLM", "weight": 99}],
            "enabled_sources": ["nope", "v2ex"],
            "timezone": "Not/AZone",
            "items_per_digest": "8",
        }
    )
    assert prefs.keywords[0].weight == 20
    assert prefs.enabled_sources == ["v2ex"]
    assert prefs.timezone == "Asia/Shanghai"
    assert prefs.items_per_digest == 8
