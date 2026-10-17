# Unit tests for STTMeet logic modules
import ast
import dataclasses
import json
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent

from src.config import (
    API_KEY_URL,
    DOCS_DIR,
    FALLBACK_MODELS,
    MINUTES_FALLBACK_MODELS,
    MINUTES_MODEL_NAME,
    MODEL_NAME,
)

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
    has_key,
    localize_date,
    mode_label,
    normalize_locale,
    translate,
)
from src.ui.docs_viewer import (
    DESCRIPTIVE_DOCS,
    DOC_ORDER,
    discover_documents,
    parse_template_descriptions,
    template_descriptions_markdown,
    _slug,
)
from src.ui.theme import (
    ACCENT_FG,
    ACCENT_HOVER,
    ACCENT_TEXT,
    MUTED_TEXT,
    SIDEBAR_FG,
    TRANSPARENT_HOVER,
    TRANSPARENT_TEXT,
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
    generate_action_items,
    generate_meeting_minutes,
    get_synthesis_prompt,
    get_action_items_prompt,
    parse_minutes_sections,
)
from src.recap_generator import (
    RECAP_PROMPTS,
    get_recap_prompt,
    generate_meeting_recap,
)
from src.gemini_failover import (
    FailoverCall,
    generate_with_failover,
    is_quota_failure,
)
from src.gemini_transcriber import (
    transcribe_audio_chunk,
    upload_and_wait_file,
)
from src.audio_processor import compute_file_hash
from src.cancellation import CancelledError
from src.checkpoint_store import checkpoint_path
from src.pipeline import (
    ENGINE_MODEL_OVERRIDES,
    Phase,
    PipelineSettings,
    engine_for_model,
    model_for_engine,
    run_pipeline,
)


class RecordingObserver:
    """
    An observer that keeps every report the Pipeline run makes.

    The Pipeline run's whole contract with a caller is what it reports, so a
    test that asserts on this list is asserting on the seam, not on internals.
    """

    def __init__(self):
        self.reports = []

    def report(self, report):
        self.reports.append(report)

    def keys(self, phase=None):
        return [r.key for r in self.reports if phase is None or r.phase == phase]

    def steps(self):
        """(step, badge state) for every step-badge report, in order."""
        return [(r.key, r.state) for r in self.reports if r.phase == Phase.STEP]

    def phases(self):
        return [r.phase for r in self.reports]

    def percents(self):
        return [r.percent for r in self.reports if r.percent is not None]


class FakeFilesApi:
    """
    Stand-in for the provider's Files API, where transcription's audio is uploaded.

    Records what was uploaded and deleted so a test can see whether provider
    storage leaked, and can hand back a file that is still PROCESSING so the
    upload's poll-and-wait path runs.
    """

    def __init__(self, processing_polls=0, on_upload=None):
        self._processing_polls = processing_polls
        self._on_upload = on_upload
        self.uploads = []
        self.deleted = []
        self._next_name = 0

    def upload(self, file):
        self._next_name += 1
        name = "files/fake-%d" % self._next_name
        self.uploads.append({"file": file, "name": name})
        if self._on_upload:
            self._on_upload()
        return self._file(name, self._processing_polls > 0)

    def get(self, name):
        self._processing_polls -= 1
        return self._file(name, self._processing_polls > 0)

    def delete(self, name):
        self.deleted.append(name)

    @staticmethod
    def _file(name, processing):
        state = "PROCESSING" if processing else "ACTIVE"
        return SimpleNamespace(name=name, state=SimpleNamespace(name=state))


class FakeGeminiProvider:
    """
    Scripted stand-in for the Gemini client used by the Failover chain.

    Costs no quota and makes no network call. Each model in the script gets a
    list of outcomes consumed one per call: a string comes back as the
    response text, an exception is raised for the caller to deal with, and a
    response object is handed back as-is for a script that needs to shape the
    response itself (an empty transcription, say).
    """

    def __init__(self, script, files=None):
        self._script = {model: list(outcomes) for model, outcomes in script.items()}
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate_content)
        self.files = files if files is not None else FakeFilesApi()

    def _generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcomes = self._script.get(model)
        if not outcomes:
            raise AssertionError("FakeGeminiProvider: unexpected call to model '%s'" % model)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, str):
            return SimpleNamespace(text=outcome, candidates=None)
        return outcome

    def attempts_on(self, model):
        """How many times the Failover chain reached for this model."""
        return sum(1 for call in self.calls if call["model"] == model)


def quota_failure_error():
    """The provider's own wording for a Quota failure."""
    return RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded for this project")


def empty_transcription_response(finish_reason="MAX_TOKENS"):
    """A response the provider answered with nothing usable in it."""
    return SimpleNamespace(
        text="",
        candidates=[SimpleNamespace(content=None, finish_reason=finish_reason)],
    )


def recording_waits(module):
    """
    Context manager that records the backoff a policy asks for instead of
    spending it, since backoff is a boundary of that policy.
    """
    from contextlib import contextmanager

    @contextmanager
    def _recording():
        waits = []
        original = module.cancellable_sleep
        module.cancellable_sleep = lambda cancel_event, seconds, *args: waits.append(seconds) or True
        try:
            yield waits
        finally:
            module.cancellable_sleep = original

    return _recording()

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
    assert translate("menubar.tools", "en") == "Tools"
    assert translate("menubar.tools", "ms") == "Alat"
    assert translate("menubar.settings", "en") == "Settings..."
    assert translate("menubar.settings", "ms") == "Tetapan..."

def test_windows_style_ui_strings_are_complete():
    """Menu bar, toolbar and status bar must all be localized for every locale."""
    keys = [k for k in STRINGS if k.startswith(("menubar.", "toolbar.", "statusbar."))]
    assert keys, "no menu bar / toolbar / status bar strings found"
    for key in keys:
        for locale in ALL_MODES:
            assert translate(key, locale).strip(), f"{key} empty in {locale}"

def test_windows_style_chrome_replaced_the_slide_in_drawer():
    """The hamburger drawer is gone; its obsolete i18n keys must not linger."""
    removed = (
        "menu.settings", "menu.save_session", "menu.docs", "menu.about",
        "menu.open_log_folder", "menu.close_hint", "menu.language_label",
        "menu.section_general", "menu.section_tools",
    )
    for key in removed:
        assert not has_key(key), f"obsolete drawer key still defined: {key}"

def test_toolbar_and_menubar_cover_the_expected_actions():
    from src.ui.app_window import _TOOLBAR_ITEMS
    assert len(_TOOLBAR_ITEMS) == 6
    for key, icon, handler in _TOOLBAR_ITEMS:
        assert icon and not icon.isascii() or icon in ("\u2139\uFE0F",), f"{key} has no glyph"
        assert key.startswith("toolbar.")
        assert handler.startswith("_"), f"{key} handler {handler} is not a method name"
    labels = {k for k, _, _ in _TOOLBAR_ITEMS}
    assert labels == {
        "toolbar.open", "toolbar.start", "toolbar.cancel",
        "toolbar.save", "toolbar.docs", "toolbar.about",
    }

def test_ui_uses_windows_flat_corner_radii():
    """Every window chrome frame/button in the app must be square-cornered."""
    import pathlib
    import re
    ui = pathlib.Path(__file__).resolve().parent / "src" / "ui"
    pattern = re.compile(r"corner_radius\s*=\s*(\d+)")
    offenders = []
    for name in ("app_window.py", "docs_viewer.py", "markdown_view.py"):
        for match in pattern.finditer((ui / name).read_text(encoding="utf-8")):
            if match.group(1) != "0":
                offenders.append(f"{name}: corner_radius={match.group(1)}")
    assert not offenders, "rounded corners remain: " + ", ".join(offenders)

def test_docs_are_bundled_and_discoverable():
    """The in-app Documentation reader reads docs/ from disk, not a web link."""
    assert DOCS_DIR.is_dir(), f"docs folder not found at {DOCS_DIR}"
    docs = discover_documents(DOCS_DIR)
    assert docs, "no documentation files discovered"
    assert docs[0] == "user_guide.md", "user guide must lead the reading order"
    assert "meeting_minute/template_descp.txt" in docs
    for rel_path in DOC_ORDER:
        assert rel_path in docs, f"reading order references a missing file: {rel_path}"
    for rel_path in docs:
        assert (DOCS_DIR / rel_path).is_file()

def test_docs_reader_shows_format_descriptions_not_raw_templates():
    """The raw prompt skeletons stay on disk but must not clutter the sidebar."""
    docs = discover_documents(DOCS_DIR)
    for rel_path in docs:
        assert not rel_path.endswith("_template.md") or rel_path == "executive_meeting_recap_template.md"
    raw_templates = [
        p.name for p in (DOCS_DIR / "meeting_minute").glob("*_template.md")
    ]
    assert raw_templates, "the prompt specs should still exist for developers"
    for name in raw_templates:
        assert f"meeting_minute/{name}" not in docs

def test_template_description_file_parses_into_every_format():
    """The run-on descriptions file must split into one entry per format."""
    raw = (DOCS_DIR / "meeting_minute" / "template_descp.txt").read_text(encoding="utf-8")
    entries = parse_template_descriptions(raw)
    assert len(entries) == len(VALID_TEMPLATES) == 4
    assert [e.number for e in entries] == [1, 2, 3, 4]
    for entry in entries:
        assert entry.name and "Template" not in entry.name
        assert entry.short, f"{entry.name} has no short description"
        assert entry.explanation, f"{entry.name} has no explanation"
        assert len(entry.short) > 40
        assert len(entry.explanation) > 200
        assert "  " not in entry.short and "  " not in entry.explanation

def test_template_descriptions_render_as_markdown_in_both_locales():
    raw = (DOCS_DIR / "meeting_minute" / "template_descp.txt").read_text(encoding="utf-8")
    for locale in ALL_MODES:
        rendered = template_descriptions_markdown(raw, locale)
        assert rendered.startswith("# ")
        assert rendered.count("\n## ") == 4
        assert translate("docs.formats.short", locale) in rendered
        assert translate("docs.formats.explanation", locale) in rendered
        assert "A lean, task-driven record" in rendered
        assert "run-on" not in rendered

def test_template_description_parser_handles_missing_or_empty_input():
    assert parse_template_descriptions("") == []
    assert parse_template_descriptions("no sections here at all") == []
    rendered = template_descriptions_markdown("plain prose only", "en")
    assert "plain prose only" in rendered

def test_docs_menu_item_is_localized_in_every_mode():
    for locale in ALL_MODES:
        assert translate("toolbar.docs", locale).strip()
        assert translate("docs.window.title", locale).strip()
        assert translate("docs.sidebar.title", locale).strip()

def test_every_curated_doc_has_a_localized_title():
    """Each entry in the reader's reading order needs an en/ms sidebar title."""
    for rel_path in discover_documents(DOCS_DIR):
        key = f"docs.doc.{_slug(rel_path)}"
        assert has_key(key), f"missing localized title for {rel_path}"
        for locale in ALL_MODES:
            assert translate(key, locale).strip()

def test_docs_source_line_interpolates_the_path():
    for locale in ALL_MODES:
        rendered = translate("docs.source", locale, path="docs/user_guide.md")
        assert "docs/user_guide.md" in rendered
        assert "{" not in rendered

def test_api_key_link_points_at_google_ai_studio():
    """The Settings field links to the page where users create a Gemini key."""
    assert API_KEY_URL == "https://aistudio.google.com/apikey"
    assert API_KEY_URL.startswith("https://")

def test_api_key_link_strings_are_localized():
    for locale in ALL_MODES:
        assert translate("settings.get_key", locale).strip()
        assert translate("settings.get_key_hint", locale).strip()
        assert translate("status.key_link_opened", locale).strip()
    for locale in ALL_MODES:
        rendered = translate("msg.key_link_failed", locale, url=API_KEY_URL)
        assert API_KEY_URL in rendered
        assert "{" not in rendered

def test_settings_help_no_longer_hardcodes_the_key_url():
    """The raw URL now lives on the clickable link, not duplicated in prose."""
    for locale in ALL_MODES:
        assert "aistudio.google.com" not in translate("settings.help", locale)
        assert translate("settings.help", locale).strip()

# ---------------------------------------------------------------------------
# Theme contrast
# ---------------------------------------------------------------------------

def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

def _contrast_ratio(fg: str, bg: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(fg), _relative_luminance(bg)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)

def test_theme_pairs_meet_wcag_aa_contrast():
    """Transparent widgets need explicit (light, dark) text colours.

    CustomTkinter's default button text (#DCE4EE) is tuned for filled buttons
    and drops to ~1.07:1 on the light sidebar, making the labels invisible.
    """
    pairs = [
        ("transparent button", TRANSPARENT_TEXT, SIDEBAR_FG),
        ("transparent button hover", TRANSPARENT_TEXT, TRANSPARENT_HOVER),
        ("active document", ACCENT_TEXT, ACCENT_FG),
        ("active document hover", ACCENT_TEXT, ACCENT_HOVER),
        ("sidebar heading", MUTED_TEXT, SIDEBAR_FG),
    ]
    for name, fg, bg in pairs:
        assert len(fg) == 2 and len(bg) == 2, f"{name} is not a (light, dark) pair"
        for mode, index in (("light", 0), ("dark", 1)):
            ratio = _contrast_ratio(fg[index], bg[index])
            assert ratio >= 4.5, f"{name} in {mode} mode is {ratio:.2f}:1"

def test_docs_sidebar_widgets_use_explicit_theme_colors():
    """The documentation sidebar must never fall back to CTk's washed-out default."""
    from src.ui import docs_viewer
    assert docs_viewer.TRANSPARENT_TEXT is TRANSPARENT_TEXT
    assert docs_viewer.ACCENT_TEXT is ACCENT_TEXT
    assert docs_viewer.SIDEBAR_FG is SIDEBAR_FG

def test_translate_has_no_combined_mode():
    # A bilingual "both" mode used to exist; it is gone from both the locale
    # list and every string entry, so it can never be selected again.
    assert ALL_MODES == ("en", "ms")
    assert "both" not in ALL_MODES
    assert DEFAULT_LOCALE == "en"
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

def test_every_literal_translation_key_resolves():
    # translate() raises on a missing key rather than falling back, which is
    # only a guarantee if callers stay inside it. Walk every literal key passed
    # to _t()/translate() across src/ and assert each one resolves in every
    # locale. Parsed rather than grepped so the check survives either quote
    # style and f-strings, and so failures name a line.
    #
    # Only literal arguments are checked. Twenty-odd call sites build their key
    # at runtime (toolbar tips via str.replace, docs titles via f-string slug),
    # and those are covered by the has_key assertions elsewhere in this file.
    checked = 0
    for path in sorted(Path("src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in ("t", "_t", "translate") or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            checked += 1
            for locale in ALL_MODES:
                try:
                    translate(first.value, locale)
                except KeyError:
                    raise AssertionError(
                        f"{path}:{node.lineno} translates unresolvable key "
                        f"{first.value!r} (locale {locale!r})"
                    )
    # Guard the test itself: if the walk ever stops finding call sites, it is
    # no longer checking anything and would pass vacuously.
    assert checked > 200, f"only {checked} literal translation calls found; walk is broken"

def test_translate_falls_back_to_english_for_unknown_mode():
    assert translate("menubar.tools", "klingon") == translate("menubar.tools", "en")
    # A locale written by an older build is no longer valid and must not raise.
    assert translate("menubar.tools", "both") == translate("menubar.tools", "en")

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

def test_weak_model_diarization_policy():
    # Helper policy simulation matching AppWindow._is_diarization_supported
    def is_diarization_supported(chunk_mins: int, engine_choice: str) -> bool:
        if chunk_mins > 0:
            return False
        if "Flash Lite" in str(engine_choice) or "lite" in str(engine_choice).lower():
            return False
        return True

    # 1. Chunked audio must never diarize
    assert is_diarization_supported(25, "☁️ Gemini 3.8 Flash") is False
    assert is_diarization_supported(15, "⚡ Gemini Cloud (Auto-Failover)") is False

    # 2. No chunking with Flash Lite must NOT diarize
    assert is_diarization_supported(0, "☁️ Gemini 3.5 Flash Lite") is False
    assert is_diarization_supported(0, "gemini-3.5-flash-lite") is False

    # 3. No chunking with capable models MUST diarize
    assert is_diarization_supported(0, "☁️ Gemini 3.8 Flash") is True
    assert is_diarization_supported(0, "☁️ Gemini 3.5 Flash") is True
    assert is_diarization_supported(0, "⚡ Gemini Cloud (Auto-Failover)") is True

    # 4. Verify i18n keys exist
    assert has_key("msg.speaker_mapping_weak_model")
    assert has_key("settings.chunk_note")

def test_quota_failure_skips_retries_and_fails_over_to_the_next_model():
    provider = FakeGeminiProvider({
        "model-a": [quota_failure_error()],
        "model-b": ["# Recap from model-b"],
    })
    call = FailoverCall(
        description="recap synthesis",
        label="recap",
        contents=["transcript"],
        models=["model-a", "model-b"],
        max_retries=3,
        backoff_step=0,
        temperature=0.2,
        final_error="no model left in the chain",
    )

    result = generate_with_failover(provider, call)

    assert result == "# Recap from model-b"
    # A Quota failure ends this model's retry sweep at once, so model-a is
    # reached for exactly once despite max_retries being 3.
    assert provider.attempts_on("model-a") == 1
    assert provider.attempts_on("model-b") == 1


def test_transient_error_retries_with_backoff_then_fails_over():
    provider = FakeGeminiProvider({
        "model-a": [
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
        ],
        "model-b": ["# Recap from model-b"],
    })
    messages = []
    call = FailoverCall(
        description="recap synthesis",
        label="recap",
        contents=["transcript"],
        models=["model-a", "model-b"],
        max_retries=3,
        backoff_step=0,
        temperature=0.2,
        final_error="no model left in the chain",
        progress_callback=messages.append,
    )

    result = generate_with_failover(provider, call)

    assert result == "# Recap from model-b"
    # Three transient failures spend the retry count for model-a before the
    # chain moves on; the backoff in between is reported at attempt * step.
    assert provider.attempts_on("model-a") == 3
    assert provider.attempts_on("model-b") == 1
    assert "Server busy. Retrying in 0s (Attempt 2/3)..." in messages
    assert "Server busy. Retrying in 0s (Attempt 3/3)..." in messages


def test_success_ends_the_failover_chain_without_touching_later_models():
    provider = FakeGeminiProvider({
        "model-a": ["# Recap from model-a"],
        "model-b": ["# Recap nobody asked for"],
    })
    call = FailoverCall(
        description="recap synthesis",
        label="recap",
        contents=["transcript"],
        models=["model-a", "model-b"],
        backoff_step=0,
        temperature=0.2,
    )

    assert generate_with_failover(provider, call) == "# Recap from model-a"
    assert provider.attempts_on("model-b") == 0


def test_exhausted_failover_chain_raises_the_calls_final_error():
    provider = FakeGeminiProvider({
        "model-a": [quota_failure_error()],
        "model-b": [quota_failure_error()],
    })
    call = FailoverCall(
        description="recap synthesis",
        label="recap",
        contents=["transcript"],
        models=["model-a", "model-b"],
        backoff_step=0,
        temperature=0.2,
        final_error="Both models are out of allowance today.",
    )

    try:
        generate_with_failover(provider, call)
    except RuntimeError as error:
        assert str(error) == "Both models are out of allowance today."
    else:
        raise AssertionError("an exhausted Failover chain must raise RuntimeError")


def test_quota_failure_predicate_separates_quota_from_transient_errors():
    assert is_quota_failure(RuntimeError("429 Too Many Requests")) is True
    assert is_quota_failure(RuntimeError("RESOURCE_EXHAUSTED")) is True
    assert is_quota_failure(RuntimeError("Quota exceeded for the day")) is True
    assert is_quota_failure(RuntimeError("503 UNAVAILABLE: overloaded")) is False


def recap_failover_chain(lead_model):
    """The Failover chain the Recap path walks when the Engine pins a model."""
    return [lead_model] + [m for m in MINUTES_FALLBACK_MODELS if m != lead_model]


def test_recap_path_keeps_its_backoff_step_and_temperature():
    """Divergence from the other call sites is deliberate, so it stays pinned."""
    from src import gemini_failover

    waits = []
    original_sleep = gemini_failover.cancellable_sleep
    # Backoff is a boundary of this policy, so record the waits it asks for
    # instead of spending them.
    gemini_failover.cancellable_sleep = lambda cancel_event, seconds: waits.append(seconds) or True
    try:
        provider = FakeGeminiProvider({
            "model-a": [RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE"), "# Recap from model-a"],
        })
        recap = generate_meeting_recap(
            provider, "a long transcript", language="English", model_override="model-a"
        )
    finally:
        gemini_failover.cancellable_sleep = original_sleep

    assert recap == "# Recap from model-a"
    # Today's Recap path backs off by attempt * 5 seconds...
    assert waits == [5, 10]
    # ...and pins the text-generation temperature.
    assert provider.calls[0]["config"]["temperature"] == 0.2


def test_recap_quota_failure_message_is_unchanged():
    chain = recap_failover_chain("model-a")
    provider = FakeGeminiProvider({model: [quota_failure_error()] for model in chain})

    try:
        generate_meeting_recap(provider, "a long transcript", language="English", model_override="model-a")
    except RuntimeError as error:
        assert str(error) == (
            "All available Gemini models (%s) exceeded daily free quotas or failed.\n"
            "Please check your Google AI Studio quota limits or retry tomorrow." % ", ".join(chain)
        )
    else:
        raise AssertionError("a Quota failure on every model must raise RuntimeError")


def test_recap_path_delegates_its_failure_policy_to_the_shared_module():
    """The Quota failure predicate is written once, and Recap uses that one."""
    source = (Path(__file__).parent / "src" / "recap_generator.py").read_text(encoding="utf-8")

    assert "RESOURCE_EXHAUSTED" not in source
    assert "quota exceeded" not in source
    assert "generate_with_failover" in source
    assert "is_quota_failure" not in source


def test_failover_policy_module_owns_the_policy_and_nothing_else():
    """The policy is a sibling of cancellation, not a client of the generators."""
    source = (Path(__file__).parent / "src" / "gemini_failover.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    allowed = {"dataclasses", "typing", "cancellation", "config", "logger"}
    assert imported <= allowed, "unexpected imports: %s" % sorted(imported - allowed)


def test_failover_description_carries_no_provider_types():
    """A caller can describe its request in plain data, with no provider objects."""
    for field in FailoverCall.__dataclass_fields__.values():
        annotation = str(field.type)
        assert "genai" not in annotation and "types." not in annotation, annotation


def test_resource_lifecycle_brackets_one_models_whole_retry_sweep():
    provider = FakeGeminiProvider({
        "model-a": [RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE")],
        "model-b": ["# Recap from model-b"],
    })
    prepared = []
    released = []

    def prepare(model):
        prepared.append(model)
        return f"upload for {model}"

    def cleanup(resource):
        released.append(resource)

    call = FailoverCall(
        description="chunk transcription",
        label="transcription",
        contents=["audio", "prompt"],
        models=["model-a", "model-b"],
        max_retries=2,
        backoff_step=0,
        temperature=0.1,
        prepare=prepare,
        cleanup=cleanup,
    )

    assert generate_with_failover(provider, call) == "# Recap from model-b"
    # Each model uploads before its retry sweep and releases afterwards, so a
    # retry reuses the upload instead of paying for it again.
    assert prepared == ["model-a", "model-b"]
    assert released == ["upload for model-a", "upload for model-b"]


def test_resource_is_released_even_when_a_models_sweep_fails():
    provider = FakeGeminiProvider({"model-a": [RuntimeError("503 UNAVAILABLE")]})
    released = []

    call = FailoverCall(
        description="chunk transcription",
        label="transcription",
        contents=["audio", "prompt"],
        models=["model-a"],
        max_retries=1,
        backoff_step=0,
        prepare=lambda model: "upload",
        cleanup=released.append,
    )

    try:
        generate_with_failover(provider, call)
    except RuntimeError:
        pass
    else:
        raise AssertionError("an exhausted Failover chain must raise RuntimeError")
    assert released == ["upload"]


def transcription_failover_chain(lead_model):
    """The Failover chain the transcription path walks when the Engine pins a model."""
    return [lead_model] + [m for m in FALLBACK_MODELS if m != lead_model]


def test_transcribed_chunk_is_uploaded_once_and_the_upload_is_deleted():
    """One upload brackets that model's whole retry sweep, and is deleted after."""
    provider = FakeGeminiProvider({"model-a": ["[00:01] Speaker 1: Setuju."]})

    transcript = transcribe_audio_chunk(provider, "chunk_0.wav", model_override="model-a")

    assert transcript == "[00:01] Speaker 1: Setuju."
    assert provider.attempts_on("model-a") == 1
    assert [upload["file"] for upload in provider.files.uploads] == ["chunk_0.wav"]
    assert provider.files.deleted == ["files/fake-1"]


def test_transcription_reuses_one_upload_across_a_models_retries():
    """A retry reaches for the same upload rather than paying for it again."""
    from src import gemini_failover

    provider = FakeGeminiProvider({
        "model-a": [
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            "[00:01] Speaker 1: Setuju.",
        ],
    })
    with recording_waits(gemini_failover) as waits:
        transcript = transcribe_audio_chunk(
            provider, "chunk_0.wav", max_retries=3, model_override="model-a"
        )

    assert transcript == "[00:01] Speaker 1: Setuju."
    assert provider.attempts_on("model-a") == 3
    # Three generations, but the chunk was uploaded to the provider only once.
    assert len(provider.files.uploads) == 1
    assert provider.files.deleted == ["files/fake-1"]
    # Transcription backs off by attempt * 4 seconds, unlike the text paths'
    # attempt * 5.
    assert waits == [4, 8]


def test_transcription_fails_over_to_a_later_model_after_a_transient_error():
    """One flaky model does not lose the chunk, and each model pays for its own upload."""
    from src import gemini_failover

    next_model = FALLBACK_MODELS[0]
    provider = FakeGeminiProvider({
        "model-a": [RuntimeError("503 UNAVAILABLE")] * 2,
        next_model: ["[00:02] Speaker 2: Baik."],
    })
    with recording_waits(gemini_failover):
        transcript = transcribe_audio_chunk(
            provider, "chunk_0.wav", max_retries=2, model_override="model-a"
        )

    assert transcript == "[00:02] Speaker 2: Baik."
    assert provider.attempts_on("model-a") == 2
    assert provider.attempts_on(next_model) == 1
    # Each model uploads before its own retry sweep, so model-a's upload is
    # gone before the next model's begins, and both are deleted.
    assert [upload["name"] for upload in provider.files.uploads] == ["files/fake-1", "files/fake-2"]
    assert provider.files.deleted == ["files/fake-1", "files/fake-2"]


def test_transcription_deletes_the_uploaded_audio_when_the_run_is_cancelled():
    from src import gemini_failover

    cancel_event = threading.Event()
    provider = FakeGeminiProvider({"model-a": [RuntimeError("503 UNAVAILABLE")]})
    original_sleep = gemini_failover.cancellable_sleep

    # The user cancels while the retry backoff is running.
    def cancel_during_backoff(event, seconds, *args):
        cancel_event.set()
        return True

    gemini_failover.cancellable_sleep = cancel_during_backoff
    try:
        transcribe_audio_chunk(
            provider, "chunk_0.wav", model_override="model-a", cancel_event=cancel_event
        )
    except CancelledError:
        pass
    else:
        raise AssertionError("a cancelled transcription must raise CancelledError")
    finally:
        gemini_failover.cancellable_sleep = original_sleep

    assert provider.files.uploads != []
    assert provider.files.deleted == ["files/fake-1"]


def test_cancellation_during_an_upload_leaves_no_file_in_provider_storage():
    """An abandoned upload is released even though it never reaches a caller."""
    cancel_event = threading.Event()
    # The provider cancels the run the moment it accepts the upload, and the
    # file is still processing when it is asked for again.
    provider = FakeGeminiProvider(
        {"model-a": ["[00:01] Speaker 1: Setuju."]},
        files=FakeFilesApi(processing_polls=3, on_upload=cancel_event.set),
    )

    try:
        transcribe_audio_chunk(
            provider, "chunk_0.wav", model_override="model-a", cancel_event=cancel_event
        )
    except CancelledError:
        pass
    else:
        raise AssertionError("a cancelled transcription must raise CancelledError")

    assert [upload["file"] for upload in provider.files.uploads] == ["chunk_0.wav"]
    assert provider.files.deleted == ["files/fake-1"]
    # Nothing was ever transcribed, so nothing reached the provider's models.
    assert provider.attempts_on("model-a") == 0


def test_transcription_diarization_still_turns_off_for_weak_models():
    """Diarization policy for weak models is out of scope, so it is unchanged."""
    tail = "[00:58] Speaker 1: Jadi kita sambung."

    provider = FakeGeminiProvider({"model-a": ["[00:01] Speaker 1: Setuju."]})
    transcribe_audio_chunk(
        provider, "chunk_0.wav", previous_tail_transcript=tail, model_override="model-a"
    )
    prompt = provider.calls[0]["contents"][1]

    assert "Speaker Diarization" in prompt
    assert "[MM:SS] Speaker X: <Spoken content>" in prompt
    # Tail context carries across the chunk seam.
    assert tail in prompt

    provider = FakeGeminiProvider({"gemini-3.5-flash-lite": ["[00:01] Setuju."]})
    transcribe_audio_chunk(
        provider,
        "chunk_0.wav",
        previous_tail_transcript=tail,
        model_override="gemini-3.5-flash-lite",
    )
    weak_prompt = provider.calls[0]["contents"][1]

    assert "Clean Transcription" in weak_prompt
    assert "Speaker Diarization" not in weak_prompt
    assert "SPEAKER CONTINUITY GUIDANCE" not in weak_prompt


def test_transcription_reports_its_own_progress_wording():
    """The transcription progress a user reads today is kept as it was."""
    from src import gemini_failover

    next_model = FALLBACK_MODELS[0]
    provider = FakeGeminiProvider({
        "model-a": [
            RuntimeError("503 UNAVAILABLE"),
            RuntimeError("503 UNAVAILABLE"),
            RuntimeError("503 UNAVAILABLE"),
        ],
        next_model: ["[00:03] Speaker 1: Jumpa."],
    })
    messages = []
    with recording_waits(gemini_failover):
        transcribe_audio_chunk(
            provider,
            "chunk_0.wav",
            progress_callback=messages.append,
            max_retries=3,
            model_override="model-a",
        )

    assert "Uploading chunk to Google Files API..." in messages
    assert "Calling Gemini model-a (Attempt 1/3)..." in messages
    assert "Server notice. Retrying in 4s..." in messages
    assert "Calling Gemini %s (Attempt 1/3)..." % next_model in messages
    # The text-generation wording must not leak into the transcription path.
    assert not any(message.startswith("Server busy") for message in messages)


def test_transcription_keeps_its_own_quota_failure_message():
    chain = transcription_failover_chain("model-a")
    provider = FakeGeminiProvider({model: [quota_failure_error()] for model in chain})

    try:
        transcribe_audio_chunk(provider, "chunk_0.wav", model_override="model-a")
    except RuntimeError as error:
        assert str(error) == (
            "All available Gemini models (%s) exceeded daily free quotas or failed.\n"
            "Please try again later once your Gemini quota resets, or use a different API key."
            % ", ".join(chain)
        )
    else:
        raise AssertionError("a Quota failure on every model must raise RuntimeError")


def minutes_failover_chain(lead_model):
    """The Failover chain the Minutes path walks when the Engine pins a model."""
    return [lead_model] + [m for m in MINUTES_FALLBACK_MODELS if m != lead_model]


def test_minutes_path_fails_over_to_the_next_model_on_a_quota_failure():
    """Minutes delegates Quota failure handling, so it behaves as Recap does."""
    chain = minutes_failover_chain("model-a")
    lead, fallback = chain[0], chain[1]
    provider = FakeGeminiProvider({
        lead: [quota_failure_error()],
        fallback: ["# Minutes from the fallback model"],
    })

    minutes = generate_meeting_minutes(
        provider, "a long transcript", language="English", model_override=lead
    )

    assert minutes == "# Minutes from the fallback model"
    # A Quota failure ends this model's retry sweep at once, exactly as it does
    # for the Recap path.
    assert provider.attempts_on(lead) == 1
    assert provider.attempts_on(fallback) == 1


def test_minutes_path_retries_a_transient_error_with_backoff_then_answers():
    """A transient fault spends the retry count, then Minutes answers."""
    chain = minutes_failover_chain("model-a")
    lead = chain[0]
    provider = FakeGeminiProvider({
        lead: [
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            "# Minutes from model-a",
        ],
    })
    messages = []
    waits = []
    from src import gemini_failover

    original_sleep = gemini_failover.cancellable_sleep
    # Backoff is a boundary of the shared policy, so record the waits it asks
    # for instead of spending them.
    gemini_failover.cancellable_sleep = lambda cancel_event, seconds: waits.append(seconds) or True
    try:
        minutes = generate_meeting_minutes(
            provider, "a long transcript", language="English", model_override=lead,
            progress_callback=messages.append,
        )
    finally:
        gemini_failover.cancellable_sleep = original_sleep

    assert minutes == "# Minutes from model-a"
    # Today's Minutes path backs off by attempt * 5 seconds...
    assert waits == [5, 10]
    # ...and pins the text-generation temperature.
    assert provider.calls[0]["config"]["temperature"] == 0.2
    # The progress wording a user reads is unchanged.
    assert "Server busy. Retrying in 5s (Attempt 2/3)..." in messages
    assert "Server busy. Retrying in 10s (Attempt 3/3)..." in messages
    assert "Generating minutes with %s (Attempt 1/3)..." % lead in messages


def test_minutes_quota_failure_message_is_unchanged():
    chain = minutes_failover_chain("model-a")
    provider = FakeGeminiProvider({model: [quota_failure_error()] for model in chain})

    try:
        generate_meeting_minutes(
            provider, "a long transcript", language="English", model_override="model-a"
        )
    except RuntimeError as error:
        assert str(error) == (
            "All available Gemini models (%s) exceeded daily free quotas or failed.\n"
            "Please check your Google AI Studio quota limits or retry tomorrow." % ", ".join(chain)
        )
    else:
        raise AssertionError("a Quota failure on every model must raise RuntimeError")


def test_transcription_retries_an_empty_transcription_on_its_own_backoff():
    """An empty transcription is not a chunk: it retries, then moves down the chain."""
    from src import gemini_failover

    next_model = FALLBACK_MODELS[0]
    provider = FakeGeminiProvider({
        "model-a": [empty_transcription_response(), empty_transcription_response()],
        next_model: ["[00:04] Speaker 1: Lagi."],
    })
    with recording_waits(gemini_failover) as waits:
        transcript = transcribe_audio_chunk(
            provider, "chunk_0.wav", max_retries=2, model_override="model-a"
        )

    assert transcript == "[00:04] Speaker 1: Lagi."
    assert provider.attempts_on("model-a") == 2
    # An empty transcription backs off by attempt * 3 seconds, which is not the
    # step a transient error backs off by.
    assert waits == [3]


def test_a_chunk_that_only_ever_comes_back_empty_is_not_a_transcript():
    """Silence is never banked as the chunk's transcript."""
    from src import gemini_failover

    chain = transcription_failover_chain("model-a")
    provider = FakeGeminiProvider({
        model: [empty_transcription_response()] for model in chain
    })
    with recording_waits(gemini_failover):
        try:
            transcribe_audio_chunk(provider, "chunk_0.wav", max_retries=1, model_override="model-a")
        except RuntimeError as error:
            assert str(error).startswith("All available Gemini models (")
        else:
            raise AssertionError("an empty transcription must not pass for a transcript")


def test_transcription_path_delegates_its_failure_policy_to_the_shared_module():
    """The Quota failure predicate is written once, and transcription uses that one."""
    source = (Path(__file__).parent / "src" / "gemini_transcriber.py").read_text(encoding="utf-8")

    assert "RESOURCE_EXHAUSTED" not in source
    assert "quota exceeded" not in source
    assert "generate_with_failover" in source
    assert "is_quota_failure" not in source


def test_upload_lifecycle_is_an_input_to_the_policy_not_part_of_it():
    """The policy brackets whatever a caller prepares; it never learns what it is."""
    source = (Path(__file__).parent / "src" / "gemini_failover.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "gemini_transcriber" not in imported

    # The policy only ever reaches for the caller's resource through its
    # prepare/cleanup callbacks: it names no provider file API of its own.
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "files" not in attributes

def test_minutes_and_action_items_delegate_their_failure_policy_to_the_shared_module():
    """The Quota failure predicate is written once, and both paths use that one."""
    source = (Path(__file__).parent / "src" / "minutes_generator.py").read_text(encoding="utf-8")

    assert "RESOURCE_EXHAUSTED" not in source
    assert "quota exceeded" not in source
    assert "is_quota_failure" not in source
    # Both generation paths hand their request to the shared policy.
    assert source.count("generate_with_failover(client") == 2


def test_action_items_path_fails_over_to_the_next_model_on_a_quota_failure():
    """Action items delegates Quota failure handling, so it behaves as Recap does."""
    chain = minutes_failover_chain("model-a")
    lead, fallback = chain[0], chain[1]
    provider = FakeGeminiProvider({
        lead: [quota_failure_error()],
        fallback: ["| 1 | Draft the brief | Deen | 2026-01-01 | Open |"],
    })

    register = generate_action_items(
        provider, "a long transcript", language="English", model_override=lead
    )

    assert register == "| 1 | Draft the brief | Deen | 2026-01-01 | Open |"
    # A Quota failure ends this model's retry sweep at once, exactly as it does
    # for the Recap path.
    assert provider.attempts_on(lead) == 1
    assert provider.attempts_on(fallback) == 1


def test_action_items_path_retries_a_transient_error_with_backoff_then_answers():
    """A transient fault spends the retry count, then Action items answers."""
    chain = minutes_failover_chain("model-a")
    lead = chain[0]
    provider = FakeGeminiProvider({
        lead: [
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            RuntimeError("503 UNAVAILABLE: the model is overloaded"),
            "| 1 | Draft the brief | Deen | 2026-01-01 | Open |",
        ],
    })
    messages = []
    waits = []
    from src import gemini_failover

    original_sleep = gemini_failover.cancellable_sleep
    gemini_failover.cancellable_sleep = lambda cancel_event, seconds: waits.append(seconds) or True
    try:
        register = generate_action_items(
            provider, "a long transcript", language="English", model_override=lead,
            progress_callback=messages.append,
        )
    finally:
        gemini_failover.cancellable_sleep = original_sleep

    assert register == "| 1 | Draft the brief | Deen | 2026-01-01 | Open |"
    # Today's Action items path backs off by attempt * 5 seconds...
    assert waits == [5, 10]
    # ...and pins the text-generation temperature.
    assert provider.calls[0]["config"]["temperature"] == 0.2
    # The progress wording a user reads is unchanged.
    assert "Server busy. Retrying in 5s (Attempt 2/3)..." in messages
    assert "Generating action items with %s (Attempt 1/3)..." % lead in messages


def test_action_items_quota_failure_message_is_unchanged():
    chain = minutes_failover_chain("model-a")
    provider = FakeGeminiProvider({model: [quota_failure_error()] for model in chain})

    try:
        generate_action_items(
            provider, "a long transcript", language="English", model_override="model-a"
        )
    except RuntimeError as error:
        assert str(error) == (
            "All available Gemini models (%s) exceeded daily free quotas or failed.\n"
            "Please check your Google AI Studio quota limits or retry tomorrow." % ", ".join(chain)
        )
    else:
        raise AssertionError("a Quota failure on every model must raise RuntimeError")


def test_minutes_keep_their_own_failover_chain_apart_from_transcription():
    """The Minutes Failover chain is not the transcription Failover chain."""
    from src.config import FALLBACK_MODELS, MINUTES_FALLBACK_MODELS, MINUTES_MODEL_NAME, MODEL_NAME

    assert MINUTES_MODEL_NAME != MODEL_NAME
    assert MINUTES_FALLBACK_MODELS != FALLBACK_MODELS


def test_tooltip_text_provider():
    from src.ui.tooltip import Tooltip

    class DummyWidget:
        def bind(self, *args, **kwargs): pass
        def winfo_exists(self): return True

    dummy = DummyWidget()
    t1 = Tooltip(dummy, "Static info")
    assert t1._get_text() == "Static info"

    current_val = "Hello"
    t2 = Tooltip(dummy, lambda: current_val)
    assert t2._get_text() == "Hello"
    current_val = "Updated"
    assert t2._get_text() == "Updated"

def test_audio_setup_wizard_integration():
    """Wizard strings and methods must be properly localized and callable."""
    assert has_key("wizard.title")
    assert has_key("wizard.heading")
    assert has_key("wizard.start")
    assert has_key("wizard.apply")
    assert has_key("wizard.cancel")
    assert has_key("file.wizard")
    assert has_key("menubar.wizard")
    for key in ("wizard.title", "wizard.heading", "wizard.start", "wizard.apply", "file.wizard"):
        for locale in ALL_MODES:
            assert translate(key, locale).strip()
    from src.ui.app_window import STTMeetApp
    assert hasattr(STTMeetApp, "_open_audio_setup_wizard")
    assert hasattr(STTMeetApp, "_open_audio_setup_wizard_manual")

def pipeline_run_provider(transcript_text, minutes_text, transcription_lead=None, minutes_lead=None):
    """
    A fake Gemini client serving one whole-Audio-file transcription and one Minutes
    synthesis.

    The two leads default to what each Failover chain leads with on its own; a pinned
    Engine makes them the same model, which then answers both calls in order. Any other
    model being reached for is a test failure, because nothing here should fail over.
    """
    transcription_lead = transcription_lead or MODEL_NAME
    minutes_lead = minutes_lead or MINUTES_MODEL_NAME
    script = {transcription_lead: [transcript_text]}
    if minutes_lead == transcription_lead:
        script[minutes_lead].append(minutes_text)
    else:
        script[minutes_lead] = [minutes_text]
    return FakeGeminiProvider(script)


def a_recording_audio_file(directory):
    """A stand-in Audio file on disk: enough bytes to be hashed."""
    path = Path(directory) / "meeting.mp3"
    path.write_bytes(b"not really an mp3, but it is a file with a hash")
    return path


def test_a_whole_pipeline_run_reports_what_it_is_doing_and_yields_transcript_and_minutes():
    """
    A Pipeline run is reachable without a window: an Audio file with Chunking
    off goes in, a Transcript and Minutes come out, and the only thing the run
    says to its caller is reports.
    """
    transcript = "[00:01] Speaker 1: Setuju.\n[00:04] Speaker 2: Setuju, kita teruskan."
    minutes = "# Minit\n\n## Keputusan\nSetuju."

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        settings = PipelineSettings(audio_path=str(audio), api_key="key", preprocess=False, cache_dir=tmp)
        observer = RecordingObserver()

        result = run_pipeline(
            settings, observer, client=pipeline_run_provider(transcript, minutes)
        )

    assert result.transcript == transcript
    assert result.minutes == minutes

    # Per-Chunk status arrives on one channel, distinguished by phase. With
    # Chunking off the whole recording is the one Chunk, at index 0.
    assert observer.keys(Phase.CHUNK) == ["chunk.working", "chunk.done"]
    assert [r.index for r in observer.reports if r.phase == Phase.CHUNK] == [0, 0]

    # All four steps are badged through the same channel.
    assert observer.steps() == [
        ("step1", "working"), ("step1", "done"),
        ("step2", "working"), ("step2", "done"),
        ("step3", "working"), ("step3", "done"),
        ("step4", "working"), ("step4", "done"),
    ]


def test_a_minutes_failure_never_costs_the_transcript():
    """The Transcript is worth more than the Minutes, and says so without raising."""
    transcript = "[00:01] Speaker 1: Setuju."

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        settings = PipelineSettings(audio_path=str(audio), api_key="key", preprocess=False, cache_dir=tmp)
        observer = RecordingObserver()
        # Every model of the Minutes chain refuses for the day.
        script = {model: [quota_failure_error()] for model in MINUTES_FALLBACK_MODELS}
        script[MODEL_NAME] = [transcript]
        provider = FakeGeminiProvider(script)

        result = run_pipeline(settings, observer, client=provider)

    assert result.transcript == transcript
    assert result.minutes == ""
    assert result.minutes_error
    assert "status.minutes_failed" in observer.keys()
    assert observer.steps()[-1] == ("step4", "error")
    # The Chunk still finished, and the Transcript was assembled from it.
    assert observer.keys(Phase.CHUNK) == ["chunk.working", "chunk.done"]


def test_the_run_honours_the_engine_and_the_processing_language():
    """The Engine leads both Failover chains; the Processing language reaches the prompt."""
    transcript = "[00:01] Speaker 1: Setuju."
    minutes = "# Action Minutes of Meeting"
    pinned = "☁️ Gemini 3.8 Flash"
    provider = pipeline_run_provider(transcript, minutes, "gemini-3.8-flash", "gemini-3.8-flash")

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            engine=pinned, language="English",
            cache_dir=tmp,
        )
        observer = RecordingObserver()

        result = run_pipeline(settings, observer, client=provider)

    assert result.engine == "gemini-3.8-flash"
    # Both calls went to the model the Engine pinned, and to no other model.
    assert [call["model"] for call in provider.calls] == ["gemini-3.8-flash"] * 2
    # The run said which Engine it is using, rather than the caller having to know.
    engine_report = [r for r in observer.reports if r.key == "status.step3_engine"][0]
    assert engine_report.args["engine"] == "gemini-3.8-flash"
    # The Minutes were asked for in the Processing language.
    minutes_prompt = provider.calls[1]["contents"][0]
    assert "in English" in minutes_prompt
    assert "Bahasa Melayu" not in minutes_prompt


def test_every_report_a_run_makes_renders_from_its_key_and_args():
    """
    Reports carry a translation key and formatting arguments, never a finished
    sentence: every one of them renders from the English table using only its own args.
    """
    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        settings = PipelineSettings(audio_path=str(audio), api_key="key", preprocess=False, cache_dir=tmp)
        observer = RecordingObserver()

        run_pipeline(settings, observer,
                     client=pipeline_run_provider("[00:01] Speaker 1: Setuju.", "# Minit"))

    reported = [r for r in observer.reports if r.phase in (Phase.STATUS, Phase.PROGRESS)]
    assert reported
    for report in reported:
        assert has_key(report.key), report.key
        rendered = translate(report.key, "en", **report.args)
        assert rendered.strip()
        # The formatting args are the sentence's variable parts; a run that handed over
        # a finished sentence instead would have nowhere left to put them.
        assert "{" not in rendered


def test_a_run_defaults_to_what_the_desktop_app_persists():
    """Both entry points start from the same settings, read once rather than copied."""
    defaults = PipelineSettings(audio_path="anything.wav")

    assert defaults.engine == DEFAULT_SETTINGS["engine"]
    assert defaults.language == DEFAULT_SETTINGS["language"]
    assert defaults.template == DEFAULT_SETTINGS["template"]
    assert defaults.preprocess == DEFAULT_SETTINGS["preprocess"]
    # Chunking is the one deliberate divergence: this run transcribes the whole
    # recording as a single Chunk, so 0 rather than the desktop's default.
    assert defaults.chunk_minutes == 0


def test_a_cancelled_run_transcribes_nothing():
    """A Pipeline run handed a set cancel event reports nothing and calls nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        settings = PipelineSettings(audio_path=str(audio), api_key="key", preprocess=False, cache_dir=tmp)
        observer = RecordingObserver()
        provider = pipeline_run_provider("[00:01] Speaker 1: Setuju.", "# Minit")
        already_cancelled = threading.Event()
        already_cancelled.set()

        try:
            run_pipeline(settings, observer, cancel_event=already_cancelled, client=provider)
            raise AssertionError("a cancelled Pipeline run should not return a result")
        except CancelledError:
            pass

    assert provider.calls == []
    assert observer.reports == []


def test_preprocessing_decides_which_audio_is_transcribed_and_reports_its_own_progress():
    """The whole recording is preprocessed first, and what Preprocessing says is reported."""
    from src import pipeline as pipeline_module

    transcript = "[00:01] Speaker 1: Setuju."
    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        preprocessed = Path(tmp) / "preprocessed_meeting.mp3"
        preprocessed.write_bytes(b"16kHz mono, allegedly")

        def fake_preprocess(input_path, progress_callback=None, **kwargs):
            assert input_path == str(audio)
            for message in ("Converting audio (converting to 16kHz mono MP3)...",
                            "Found existing optimized preprocessed audio."):
                if progress_callback:
                    progress_callback(message)
            return str(preprocessed)

        original = pipeline_module.preprocess_audio
        pipeline_module.preprocess_audio = fake_preprocess
        try:
            settings = PipelineSettings(audio_path=str(audio), api_key="key", preprocess=True, cache_dir=tmp)
            observer = RecordingObserver()
            provider = pipeline_run_provider(transcript, "# Minit")
            run_pipeline(settings, observer, client=provider)
        finally:
            pipeline_module.preprocess_audio = original

        uploaded = provider.files.uploads[0]["file"]

    assert uploaded == str(preprocessed)
    detail_reports = [r for r in observer.reports if r.key == "status.step1_detail"]
    assert [r.args["detail"] for r in detail_reports] == [
        "Converting audio (converting to 16kHz mono MP3)...",
        "Found existing optimized preprocessed audio.",
    ]
    # Preprocessing was not skipped, and the run badged it so.
    assert ("step1", "working") in observer.steps()
    step1_done = [r for r in observer.reports
                  if r.phase == Phase.STEP and r.key == "step1" and r.state == "done"][0]
    assert step1_done.args["skipped"] is False


def test_importing_the_pipeline_run_pulls_in_no_ui_toolkit():
    """
    Importing the Pipeline run on its own must not drag in a UI toolkit, the desktop
    package, or the translation table: a headless caller has none of them and needs none
    of them. Checked in a fresh interpreter so this suite's own imports cannot mask it.
    """
    script = (
        "import sys\n"
        "import src.pipeline\n"
        "ui = sorted(m for m in sys.modules\n"
        "           if m.split('.')[0] in ('tkinter', '_tkinter', 'customtkinter', 'darkdetect')\n"
        "           or m.startswith('src.ui'))\n"
        "table = sorted(m for m in sys.modules if m.startswith('src.i18n'))\n"
        "print(ui)\nprint(table)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    ui_modules, translation_table = proc.stdout.strip().splitlines()[-2:]
    assert ui_modules == "[]", ui_modules
    assert translation_table == "[]", translation_table


def test_the_pipeline_run_module_reaches_no_ui_package_and_no_translation_table():
    """The rule behind the previous test, read off the module's own imports."""
    tree = ast.parse((REPO_ROOT / "src" / "pipeline.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    assert not [name for name in imported if "ui" in name.split(".")]
    assert not [name for name in imported if "tkinter" in name]
    assert not [name for name in imported if name.endswith("i18n")]


def test_the_pipeline_run_takes_its_settings_as_a_plain_data_object():
    """
    Settings are data, and nothing else: no widget handle, no live value to read off
    another thread. That is what closes the thread-safety leak structurally.
    """
    assert dataclasses.is_dataclass(PipelineSettings)
    fields = {f.name for f in dataclasses.fields(PipelineSettings)}
    # A settings object carries values and nothing an observer could read state from.
    assert not [
        name for name in dir(PipelineSettings)
        if not name.startswith("_") and name not in fields
    ]
    defaults = PipelineSettings(audio_path="anything.wav")
    for name in fields - {"audio_path"}:
        value = getattr(defaults, name)
        assert isinstance(value, (str, bool, int)), (name, value)


def test_a_headless_run_writes_the_transcript_and_the_minutes_to_disk():
    """The whole point of the second adapter: an Audio file in, two documents out."""
    from src.headless import EXIT_OK, run_headless

    transcript = "[00:01] Speaker 1: Setuju.\n[00:04] Speaker 2: Kita teruskan."
    minutes = "# Minit Tindakan Mesyuarat\n\n## Tindakan\n- En. Razak: susun draf."

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        outcome = run_headless(
            str(audio), output_dir=tmp, preprocess=False, cache_dir=tmp,
            client=pipeline_run_provider(transcript, minutes),
        )
        written = sorted(p.name for p in Path(tmp).glob("*.md"))
        assert outcome.exit_code == EXIT_OK
        assert written == ["meeting_minutes.md", "meeting_transcript.md"]
        assert Path(outcome.transcript_path).read_text(encoding="utf-8") == transcript
        assert Path(outcome.minutes_path).read_text(encoding="utf-8") == minutes


def test_a_headless_run_keeps_the_transcript_when_minutes_fail():
    from src.headless import EXIT_NO_MINUTES, run_headless

    transcript = "[00:01] Speaker 1: Setuju."
    script = {model: [quota_failure_error()] for model in MINUTES_FALLBACK_MODELS}
    script[MODEL_NAME] = [transcript]

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        outcome = run_headless(
            str(audio), output_dir=tmp, preprocess=False, cache_dir=tmp,
            client=FakeGeminiProvider(script),
        )
        written = sorted(p.name for p in Path(tmp).glob("*.md"))

    assert outcome.exit_code == EXIT_NO_MINUTES
    assert outcome.minutes_path is None
    assert written == ["meeting_transcript.md"]


def test_a_console_report_prints_its_key_and_arguments_without_a_translation_table():
    """A headless reader gets the key and its args even when no wording is available."""
    import io

    from src.headless import ConsoleObserver
    from src.pipeline import PipelineReport

    stream = io.StringIO()
    observer = ConsoleObserver(stream)
    observer.report(PipelineReport(phase=Phase.STATUS, key="status.step3_chunk",
                                   args={"index": 1, "total": 1}))
    observer.report(PipelineReport(phase=Phase.CHUNK, key="chunk.done", index=0))
    observer.report(PipelineReport(phase=Phase.STATUS, key="status.no.such.key"))

    printed = stream.getvalue()
    assert "[status] status.step3_chunk index=1 total=1" in printed
    assert "[chunk] chunk.done (#0)" in printed
    assert "status.no.such.key" in printed


def test_the_headless_flag_on_the_entry_point_configures_the_run():
    """--headless on the existing entry point reaches the headless adapter."""
    import src.headless as headless_module
    import main as entry_point

    captured = {}

    def fake_run_headless(audio_path, **kwargs):
        captured["audio_path"] = audio_path
        captured.update(kwargs)
        return headless_module.HeadlessOutcome(exit_code=0, result=None)

    original = headless_module.run_headless
    headless_module.run_headless = fake_run_headless
    try:
        exit_code = entry_point.main([
            "--headless", "meeting.mp3",
            "--output-dir", "out",
            "--engine", "gemini-3.5-flash-lite",
            "--language", "English",
            "--template", "board_governance",
            "--no-preprocess",
        ])
    finally:
        headless_module.run_headless = original

    assert exit_code == 0
    assert captured["audio_path"] == "meeting.mp3"
    assert captured["output_dir"] == "out"
    assert captured["engine"] == "☁️ Gemini 3.5 Flash Lite"
    assert captured["language"] == "English"
    assert captured["template"] == "board_governance"
    assert captured["preprocess"] is False


def test_the_engine_and_its_model_name_name_the_same_choice_both_ways():
    for choice, model in ENGINE_MODEL_OVERRIDES.items():
        assert model_for_engine(choice) == model
        assert engine_for_model(model) == choice
    # Auto-failover pins nothing, and is spelled out rather than left blank.
    assert model_for_engine(DEFAULT_SETTINGS["engine"]) is None
    assert model_for_engine("") is None


def a_chunking_plan(directory, count, chunk_minutes=25):
    """
    The Chunks Chunking would produce for a long Audio file: one slice file each, with
    the timestamps and offset the run needs to stitch them back together.

    Built rather than derived, because finding silence boundaries needs a real decoder.
    What is under test is what a Pipeline run does with a Chunk plan, not where the
    boundaries happened to fall.
    """
    plan = []
    for index in range(count):
        slice_path = Path(directory) / ("chunk_%03d.mp3" % index)
        slice_path.write_bytes(b"16kHz mono slice %d" % index)
        plan.append({
            "chunk_index": index,
            "file_path": str(slice_path),
            "start_ms": index * chunk_minutes * 60 * 1000,
            "end_ms": (index + 1) * chunk_minutes * 60 * 1000,
            "duration_ms": chunk_minutes * 60 * 1000,
            "offset_seconds": float(index * chunk_minutes * 60),
        })
    return plan


@contextmanager
def chunking_that_splits_into(plan):
    """Stand in for Chunking with a plan, so a run can be driven without a decoder."""
    from src import pipeline as pipeline_module

    def split(audio_path, **kwargs):
        split.calls += 1
        split.audio_paths.append(audio_path)
        return list(plan)

    split.calls = 0
    split.audio_paths = []
    original = pipeline_module.split_audio_into_chunks
    pipeline_module.split_audio_into_chunks = split
    try:
        yield split
    finally:
        pipeline_module.split_audio_into_chunks = original


@contextmanager
def chunking_that_must_not_run():
    """Fail loudly if a run splits an Audio file it was told not to split."""
    from src import pipeline as pipeline_module

    def refuse(*args, **kwargs):
        raise AssertionError("Chunking is off; the recording must not be sliced.")

    original = pipeline_module.split_audio_into_chunks
    pipeline_module.split_audio_into_chunks = refuse
    try:
        yield
    finally:
        pipeline_module.split_audio_into_chunks = original


def chunked_pipeline_provider(chunk_transcripts, minutes_text, lead=None):
    """
    A fake Gemini client serving one transcription per Chunk, then one Minutes synthesis.

    A pinned Engine makes both calls land on the same model, which then answers them in
    the order the run makes them: every Chunk in turn, then the Minutes.
    """
    lead = lead or MODEL_NAME
    script = {lead: list(chunk_transcripts)}
    if MINUTES_MODEL_NAME == lead:
        script[lead].append(minutes_text)
    else:
        script[MINUTES_MODEL_NAME] = [minutes_text]
    return FakeGeminiProvider(script)


def test_chunking_splits_a_long_audio_file_and_every_chunk_is_transcribed():
    """Chunking on: the Audio file becomes many Chunks, and each is sent to the service."""
    # Each Chunk's timestamps are local to that Chunk, as the service returns them.
    chunk_texts = [
        "[00:05] Speaker 1: Agenda pertama.",
        "[00:03] Speaker 2: Agenda kedua.",
        "[00:07] Speaker 1: Kita tutup mesyuarat.",
    ]
    minutes = "# Minit\n\n## Keputusan\nTutup mesyuarat."

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        provider = chunked_pipeline_provider(chunk_texts, minutes)
        observer = RecordingObserver()
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp,
        )

        with chunking_that_splits_into(plan) as chunking:
            result = run_pipeline(settings, observer, client=provider)

    assert chunking.calls == 1
    assert result.chunks == 3
    assert result.completed_chunks == 3
    # Each Chunk was uploaded as its own slice, in order, rather than the whole file.
    assert [upload["file"] for upload in provider.files.uploads] == [
        chunk["file_path"] for chunk in plan
    ]
    # The Transcript is every Chunk's text, in order.
    # The Transcript is every Chunk's text, in order, each Chunk's clock shifted onto
    # the meeting's: Chunk 2 starts 25 minutes in, Chunk 3 an hour in.
    assert result.transcript == "\n\n".join([
        "[00:05] Speaker 1: Agenda pertama.",
        "[25:03] Speaker 2: Agenda kedua.",
        "[50:07] Speaker 1: Kita tutup mesyuarat.",
    ])
    assert [(r.index, r.key) for r in observer.reports if r.phase == Phase.CHUNK] == [
        (0, "chunk.working"), (0, "chunk.done"),
        (1, "chunk.working"), (1, "chunk.done"),
        (2, "chunk.working"), (2, "chunk.done"),
    ]
    assert ("step2", "done") in observer.steps()


def test_chunking_is_skipped_entirely_when_it_is_off():
    """Chunking off: the recording is never sliced, and is the one Chunk end to end."""
    transcript = "[00:01] Speaker 1: Setuju.\n[00:04] Speaker 2: Kita teruskan."

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        provider = pipeline_run_provider(transcript, "# Minit")
        observer = RecordingObserver()
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=0, cache_dir=tmp,
        )

        with chunking_that_must_not_run():
            result = run_pipeline(settings, observer, client=provider)

        uploaded = [upload["file"] for upload in provider.files.uploads]

    assert result.chunks == 1
    assert result.completed_chunks == 1
    assert result.transcript == transcript
    # The whole Audio file is what reaches the service, uncut.
    assert uploaded == [str(audio)]
    assert "status.step2_off" in observer.keys()
    step2_done = [r for r in observer.reports
                  if r.phase == Phase.STEP and r.key == "step2" and r.state == "done"][0]
    assert step2_done.args == {"skipped": True, "chunk_count": 1}


class CheckpointWatchingObserver(RecordingObserver):
    """
    An observer that reads the Checkpoint off disk at each Chunk report.

    The run's promise is that the Checkpoint is written before it moves on to the next
    Chunk, so the only honest way to see that is to look at the file when the run says
    the Chunk is done rather than after the run has finished.
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.banked_at_chunk_done = []

    def report(self, report):
        super().report(report)
        if report.phase == Phase.CHUNK and report.key == "chunk.done":
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.banked_at_chunk_done.append(sorted(payload["chunks"]))


def test_a_checkpoint_records_each_chunk_as_soon_as_it_is_done():
    """The Checkpoint is written after every Chunk, not once at the end of the run."""
    chunk_texts = ["[00:05] Speaker 1: Satu.", "[00:05] Speaker 2: Dua."]

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 2)
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp,
        )
        observer = CheckpointWatchingObserver(
            checkpoint_path(tmp, compute_file_hash(str(audio)))
        )

        with chunking_that_splits_into(plan):
            run_pipeline(settings, observer,
                         client=chunked_pipeline_provider(chunk_texts, "# Minit"))

        saved = json.loads(observer.path.read_text(encoding="utf-8"))

    # Each Chunk was on disk by the time the run reported it done, so an interruption
    # after Chunk 1 still has Chunk 0 banked.
    assert observer.banked_at_chunk_done == [["0"], ["0", "1"]]
    assert saved["chunk_minutes"] == 25
    # What is banked is the Chunk's final text, on the meeting's clock.
    assert saved["chunks"]["0"] == "[00:05] Speaker 1: Satu."
    assert saved["chunks"]["1"] == "[25:05] Speaker 2: Dua."


def test_an_interrupted_run_resumes_and_does_not_re_pay_for_chunks_already_done():
    """
    The acceptance case: a long meeting interrupted partway, restarted, picks up where it
    stopped rather than transcribing from the beginning.
    """
    chunk_texts = [
        "[00:05] Speaker 1: Agenda pertama.",
        "[00:03] Speaker 2: Agenda kedua.",
        "[00:07] Speaker 1: Kita tutup mesyuarat.",
    ]
    minutes = "# Minit\n\n## Keputusan\nTutup mesyuarat."
    # One model pinned, so the whole run -- every Chunk and the Minutes -- is answered by
    # one scripted list, and reaching for any other model is a test failure.
    lead = MODEL_NAME
    pinned = "☁️ Gemini 3.8 Flash"

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp, engine=pinned,
        )

        # First run: the first two Chunks transcribe, the third is refused by every model
        # of the chain -- which is what an exhausted day looks like.
        first_provider = FakeGeminiProvider(
            dict(
                {lead: chunk_texts[:2] + [quota_failure_error(), minutes]},
                **{model: [quota_failure_error()] for model in FALLBACK_MODELS if model != lead},
            )
        )
        first_observer = RecordingObserver()
        with chunking_that_splits_into(plan):
            first = run_pipeline(settings, first_observer, client=first_provider)

        # Second run: a fresh client whose script covers only what is left to do -- the
        # third Chunk and the Minutes. Anything more would be a re-paid Chunk, so nothing
        # else is scripted: reaching for an unscripted call is itself the failure.
        second_provider = FakeGeminiProvider({
            lead: [chunk_texts[2], minutes],
        })
        second_observer = RecordingObserver()
        with chunking_that_splits_into(plan):
            second = run_pipeline(settings, second_observer, client=second_provider)

        first_uploads = [upload["file"] for upload in first_provider.files.uploads]
        second_uploads = [upload["file"] for upload in second_provider.files.uploads]

    # The first run banked the two Chunks it managed and said the step was incomplete.
    assert first.completed_chunks == 2
    assert first.chunks == 3
    assert ("step3", "error") in first_observer.steps()
    assert (2, "chunk.error") in [
        (r.index, r.key) for r in first_observer.reports if r.phase == Phase.CHUNK
    ]

    # The resumed run paid for only the Chunk that was missing, and got the whole
    # meeting back -- assembled from three Chunks, the first two read from the Checkpoint.
    assert second.chunks == 3
    assert second.completed_chunks == 3
    assert second_uploads == [plan[2]["file_path"]]
    assert first_uploads[:2] == [plan[0]["file_path"], plan[1]["file_path"]]
    # Every Chunk's text is in the Transcript exactly once, in the order it was spoken.
    assert second.transcript.count("Agenda pertama.") == 1
    assert second.transcript.count("Agenda kedua.") == 1
    assert second.transcript.count("Kita tutup mesyuarat.") == 1
    assert second.transcript.index("Agenda pertama.") < second.transcript.index("Agenda kedua.")
    assert second.transcript.index("Agenda kedua.") < second.transcript.index("Kita tutup mesyuarat.")

    # The resumed run said which Chunks came from the Checkpoint rather than the service.
    chunk_reports = [(r.index, r.key) for r in second_observer.reports
                     if r.phase == Phase.CHUNK]
    assert chunk_reports == [
        (0, "chunk.cached"), (1, "chunk.cached"),
        (2, "chunk.working"), (2, "chunk.done"),
    ]


def test_tail_context_carries_the_previous_chunk_across_the_seam():
    """
    Each Chunk is sent the tail of the Chunk before it, so speaker names and phrasing
    stay continuous where the Chunking boundary fell mid-sentence.
    """
    chunk_texts = [
        "[00:05] Speaker 1: En. Razak akan bentangkan laporan.\n"
        "[00:09] Speaker 2: Pn. Faridah, sila prepare bahagian wandangian.",
        "[00:07] Speaker 1: Terima kasih.",
    ]

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        provider = chunked_pipeline_provider(chunk_texts, "# Minit")
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp,
        )
        with chunking_that_splits_into(plan):
            result = run_pipeline(settings, RecordingObserver(), client=provider)

        # What the service was actually sent, prompt for prompt.
        prompts = [call["contents"][1] for call in provider.calls[:3]]
        transcript = result.transcript

    # The first Chunk has nothing before it, so it carries no Tail context.
    assert "SPEAKER CONTINUITY GUIDANCE" not in prompts[0]
    # The second was sent the first Chunk's closing line, and the third the second's --
    # as they stand in the Transcript, on the meeting's clock rather than the Chunk's.
    assert transcript.splitlines()[1] in prompts[1]
    assert transcript.splitlines()[3] in prompts[2]
    # So the third Chunk was not sent the first Chunk's tail as well.
    assert transcript.splitlines()[1] not in prompts[2]


def test_overlap_is_removed_from_the_seam_between_two_chunks():
    """
    Chunking cuts at silence but keeps five seconds of audio either side, so the opening
    of a Chunk repeats the close of the one before. That Overlap is removed, not kept
    twice in the Transcript.
    """
    repeated = "[00:03] Speaker 2: Baik Tuan, saya sambung."
    chunk_texts = [
        "[00:40] Speaker 1: Kita teruskan.\n" + repeated,
        repeated + "\n[00:12] Speaker 1: Agenda seterusnya.",
        "[00:05] Speaker 2: Baiknya.",
    ]

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp,
        )
        with chunking_that_splits_into(plan):
            result = run_pipeline(settings, RecordingObserver(),
                                  client=chunked_pipeline_provider(chunk_texts, "# Minit"))

    # The repeated line is in the Transcript once, and the Chunk after the seam keeps
    # only what was new in it.
    assert result.transcript.count("Baik Tuan, saya sambung.") == 1
    assert "Agenda seterusnya." in result.transcript
    assert "Baiknya." in result.transcript


def test_a_cancelled_run_stops_between_chunks_and_leaves_the_rest_resumable():
    """
    A cancel mid-meeting ends the run promptly -- the Chunk after the cancel is never
    sent -- and what was already transcribed stays in the Checkpoint as done, so the
    remaining Chunks are resumed rather than failed.
    """
    chunk_texts = [
        "[00:05] Speaker 1: Agenda pertama.",
        "[00:03] Speaker 2: Agenda kedua.",
        "[00:07] Speaker 1: Kita tutup mesyuarat.",
    ]
    cancel_event = threading.Event()

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        settings = PipelineSettings(
            audio_path=str(audio), api_key="key", preprocess=False,
            chunk_minutes=25, cache_dir=tmp,
        )

        # The user cancels once the second Chunk has been transcribed.
        class CancellingObserver(RecordingObserver):
            def report(self, report):
                super().report(report)
                if report.phase == Phase.CHUNK and report.key == "chunk.done" and report.index == 1:
                    cancel_event.set()

        observer = CancellingObserver()
        provider = chunked_pipeline_provider(chunk_texts, "# Minit")
        with chunking_that_splits_into(plan):
            try:
                run_pipeline(settings, observer, cancel_event=cancel_event, client=provider)
                raise AssertionError("a cancelled run must not return a result")
            except CancelledError:
                pass

        uploaded = [upload["file"] for upload in provider.files.uploads]
        checkpoint = json.loads(
            checkpoint_path(tmp, compute_file_hash(str(audio))).read_text(encoding="utf-8")
        )

    # It stopped between Chunks: the third was never sent, and no Minutes were asked for.
    assert uploaded == [plan[0]["file_path"], plan[1]["file_path"]]
    assert provider.attempts_on(MINUTES_MODEL_NAME) == 0

    # The two finished Chunks are banked as done. The third is absent -- neither done
    # nor errored -- which is what "resumable rather than failed" means on disk.
    assert sorted(checkpoint["chunks"]) == ["0", "1"]
    assert "error" not in json.dumps(checkpoint)


def test_ctrl_c_cancels_a_headless_run_and_leaves_it_resumable():
    """
    Ctrl+C is how a terminal user stops a run. It must end the run the same way the
    Cancel button ends it on the desktop -- through the cancel event, not by killing the
    process -- so the Chunks already transcribed survive to be resumed.
    """
    import signal

    from src.headless import EXIT_CANCELLED, run_headless

    chunk_texts = [
        "[00:05] Speaker 1: Agenda pertama.",
        "[00:03] Speaker 2: Agenda kedua.",
        "[00:07] Speaker 1: Kita tutup mesyuarat.",
    ]

    class InterruptingObserver:
        """Raises SIGINT at the terminal, as Ctrl+C would, once Chunk 1 is banked."""

        def __init__(self):
            self.transcript_path = None

        def report(self, report):
            if (report.phase == Phase.CHUNK and report.key == "chunk.done"
                    and report.index == 1):
                # raise_signal, not os.kill: on Windows os.kill(SIGINT) terminates the
                # process outright, which is exactly the behaviour being ruled out here.
                signal.raise_signal(signal.SIGINT)

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        # Only the first two Chunks are scripted: if the interrupt did not take, the run
        # would reach for a third call this provider has no answer for.
        provider = chunked_pipeline_provider(chunk_texts[:2], "# Minit")
        original_split = None
        from src import pipeline as pipeline_module
        original_split = pipeline_module.split_audio_into_chunks
        pipeline_module.split_audio_into_chunks = lambda audio_path, **kw: list(plan)
        try:
            outcome = run_headless(
                str(audio), output_dir=tmp, preprocess=False, chunk_minutes=25,
                cache_dir=tmp, client=provider, observer=InterruptingObserver(),
            )
        finally:
            pipeline_module.split_audio_into_chunks = original_split

        written = sorted(p.name for p in Path(tmp).glob("*.md"))
        checkpoint = json.loads(
            checkpoint_path(tmp, compute_file_hash(str(audio))).read_text(encoding="utf-8")
        )

    # Ctrl+C did not kill the process: it came back through the adapter's own door code.
    assert outcome.exit_code == EXIT_CANCELLED
    # Nothing half-finished was written, and the finished Chunks are still banked.
    assert written == []
    assert sorted(checkpoint["chunks"]) == ["0", "1"]


def test_a_headless_run_that_failed_partway_is_resumed_by_running_it_again():
    """
    The whole acceptance case end to end, through the seam a terminal reader actually
    uses: a long meeting fails partway, and running the same command again produces the
    complete Transcript without re-paying for the Chunks already transcribed.
    """
    from src.headless import EXIT_OK, run_headless

    chunk_texts = [
        "[00:05] Speaker 1: Agenda pertama.",
        "[00:03] Speaker 2: Agenda kedua.",
        "[00:07] Speaker 1: Kita tutup mesyuarat.",
    ]
    minutes = "# Minit\n\n## Keputusan\nTutup mesyuarat."
    lead = MODEL_NAME

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        plan = a_chunking_plan(tmp, 3)
        with chunking_that_splits_into(plan):
            # First attempt: the third Chunk is refused by the whole chain.
            first = FakeGeminiProvider({
                lead: chunk_texts[:2] + [quota_failure_error(), minutes],
            })
            failed = run_headless(
                str(audio), output_dir=tmp, preprocess=False, chunk_minutes=25,
                cache_dir=tmp, client=first,
            )
            after_first = sorted(p.name for p in Path(tmp).glob("*.md"))

            # Second attempt, same command: a client with answers for the rest only.
            second = FakeGeminiProvider({lead: [chunk_texts[2], minutes]})
            resumed = run_headless(
                str(audio), output_dir=tmp, preprocess=False, chunk_minutes=25,
                cache_dir=tmp, client=second,
            )
            written = sorted(p.name for p in Path(tmp).glob("*.md"))
            transcript = Path(resumed.transcript_path).read_text(encoding="utf-8")

    # The failed run wrote nothing, even though it had two Chunks' worth of text.
    assert failed.exit_code != EXIT_OK
    assert failed.transcript_path is None
    assert after_first == []

    # The resumed run wrote both documents, and paid for only the Chunk that was missing.
    assert resumed.exit_code == EXIT_OK
    assert written == ["meeting_minutes.md", "meeting_transcript.md"]
    assert [upload["file"] for upload in second.files.uploads] == [plan[2]["file_path"]]
    # The Transcript is the whole meeting, in order, each line once.
    for phrase in ("Agenda pertama.", "Agenda kedua.", "Kita tutup mesyuarat."):
        assert transcript.count(phrase) == 1
    assert transcript.index("Agenda pertama.") < transcript.index("Kita tutup mesyuarat.")


def test_every_test_in_this_suite_is_registered_to_run():
    """
    main() calls tests from a hardcoded list, so a test that is defined but not
    registered never runs and never fails. This suite has been bitten by that before,
    so the list is checked against the file rather than trusted.
    """
    tree = ast.parse((REPO_ROOT / "test_pipeline.py").read_text(encoding="utf-8"))
    defined = {
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    entry_point = [node for node in tree.body if isinstance(node, ast.If)]
    registered = {
        node.func.id
        for block in entry_point
        for node in ast.walk(block)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert defined, "no tests found to register"
    assert defined <= registered, sorted(defined - registered)


def test_a_headless_run_that_cannot_transcribe_writes_nothing_and_says_why():
    """A terminal gets an answer, not a traceback, when the recording cannot be read."""
    from src.headless import EXIT_NO_TRANSCRIPT, run_headless

    # Every model of the transcription chain refuses for the day.
    provider = FakeGeminiProvider(
        {model: [quota_failure_error()] for model in FALLBACK_MODELS}
    )

    with tempfile.TemporaryDirectory() as tmp:
        audio = a_recording_audio_file(tmp)
        outcome = run_headless(str(audio), output_dir=tmp, preprocess=False, cache_dir=tmp, client=provider)
        written = sorted(p.name for p in Path(tmp).glob("*.md"))

    assert outcome.exit_code == EXIT_NO_TRANSCRIPT
    assert outcome.transcript_path is None and outcome.minutes_path is None
    assert written == []


if __name__ == "__main__":
    test_audio_setup_wizard_integration()
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
    test_windows_style_ui_strings_are_complete()
    test_windows_style_chrome_replaced_the_slide_in_drawer()
    test_toolbar_and_menubar_cover_the_expected_actions()
    test_ui_uses_windows_flat_corner_radii()
    test_docs_are_bundled_and_discoverable()
    test_docs_menu_item_is_localized_in_every_mode()
    test_every_curated_doc_has_a_localized_title()
    test_docs_reader_shows_format_descriptions_not_raw_templates()
    test_template_description_file_parses_into_every_format()
    test_template_descriptions_render_as_markdown_in_both_locales()
    test_template_description_parser_handles_missing_or_empty_input()
    test_docs_source_line_interpolates_the_path()
    test_api_key_link_points_at_google_ai_studio()
    test_api_key_link_strings_are_localized()
    test_settings_help_no_longer_hardcodes_the_key_url()
    test_theme_pairs_meet_wcag_aa_contrast()
    test_docs_sidebar_widgets_use_explicit_theme_colors()
    test_translate_has_no_combined_mode()
    test_translate_missing_key_raises()
    test_every_literal_translation_key_resolves()
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
    test_weak_model_diarization_policy()
    test_quota_failure_predicate_separates_quota_from_transient_errors()
    test_quota_failure_skips_retries_and_fails_over_to_the_next_model()
    test_transient_error_retries_with_backoff_then_fails_over()
    test_success_ends_the_failover_chain_without_touching_later_models()
    test_exhausted_failover_chain_raises_the_calls_final_error()
    test_resource_lifecycle_brackets_one_models_whole_retry_sweep()
    test_resource_is_released_even_when_a_models_sweep_fails()
    test_transcribed_chunk_is_uploaded_once_and_the_upload_is_deleted()
    test_transcription_reuses_one_upload_across_a_models_retries()
    test_transcription_fails_over_to_a_later_model_after_a_transient_error()
    test_transcription_deletes_the_uploaded_audio_when_the_run_is_cancelled()
    test_cancellation_during_an_upload_leaves_no_file_in_provider_storage()
    test_transcription_diarization_still_turns_off_for_weak_models()
    test_transcription_reports_its_own_progress_wording()
    test_transcription_keeps_its_own_quota_failure_message()
    test_transcription_retries_an_empty_transcription_on_its_own_backoff()
    test_a_chunk_that_only_ever_comes_back_empty_is_not_a_transcript()
    test_transcription_path_delegates_its_failure_policy_to_the_shared_module()
    test_upload_lifecycle_is_an_input_to_the_policy_not_part_of_it()
    test_failover_policy_module_owns_the_policy_and_nothing_else()
    test_failover_description_carries_no_provider_types()
    test_recap_path_keeps_its_backoff_step_and_temperature()
    test_recap_quota_failure_message_is_unchanged()
    test_recap_path_delegates_its_failure_policy_to_the_shared_module()
    test_minutes_path_fails_over_to_the_next_model_on_a_quota_failure()
    test_minutes_quota_failure_message_is_unchanged()
    test_minutes_path_retries_a_transient_error_with_backoff_then_answers()
    test_action_items_path_fails_over_to_the_next_model_on_a_quota_failure()
    test_action_items_path_retries_a_transient_error_with_backoff_then_answers()
    test_action_items_quota_failure_message_is_unchanged()
    test_minutes_and_action_items_delegate_their_failure_policy_to_the_shared_module()
    test_minutes_keep_their_own_failover_chain_apart_from_transcription()
    test_tooltip_text_provider()
    test_a_whole_pipeline_run_reports_what_it_is_doing_and_yields_transcript_and_minutes()
    test_a_minutes_failure_never_costs_the_transcript()
    test_the_run_honours_the_engine_and_the_processing_language()
    test_every_report_a_run_makes_renders_from_its_key_and_args()
    test_a_run_defaults_to_what_the_desktop_app_persists()
    test_a_cancelled_run_transcribes_nothing()
    test_preprocessing_decides_which_audio_is_transcribed_and_reports_its_own_progress()
    test_importing_the_pipeline_run_pulls_in_no_ui_toolkit()
    test_the_pipeline_run_module_reaches_no_ui_package_and_no_translation_table()
    test_the_pipeline_run_takes_its_settings_as_a_plain_data_object()
    test_a_headless_run_writes_the_transcript_and_the_minutes_to_disk()
    test_a_headless_run_keeps_the_transcript_when_minutes_fail()
    test_a_headless_run_that_cannot_transcribe_writes_nothing_and_says_why()
    test_chunking_splits_a_long_audio_file_and_every_chunk_is_transcribed()
    test_chunking_is_skipped_entirely_when_it_is_off()
    test_a_checkpoint_records_each_chunk_as_soon_as_it_is_done()
    test_an_interrupted_run_resumes_and_does_not_re_pay_for_chunks_already_done()
    test_tail_context_carries_the_previous_chunk_across_the_seam()
    test_overlap_is_removed_from_the_seam_between_two_chunks()
    test_a_cancelled_run_stops_between_chunks_and_leaves_the_rest_resumable()
    test_ctrl_c_cancels_a_headless_run_and_leaves_it_resumable()
    test_a_headless_run_that_failed_partway_is_resumed_by_running_it_again()
    test_a_console_report_prints_its_key_and_arguments_without_a_translation_table()
    test_the_headless_flag_on_the_entry_point_configures_the_run()
    test_the_engine_and_its_model_name_name_the_same_choice_both_ways()
    test_every_test_in_this_suite_is_registered_to_run()
    print("All unit tests passed successfully!")

