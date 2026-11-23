"""Build source and extension archives, excluding all runtime accounts and logins."""
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SKIP = {"data", "test-output", "__pycache__", ".git", ".venv", "node_modules", ".openai"}


def source_files():
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in SKIP]
        for name in files:
            if name == "app_config.json" or name == ".env" or name.startswith((".env.", "credentials", "token")) or name.endswith((".pyc", ".zip")):
                continue
            yield Path(directory) / name


def main():
    source = ROOT.parent / "study-dock.zip"
    extension = ROOT.parent / "study-dock-extension.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in source_files():
            archive.write(file, (Path("study-dock") / file.relative_to(ROOT)).as_posix())
    with zipfile.ZipFile(extension, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in (ROOT / "extension").iterdir():
            if file.is_file() and file.suffix in (".js", ".html", ".css", ".json", ".md") and not file.name.startswith("."):
                archive.write(file, "study-dock-extension/" + file.name)
    print("Ready: study-dock.zip, study-dock-extension.zip. Runtime data excluded.")


if __name__ == "__main__":
    main()
