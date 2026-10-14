"""
STTMeet - Meeting Transcription and Minutes Generator
Main Entrypoint
"""
from src.ui import run_app

def main():
    print("=" * 60)
    print("🎙️ Starting STTMeet Desktop Application...")
    print("Opening application window. Please check your taskbar/desktop.")
    print("Close the desktop window or press Ctrl+C in this terminal to exit.")
    print("=" * 60)
    run_app()

if __name__ == "__main__":
    main()
