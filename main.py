"""
STTMeet - Meeting Transcription and Minutes Generator
Main Entrypoint

Two ways in. Without a flag, the desktop window opens. With --headless, an Audio file
is transcribed from a terminal and the Transcript and Minutes are written to disk.

The desktop toolkit is imported inside the branch that needs it, so the headless path
never loads a UI it will not use -- which is the same discipline the Pipeline run itself
follows.
"""
import argparse
import sys

from src.pipeline import ENGINE_MODEL_OVERRIDES
from src.session_store import (
    DEFAULT_SETTINGS,
    VALID_CHUNK_MINUTES,
    VALID_LANGUAGES,
    VALID_TEMPLATES,
)

AUTO_MODEL = "auto"
DEFAULT_ENGINE = DEFAULT_SETTINGS["engine"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sttmeet",
        description="Transcribe a meeting and write its Transcript and Minutes.",
    )
    parser.add_argument(
        "--headless", metavar="AUDIO_FILE",
        help="Run one Pipeline run on this Audio file from a terminal and write the "
             "Transcript and Minutes to disk, instead of opening the window.",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help="Where to write the Transcript and Minutes. Defaults to the Audio file's folder.",
    )
    parser.add_argument(
        "--model", choices=[AUTO_MODEL] + sorted(set(ENGINE_MODEL_OVERRIDES.values())),
        default=AUTO_MODEL,
        help="Which model leads the Failover chain. Defaults to auto-failover. "
             "The window calls this choice the Engine; on a command line the model "
             "names are what you can actually type.",
    )
    parser.add_argument(
        "--language", choices=VALID_LANGUAGES,
        help="Processing language the Minutes are written in. Defaults to the desktop app's.",
    )
    parser.add_argument(
        "--template", choices=VALID_TEMPLATES,
        help="Template the Minutes take. Defaults to the desktop app's.",
    )
    parser.add_argument(
        "--no-preprocess", action="store_true",
        help="Skip Preprocessing and send the recording as it is.",
    )
    parser.add_argument(
        "--chunk-minutes", type=int, default=DEFAULT_SETTINGS["chunk_minutes"],
        choices=VALID_CHUNK_MINUTES,
        help="Split a long Audio file into Chunks of this many minutes. "
             "Pass 0 to transcribe the whole recording as one Chunk. Defaults to the "
             "desktop app's.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.headless:
        from src.headless import run_headless
        from src.pipeline import engine_for_model

        engine = (
            DEFAULT_ENGINE if args.model == AUTO_MODEL else engine_for_model(args.model)
        )
        outcome = run_headless(
            args.headless,
            output_dir=args.output_dir,
            language=args.language,
            engine=engine,
            template=args.template,
            preprocess=not args.no_preprocess,
            chunk_minutes=args.chunk_minutes,
        )
        return outcome.exit_code

    # The desktop app is a separate entry point that happens to share the same file.
    print("=" * 60)
    print("[STTMeet] Starting STTMeet Desktop Application...")
    print("Opening application window. Please check your taskbar/desktop.")
    print("Close the desktop window or press Ctrl+C in this terminal to exit.")
    print("=" * 60)
    from src.ui import run_app
    run_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())