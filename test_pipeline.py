# Unit tests for STTMeet logic modules
import json
import tempfile
from pathlib import Path

from src.transcript_processor import (
    parse_time_to_seconds,
    format_seconds_to_timestamp,
    adjust_chunk_timestamps,
    deduplicate_overlap,
    extract_speakers,
    apply_speaker_mapping
)
from src.utils import format_duration, estimate_cost_and_tokens
from src.i18n import (
    ALL_MODES,
    DEFAULT_LOCALE,
    LOGIC_COUPLED_LITERALS,
    MINUTES_LANG_BY_UI_LOCALE,
    MINUTES_LANG_DISPLAY,
    TEMPLATE_DISPLAY,
    STRINGS,
    display_minutes_lang,
    display_template_name,
    mode_label,
    normalize_locale,
    translate,
)
from src.session_store import (
    DEFAULT_SETTINGS,
    SCHEMA_VERSION,
    VALID_LANGUAGES,
    VALID_TEMPLATES,
    build_session_payload,
    load_session,
    normalize_settings,
    save_session,
    session_path
)
from src.minutes_generator import (
    TEMPLATES_PROMPTS,
    get_synthesis_prompt,
    get_action_items_prompt,
    parse_minutes_sections,
)
from src.recap_generator import (
    RECAP_PROMPTS,
    get_recap_prompt,
)

def test_time_conversions():
    assert parse_time_to_seconds("01:30") == 90
    assert parse_time_to_seconds("01:00:00") == 3600
    assert format_seconds_to_timestamp(90) == "[01:30]"
    assert format_seconds_to_timestamp(3665) == "[01:01:05]"

def test_adjust_chunk_timestamps():
    sample = "[00:15] Speaker 1: Helo selamat pagi.\n[01:30] Speaker 2: Selamat pagi."
    # Shift by 25 minutes = 1500 seconds
    adjusted = adjust_chunk_timestamps(sample, offset_seconds=1500)
    assert "[25:15]" in adjusted
    assert "[26:30]" in adjusted

def test_speaker_mapping():
    transcript = "[00:01] Speaker 1: Setuju.\n[00:05] Speaker 2: Baiklah."
    mapping = {"Speaker 1": "En. Razak", "Speaker 2": "Pn. Faridah"}
    mapped = apply_speaker_mapping(transcript, mapping)
    assert "En. Razak:" in mapped
    assert "Pn. Faridah:" in mapped
    assert "Speaker 1" not in mapped

def test_deduplicate_overlap():
    prev = "[10:00] Speaker 1: Kita teruskan.\n[10:15] Speaker 2: Baik Tuan."
    curr = "[10:15] Speaker 2: Baik Tuan.\n[10:20] Speaker 1: Agenda seterusnya."
    deduped = deduplicate_overlap(prev, curr)
    assert "[10:20] Speaker 1: Agenda seterusnya." in deduped
    assert deduped.count("Baik Tuan") == 0

def test_cost_estimator():
    res = estimate_cost_and_tokens(3600) # 1 hour
    assert res["estimated_input_tokens"] == 3600 * 32
    assert res["estimated_cost_usd"] > 0
    assert "1h 00m 00s" in res["formatted_duration"]

def _sample_settings():
    return {
        "engine": "☁️ Gemini 3.5 Flash",
        "language": "Bilingual",
        "chunk_minutes": 20,
        "preprocess": False,
        "template": "action_minutes",
    }

def _sample_status():
    return {
        "steps": {"step1": "done", "step2": "done", "step3": "error", "step4": "pending"},
        "chunks": [
            {"index": 0, "status": "done", "error": ""},
            {"index": 1, "status": "error", "error": "quota exceeded"}
        ],
        "progress": 0.6
    }

def test_session_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = session_path(Path(tmp), "abc123")
        assert path.name == "session_abc123.json"

        payload = build_session_payload(
            audio_hash="abc123",
            audio_path="D:/meetings/agm.mp3",
            settings=_sample_settings(),
            status=_sample_status(),
            raw_transcript="[00:01] Speaker 1: Setuju.",
            processed_transcript="[00:01] En. Razak: Setuju.",
            generated_minutes="# Minutes\n...",
            generated_recap="# Executive Meeting Recap\n...",
            generated_actions="# Action Item Register\n...",
            detected_speakers=["Speaker 1"],
            speaker_mapping={"Speaker 1": "En. Razak"}
        )
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["generated_recap"] == "# Executive Meeting Recap\n..."
        assert payload["generated_actions"] == "# Action Item Register\n..."
        assert save_session(payload, path)

        loaded = load_session(path)
        assert loaded is not None
        assert loaded["audio_hash"] == "abc123"
        assert loaded["settings"] == _sample_settings()
        assert loaded["status"]["steps"]["step3"] == "error"
        assert loaded["status"]["chunks"][1]["error"] == "quota exceeded"
        assert loaded["speaker_mapping"] == {"Speaker 1": "En. Razak"}
        assert loaded["processed_transcript"] == "[00:01] En. Razak: Setuju."
        assert loaded["generated_recap"] == "# Executive Meeting Recap\n..."
        assert loaded["generated_actions"] == "# Action Item Register\n..."

def test_session_never_stores_api_key():
    payload = build_session_payload(
        audio_hash="abc123",
        audio_path="D:/meetings/agm.mp3",
        settings=_sample_settings(),
        status=_sample_status()
    )
    serialized = json.dumps(payload)
    assert "GEMINI_API_KEY" not in serialized
    assert "api_key" not in serialized

def test_session_loads_v1_without_settings():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session_legacy.json"
        path.write_text(json.dumps({
            "audio_hash": "legacy",
            "raw_transcript": "old transcript",
            "generated_minutes": "old minutes",
            "detected_speakers": ["Speaker 2"],
            "updated_at": "2026-01-01T00:00:00"
        }), encoding="utf-8")

        loaded = load_session(path)
        assert loaded is not None
        assert loaded["schema_version"] == 1
        assert loaded["settings"] == DEFAULT_SETTINGS
        assert loaded["status"]["steps"]["step1"] == "pending"
        assert loaded["status"]["chunks"] == []
        assert loaded["processed_transcript"] == "old transcript"
        assert loaded["speaker_mapping"] == {}

def test_normalize_settings_rejects_stale_values():
    stale = {
        "engine": "💻 Malaysian-Whisper (Local)",
        "language": "Klingon",
        "chunk_minutes": 5,
        "preprocess": "yes"
    }
    assert normalize_settings(stale) == DEFAULT_SETTINGS
    assert normalize_settings(None) == DEFAULT_SETTINGS

    # Unusable chunk sizes fall back to the default rather than raising
    assert normalize_settings({"chunk_minutes": "banana"})["chunk_minutes"] == DEFAULT_SETTINGS["chunk_minutes"]

def test_load_session_missing_and_corrupt():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_session(Path(tmp) / "session_nope.json") is None

        corrupt = Path(tmp) / "session_bad.json"
        corrupt.write_text("{not valid json", encoding="utf-8")
        assert load_session(corrupt) is None

# ---------------------------------------------------------------------------
# Localization
# ---------------------------------------------------------------------------

def test_every_string_has_english_and_malay():
    for key, entry in STRINGS.items():
        assert "en" in entry and entry["en"], f"{key} missing 'en'"
        assert "ms" in entry and entry["ms"], f"{key} missing 'ms'"

def test_translate_each_mode():
    assert translate("btn.transcribe", "en") == translate("btn.transcribe", "en")
    en = translate("menu.settings", "en")
    ms = translate("menu.settings", "ms")
    both = translate("menu.settings", "both")
    assert en == "Settings"
    assert ms == "Tetapan"
    assert both == "Settings / Tetapan"

def test_translate_explicit_both_overrides_auto_join():
    # Tab captions were Malay-first before localization; that order must survive.
    assert translate("tab.recap", "both") == "Rekap Mesyuarat / Meeting Recap"
    # Entries without an explicit variant are auto-joined English / Bahasa.
    assert "both" not in STRINGS["btn.transcribe"]
    assert translate("btn.transcribe", "both").endswith("Start / Mula")

def test_translate_both_does_not_duplicate_leading_emoji():
    for key, entry in STRINGS.items():
        if "both" in entry:
            continue
        combined = translate(key, "both")
        symbol = entry["en"].split(" ", 1)[0]
        if symbol and not any(ch.isalnum() for ch in symbol):
            assert combined.count(symbol) == 1, f"{key} repeats the {symbol} icon"

def test_translate_missing_key_raises():
    try:
        translate("no.such.key", "en")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown i18n key")

def test_translate_falls_back_to_english_for_unknown_mode():
    assert translate("menu.settings", "klingon") == translate("menu.settings", "en")

def test_translate_formats_placeholders():
    assert translate("status.batch_finished", "en", done=3, total=9) == (
        "Batch finished: 3/9 chunks completed. "
        "Please click '\u21bb Reprocess' on failed chunks."
    )
    assert "3/9" in translate("status.batch_finished", "ms", done=3, total=9)

def test_logic_coupled_literals_are_not_translated():
    """Engine/language/chunk values are parsed or keyed; translating breaks them."""
    for key, entry in STRINGS.items():
        for variant in entry.values():
            for literal in LOGIC_COUPLED_LITERALS:
                assert literal not in variant, f"{key} leaks logic-coupled value {literal!r}"

def test_normalize_locale():
    for mode in ALL_MODES:
        assert normalize_locale(mode) == mode
    assert normalize_locale("klingon") == DEFAULT_LOCALE
    assert normalize_locale(None) == DEFAULT_LOCALE
    assert normalize_locale(7) == DEFAULT_LOCALE

def test_locale_cascades_to_a_valid_minutes_language():
    for locale, expected in MINUTES_LANG_BY_UI_LOCALE.items():
        assert expected in VALID_LANGUAGES, f"{locale} maps to an invalid minutes language"
    assert MINUTES_LANG_BY_UI_LOCALE["en"] == "English"
    assert MINUTES_LANG_BY_UI_LOCALE["ms"] == "Bahasa Melayu"
    assert MINUTES_LANG_BY_UI_LOCALE["both"] == "Bilingual"

def test_minutes_lang_display_map_matches_valid_languages():
    assert set(MINUTES_LANG_DISPLAY) == set(VALID_LANGUAGES)
    for canonical, entry in MINUTES_LANG_DISPLAY.items():
        assert entry["en"] and entry["ms"]

def test_display_minutes_lang_is_display_only():
    # Shows a localized name while the canonical value is untouched.
    assert display_minutes_lang("Bilingual", "ms") == "Dwibahasa"
    assert display_minutes_lang("Bilingual", "en") == "Bilingual"
    # An unmapped value is returned verbatim rather than raising.
    assert display_minutes_lang("Welsh", "ms") == "Welsh"

def test_mode_labels_cover_every_mode():
    for mode in ALL_MODES:
        assert mode_label(mode, "en")
        assert mode_label(mode, "ms")

# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def test_prefs_roundtrip_and_tolerance():
    import src.prefs as prefs_module
    from src.prefs import get_pref, load_prefs, save_pref

    original_dir = prefs_module.PREFS_PATH.parent
    original_path = prefs_module.PREFS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        prefs_module.PREFS_PATH = Path(tmp) / "prefs.json"
        try:
            assert load_prefs() == {}
            assert get_pref("ui_locale", DEFAULT_LOCALE) == DEFAULT_LOCALE

            assert save_pref("ui_locale", "ms") is True
            assert get_pref("ui_locale") == "ms"

            # A second key must not clobber the first.
            assert save_pref("other", 1) is True
            assert get_pref("ui_locale") == "ms"
            assert get_pref("other") == 1

            # Corrupt and non-object files degrade to {} instead of raising.
            prefs_module.PREFS_PATH.write_text("{not json", encoding="utf-8")
            assert load_prefs() == {}
            prefs_module.PREFS_PATH.write_text("[1, 2, 3]", encoding="utf-8")
            assert load_prefs() == {}
        finally:
            prefs_module.PREFS_PATH = original_path
    assert original_dir is not None

def test_template_prompts_and_displays():
    assert set(VALID_TEMPLATES) == set(TEMPLATE_DISPLAY.keys())
    assert set(VALID_TEMPLATES) == set(TEMPLATES_PROMPTS.keys())
    for tmpl in VALID_TEMPLATES:
        assert display_template_name(tmpl, "en")
        assert display_template_name(tmpl, "ms")
        for lang in VALID_LANGUAGES:
            prompt = get_synthesis_prompt(template=tmpl, language=lang)
            assert "{transcript}" in prompt

def test_parse_minutes_sections_for_templates():
    three_col_sample = """# Three-Column Meeting Minutes
**Project:** Alpha

| Item # | Discussion & Deliberation | Action Required & Decision | Responsibility & Deadline |
| :---: | :--- | :--- | :---: |
| 1.0 | Testing line 1 | Fix issue | Lead Due: tomorrow |
"""
    sec = parse_minutes_sections(three_col_sample)
    assert "Testing line 1" in sec["action_items"]
    assert sec["full_text"] == three_col_sample

def test_recap_prompts():
    for lang in VALID_LANGUAGES:
        prompt = get_recap_prompt(language=lang)
        assert "{transcript}" in prompt
        assert "# " in prompt
        assert "Executive" in prompt or "Rekap" in prompt

def test_action_items_prompts():
    for lang in VALID_LANGUAGES:
        prompt = get_action_items_prompt(language=lang)
        assert "{transcript}" in prompt
        assert "# " in prompt
        assert "Action" in prompt or "Tindakan" in prompt

if __name__ == "__main__":
    test_time_conversions()
    test_adjust_chunk_timestamps()
    test_speaker_mapping()
    test_deduplicate_overlap()
    test_cost_estimator()
    test_session_roundtrip()
    test_session_never_stores_api_key()
    test_session_loads_v1_without_settings()
    test_normalize_settings_rejects_stale_values()
    test_load_session_missing_and_corrupt()
    test_every_string_has_english_and_malay()
    test_translate_each_mode()
    test_translate_explicit_both_overrides_auto_join()
    test_translate_both_does_not_duplicate_leading_emoji()
    test_translate_missing_key_raises()
    test_translate_falls_back_to_english_for_unknown_mode()
    test_translate_formats_placeholders()
    test_logic_coupled_literals_are_not_translated()
    test_normalize_locale()
    test_locale_cascades_to_a_valid_minutes_language()
    test_minutes_lang_display_map_matches_valid_languages()
    test_display_minutes_lang_is_display_only()
    test_mode_labels_cover_every_mode()
    test_prefs_roundtrip_and_tolerance()
    test_template_prompts_and_displays()
    test_parse_minutes_sections_for_templates()
    test_recap_prompts()
    test_action_items_prompts()
    print("All unit tests passed successfully!")
