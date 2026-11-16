"""Download an OpCloud model's HTML export to a caller-selected target."""

from __future__ import annotations

import argparse
import shutil
import time
import sys
import webbrowser
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

try:
    from pywinauto import Desktop, keyboard
except ImportError:
    Desktop = None
    keyboard = None


DEFAULT_DOWNLOADS_DIRECTORY = Path.home() / "Downloads"
class ModelSpecResult(TypedDict):
    url: str
    destination: Path
    save_dialog_confirmed: bool


def construct_url(model_id: str) -> str:
    return f"https://opcloud.systems/load/{model_id}"

def export_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "opcloud.systems":
        raise ValueError("The export URL must be an https://opcloud.systems/load/ URL.")
    if not parsed.path.startswith("/load/") or parsed.path == "/load/":
        raise ValueError("The export URL must identify a model under /load/.")
    if parse_qs(parsed.query).get("export-html") != ["true"]:
        separator = "&" if parsed.query else "?"
        return f"{url}{separator}export-html=true"
    return url


def target_location(target: str) -> tuple[Path | None, str | None]:
    supplied_path = Path(target).expanduser()
    includes_path = supplied_path.is_absolute() or supplied_path.parent != Path(".")
    if not includes_path:
        if not supplied_path.suffix:
            supplied_path = supplied_path.with_suffix(".html")
        if supplied_path.suffix.lower() not in {".htm", ".html"}:
            raise ValueError("The target filename must end in .htm or .html.")
        return None, supplied_path.name

    if supplied_path.is_dir() or not supplied_path.suffix:
        return supplied_path, None
    if supplied_path.suffix.lower() not in {".htm", ".html"}:
        raise ValueError("The target filename must end in .htm or .html.")
    return supplied_path.parent, supplied_path.name


def latest_download(
    downloads_directory: Path, started_at: float, recursive: bool
) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    paths = downloads_directory.rglob("*") if recursive else downloads_directory.glob("*")
    for path in paths:
        try:
            if not path.is_file() or path.suffix.lower() not in {".htm", ".html"}:
                continue
            modified_at = path.stat().st_mtime
        except FileNotFoundError:
            continue
        if modified_at >= started_at:
            candidates.append((modified_at, path))
    return max(candidates, default=(0, None))[1]


def wait_for_export(
    downloads_directory: Path,
    started_at: float,
    timeout: int,
) -> tuple[Path | None, bool]:
    previous_candidate: Path | None = None
    previous_size = -1
    save_dialog_confirmed = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not save_dialog_confirmed:
            save_dialog_confirmed = save_from_dialog(downloads_directory)
        else:
            confirm_overwrite_dialog()

        candidate = latest_download(downloads_directory, started_at, recursive=False)
        if candidate is not None:
            try:
                size = candidate.stat().st_size
            except FileNotFoundError:
                continue
            if candidate == previous_candidate and size == previous_size:
                return candidate, save_dialog_confirmed
            previous_candidate = candidate
            previous_size = size
        else:
            previous_candidate = None
            previous_size = -1
        time.sleep(0.5)
    return None, save_dialog_confirmed


def available_destination(source: Path, directory: Path) -> Path:
    destination = directory / source.name
    if destination.exists():
        stem = source.stem
        suffix = source.suffix
        index = 1
        while destination.exists():
            destination = directory / f"{stem} ({index}){suffix}"
            index += 1
    return destination


def close_export_tab() -> bool:
    if sys.platform != "win32" or Desktop is None:
        return False

    desktop = Desktop(backend="uia")
    for window in desktop.windows(visible_only=True):
        if "opcloud" not in window.window_text().casefold():
            continue
        window.set_focus()
        keyboard.send_keys("^w")
        return True
    return False


def confirm_overwrite_dialog() -> bool:
    if sys.platform != "win32" or Desktop is None:
        return False

    desktop = Desktop(backend="uia")
    for window in desktop.windows(visible_only=True):
        confirmations = [
            control
            for control in window.descendants()
            if control.element_info.control_type == "Window"
            and control.window_text() == "Confirm Save As"
            and control.is_visible()
        ]
        for confirmation in confirmations:
            yes_buttons = [
                button
                for button in confirmation.descendants(control_type="Button")
                if button.element_info.automation_id == "CommandButton_6"
                and button.window_text().replace("&", "").strip().casefold() == "yes"
                and button.is_visible()
                and button.is_enabled()
            ]
            if yes_buttons:
                print("Confirming overwrite of the existing download.")
                yes_buttons[0].invoke()
                return True
    return False


def set_dialog_text(control, text: str) -> None:
    control.set_focus()
    control.set_edit_text(text)
    # Windows' file dialog may not commit a UI Automation value without an edit event.
    control.type_keys("{END}{SPACE}{BACKSPACE}")
    if control.get_value() != text:
        raise OSError("Unable to set the Save As dialog text; save the export manually.")


def save_from_dialog(downloads_directory: Path) -> bool:
    """Save the browser's suggested filename in the downloads directory."""
    if sys.platform != "win32" or Desktop is None:
        return False

    desktop = Desktop(backend="uia")
    for window in desktop.windows(visible_only=True):
        controls = window.descendants()
        save_buttons = [
            button
            for button in controls
            if button.element_info.control_type == "Button"
            and button.element_info.automation_id == "1"
            and button.window_text().replace("&", "").strip().casefold() == "save"
            and button.is_visible()
            and button.is_enabled()
        ]
        file_names = [
            control
            for control in controls
            if control.element_info.control_type == "Edit"
            and control.element_info.automation_id == "1001"
            and control.is_visible()
            and control.is_enabled()
        ]
        if not save_buttons or not file_names:
            continue

        file_name = file_names[0]
        filename = Path(file_name.get_value()).name
        if filename and not Path(filename).suffix:
            filename += ".html"
        if not filename or Path(filename).suffix.lower() not in {".htm", ".html"}:
            raise OSError("The Save As dialog did not provide an HTML filename.")
        set_dialog_text(file_name, str(downloads_directory / filename))
        save_buttons[0].click_input()
        return True
    return False


def parse_key_value_arguments(parser: argparse.ArgumentParser, arguments: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    allowed_keys = {"source", "target", "downloads_dir", "timeout"}

    for argument in arguments:
        key, separator, value = argument.partition("=")
        if not separator or not key or not value:
            parser.error(f"Arguments must use key=value syntax: {argument}")
        if key not in allowed_keys:
            parser.error(f"Unknown argument: {key}")
        if key in values:
            parser.error(f"Argument specified more than once: {key}")
        values[key] = value

    if "source" not in values:
        parser.error("A source=OPCLOUD_URL argument is required.")
    return values


def get_model_spec(
    source: str,
    output_path: str | Path = DEFAULT_DOWNLOADS_DIRECTORY,
    target: str | None = None,
    timeout: int = 300,
) -> ModelSpecResult:
    url = export_url(source)
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")
    downloads_directory = Path(output_path).expanduser().resolve()
    if not downloads_directory.is_dir():
        raise ValueError(f"Download directory does not exist: {downloads_directory}")
    target_directory, target_filename = (
        target_location(target) if target is not None else (None, None)
    )
    if target_directory is not None:
        target_directory = target_directory.resolve()
        if not target_directory.is_dir():
            raise ValueError(f"Target directory does not exist: {target_directory}")
    started_at = time.time()
    if not webbrowser.open(url, new=2):
        raise OSError(f"Unable to open the default browser. Open this URL manually:\n{url}")
    print(
        f"Opened OpCloud's HTML export flow. Waiting up to {timeout} seconds "
        f"for the HTML download in {downloads_directory}...",
        flush=True,
    )
    if sys.platform != "win32" or Desktop is None or keyboard is None:
        print(
            "Automatic Save As dialog handling is unavailable. Select the directory "
            f"{downloads_directory} manually in the browser's Save As dialog.",
            flush=True,
        )
    downloaded, save_dialog_confirmed = wait_for_export(
        downloads_directory, started_at, timeout,
    )
    if downloaded is None:
        raise TimeoutError(
            f"No completed HTML export was found in {downloads_directory} within "
            f"{timeout} seconds. Check that the export completed and was saved there."
        )
    if target is None:
        destination = downloaded
    elif target_filename is not None:
        destination = (target_directory or downloads_directory) / target_filename
    else:
        assert target_directory is not None
        destination = (
            downloaded if target_directory == downloaded.parent
            else available_destination(downloaded, target_directory)
        )
    if downloaded != destination:
        shutil.copy2(downloaded, destination)
        print(f"Copied browser download from {downloaded}", flush=True)

    return {
        "url": url,
        "destination": destination,
        "save_dialog_confirmed": save_dialog_confirmed,
    }

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export an OpCloud model's HTML to the Downloads folder. "
            "Use key=value arguments."
        )
    )
    parser.add_argument(
        "arguments",
        nargs="*",
        metavar="key=value",
        help=(
            "Required: source=URL. Optional: target=NAME_OR_PATH, "
            "downloads_dir=PATH, timeout=SECONDS."
        ),
    )
    values = parse_key_value_arguments(parser, parser.parse_args().arguments)

    try:
        result = get_model_spec(
            source=values["source"],
            output_path=values.get("downloads_dir", str(DEFAULT_DOWNLOADS_DIRECTORY)),
            target=values.get("target"),
            timeout=int(values.get("timeout", "300")),
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))

    destination = result["destination"]
    if result["save_dialog_confirmed"]:
        print("Confirmed the Windows Save As dialog.")

    print(f"Saved HTML export to {destination}")
    if close_export_tab():
        print("Closed the OpCloud export tab.")
    else:
        print("The export tab was not closed because no active OPCloud browser tab was found.")
    return 0



def load_html_file(file_path: str | Path) -> str:
    """
    Load an HTML file and return its contents.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        h = f.read()
    return h
    
    
if __name__ == "__main__":
    sys.exit(main())
