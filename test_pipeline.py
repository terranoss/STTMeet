# Unit tests for STTMeet logic modules
import json
import tempfile
from datetime import datetime
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
    MONTH_NAMES_MS,
    TEMPLATE_DISPLAY,
    STRINGS,
    display_minutes_lang,
    display_template_name,
    localize_date,
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
    ACTION_ITEMS_PROMPTS,
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
        "language": "English",
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
    assert translate("menu.settings", "en") == "Settings"
    assert translate("menu.settings", "ms") == "Tetapan"

def test_translate_has_no_combined_mode():
    # A bilingual "both" mode used to exist; it is gone from both the locale
    # list and every string entry, so it can never be selected again.
    assert ALL_MODES == ("en", "ms")
    assert "both" not in ALL_MODES
    assert DEFAULT_LOCALE == "ms"
    assert DEFAULT_LOCALE in ALL_MODES
    for key, entry in STRINGS.items():
        assert "both" not in entry, f"{key} still carries a combined-mode variant"
    for key, entry in TEMPLATE_DISPLAY.items():
        assert "both" not in entry, f"{key} still carries a combined-mode variant"

def test_translate_missing_key_raises():
    try:
        translate("no.such.key", "en")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown i18n key")

def test_translate_falls_back_to_english_for_unknown_mode():
    assert translate("menu.settings", "klingon") == translate("menu.settings", "en")
    # A locale written by an older build is no longer valid and must not raise.
    assert translate("menu.settings", "both") == translate("menu.settings", "en")

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
    assert set(MINUTES_LANG_BY_UI_LOCALE) == set(ALL_MODES)
    assert MINUTES_LANG_BY_UI_LOCALE["en"] == "English"
    assert MINUTES_LANG_BY_UI_LOCALE["ms"] == "Bahasa Melayu"

def test_bilingual_language_is_gone_everywhere():
    """No prompt table or validator may still offer bilingual generation."""
    assert "Bilingual" not in VALID_LANGUAGES
    for languages in TEMPLATES_PROMPTS.values():
        assert "Bilingual" not in languages
    assert "Bilingual" not in ACTION_ITEMS_PROMPTS
    assert "Bilingual" not in RECAP_PROMPTS
    assert "Bilingual" not in MINUTES_LANG_DISPLAY
    assert "Bilingual" not in LOGIC_COUPLED_LITERALS

def test_stale_bilingual_session_falls_back_safely():
    """A session saved under the old bilingual mode must still load."""
    settings = normalize_settings({"language": "Bilingual"})
    assert settings["language"] in VALID_LANGUAGES
    assert settings["language"] == DEFAULT_SETTINGS["language"]

def test_minutes_lang_display_map_matches_valid_languages():
    assert set(MINUTES_LANG_DISPLAY) == set(VALID_LANGUAGES)
    for canonical, entry in MINUTES_LANG_DISPLAY.items():
        assert entry["en"] and entry["ms"]

def test_display_minutes_lang_is_display_only():
    # Shows a localized name while the canonical value is untouched.
    assert display_minutes_lang("English", "ms") == "Inggeris"
    assert display_minutes_lang("English", "en") == "English"
    # An unmapped value is returned verbatim rather than raising.
    assert display_minutes_lang("Welsh", "ms") == "Welsh"

def test_normalize_locale_rejects_retired_modes():
    assert normalize_locale("both") == DEFAULT_LOCALE
    assert normalize_locale("Bilingual") == DEFAULT_LOCALE

def test_mode_labels_cover_every_mode():
    for mode in ALL_MODES:
        assert mode_label(mode, "en")
        assert mode_label(mode, "ms")

def test_export_labels_are_localized():
    """
    Exported documents used to carry hardcoded bilingual chrome ("Tarikh /
    Date") no matter the interface language, which is what made them read as
    mixed-language. Every export label must now be single-language.
    """
    keys = [k for k in STRINGS if k.startswith("export.")]
    assert len(keys) >= 13, f"expected the export label set, found {len(keys)}"
    for key in keys:
        en = translate(key, "en")
        ms = translate(key, "ms")
        assert en and ms, f"{key} is empty"
        assert en != ms, f"{key} is identical in both languages; it is not localized"
        # No forced-bilingual "Malay / English" chrome may survive.
        for joined in (f"{ms} / {en}", f"{en} / {ms}"):
            assert joined not in (en, ms), f"{key} still renders as bilingual chrome"

def test_export_titles_interpolate_the_filename():
    for tab in ("transcript", "recap", "actions", "minutes"):
        for locale in ALL_MODES:
            title = translate(f"export.title_{tab}", locale, name="Budget Sync")
            assert "Budget Sync" in title, f"export.title_{tab} dropped the file name"
            assert "{name}" not in title

def test_localize_date_uses_language_months():
    moment = datetime(2026, 3, 9)
    assert localize_date(moment, "en") == "09 March 2026"
    assert localize_date(moment, "ms") == "9 Mac 2026"
    assert localize_date(datetime(2026, 12, 25), "ms") == "25 Disember 2026"
    assert len(MONTH_NAMES_MS) == 12
    # An unknown locale degrades to the English form rather than raising.
    assert localize_date(moment, "klingon") == localize_date(moment, "en")

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
    test_translate_has_no_combined_mode()
    test_translate_missing_key_raises()
    test_translate_falls_back_to_english_for_unknown_mode()
    test_translate_formats_placeholders()
    test_logic_coupled_literals_are_not_translated()
    test_normalize_locale()
    test_normalize_locale_rejects_retired_modes()
    test_locale_cascades_to_a_valid_minutes_language()
    test_bilingual_language_is_gone_everywhere()
    test_stale_bilingual_session_falls_back_safely()
    test_minutes_lang_display_map_matches_valid_languages()
    test_display_minutes_lang_is_display_only()
    test_mode_labels_cover_every_mode()
    test_export_labels_are_localized()
    test_export_titles_interpolate_the_filename()
    test_localize_date_uses_language_months()
    test_prefs_roundtrip_and_tolerance()
    test_template_prompts_and_displays()
    test_parse_minutes_sections_for_templates()
    test_recap_prompts()
    test_action_items_prompts()
    print("All unit tests passed successfully!")
