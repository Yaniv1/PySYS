"""Download an OpCloud model's HTML export to a caller-selected target."""

from __future__ import annotations

import os
import argparse
import json
import shutil
import subprocess
import time
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

from ai_services import (
    activate_opm2pysys_agent,
    run_python_module,
    backfill_request_metrics,
    extract_python_code,
    load_agent_settings,
    resolve_instruction_prompt,
    send_llm_request,
    test_python_in_sandbox,
    strip_base64_images,
)

try:
    from pywinauto import Desktop, keyboard
except ImportError:
    Desktop = None
    keyboard = None


class ModelSpecResult(TypedDict):
    url: str
    destination: Path
    save_dialog_confirmed: bool


def construct_opcloud_url(model_id: str) -> str:
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


def copy_missing_items(source: str | Path, destination: str | Path) -> Path:
    """Copy a template into a destination without replacing existing items."""
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser()
    if not source.is_dir():
        raise ValueError(f"Template directory does not exist: {source}")

    destination.mkdir(parents=True, exist_ok=True)
    for source_item in source.rglob("*"):
        relative = source_item.relative_to(source)
        destination_item = destination / relative
        if source_item.is_dir():
            destination_item.mkdir(parents=True, exist_ok=True)
        elif not destination_item.exists():
            destination_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_item, destination_item)
    return destination.resolve()


def template_directory(base_directory: str | Path | None = None) -> Path:
    root = (
        Path(base_directory).expanduser().resolve()
        if base_directory is not None
        else Path(__file__).resolve().parent
    )
    template = root / "Projects" / "__Template__"
    if not template.is_dir():
        raise ValueError(f"Project template does not exist: {template}")
    return template


def load_project_params(project_directory: str | Path | None = None) -> dict:
    if project_directory is None:
        params_path = template_directory() / "Params" / "params.json"
    else:
        params_path = Path(project_directory).expanduser().resolve() / "Params" / "params.json"
    if not params_path.is_file():
        raise ValueError(f"Project params file does not exist: {params_path}")
    with params_path.open("r", encoding="utf-8") as params_file:
        params = json.load(params_file)
    if not isinstance(params, dict):
        raise ValueError("Project params must contain a JSON object.")
    return params


def resolve_param_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def model_store_directory(project_directory: str | Path) -> Path:
    params = load_project_params(project_directory)
    artifacts = params.get("Artifacts", {})
    model_store = artifacts.get("Models") if isinstance(artifacts, dict) else None
    if not isinstance(model_store, str) or not model_store.strip():
        raise ValueError("Params.Artifacts.Models must contain a relative or absolute path.")
    model_path = Path(model_store).expanduser()
    if not model_path.is_absolute():
        model_path = Path(project_directory).expanduser().resolve() / model_path
    return model_path.resolve()


def code_store_directory(project_directory: str | Path) -> Path:
    params = load_project_params(project_directory)
    artifacts = params.get("Artifacts", {})
    code_store = artifacts.get("Code") if isinstance(artifacts, dict) else None
    if not isinstance(code_store, str) or not code_store.strip():
        raise ValueError("Params.Artifacts.Code must contain a relative or absolute path.")
    project_path = Path(project_directory).expanduser().resolve()
    project_name = params.get("ProjectName")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = project_path.name
    code_path = Path(code_store).expanduser()
    if not code_path.is_absolute():
        code_path = project_path / code_path
    if code_path.name.casefold() != project_name.strip().casefold():
        code_path = code_path / project_name.strip()
    return code_path.resolve()


def image_store_directory(project_directory: str | Path) -> Path:
    params = load_project_params(project_directory)
    artifacts = params.get("Artifacts", {})
    image_store = artifacts.get("Images") if isinstance(artifacts, dict) else None
    if not isinstance(image_store, str) or not image_store.strip():
        image_store = "Artifacts/Images"
    image_path = Path(image_store).expanduser()
    if not image_path.is_absolute():
        image_path = Path(project_directory).expanduser().resolve() / image_path
    return image_path.resolve()


def setup_git_repo(
    code_directory: str | Path,
    action: str = "none",
    source: str | Path | None = None,
    branch: str | None = None,
) -> dict:
    code_path = Path(code_directory).expanduser().resolve()
    normalized_action = action.strip().lower()
    if normalized_action in {"", "none", "skip"}:
        return {"action": "none", "code": code_path}

    code_path.mkdir(parents=True, exist_ok=True)
    git_marker = code_path / ".git"
    if git_marker.exists():
        result = subprocess.run(
            ["git", "-C", str(code_path), "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "The code directory is not a usable Git repository.")
        return {"action": "existing", "code": code_path, "output": result.stdout.strip()}

    def run_git(command: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise OSError("Git executable was not found in PATH.") from error

    preserved_directory = None
    has_existing_content = any(code_path.iterdir())
    if has_existing_content:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        preserved_directory = code_path.with_name(f"{code_path.name}_pre_git_{timestamp}")
        while preserved_directory.exists():
            preserved_directory = code_path.with_name(
                f"{code_path.name}_pre_git_{timestamp}_{os.getpid()}"
            )
        code_path.rename(preserved_directory)
        code_path.mkdir(parents=True, exist_ok=False)

    if normalized_action == "create":
        command = ["git", "-C", str(code_path), "init"]
    elif normalized_action == "clone":
        if not source:
            if preserved_directory is not None:
                preserved_directory.rename(code_path)
            raise ValueError("git=clone requires git_source=LOCAL_OR_REMOTE_REPOSITORY.")
        source_path = Path(source).expanduser()
        clone_source = str(source_path.resolve()) if source_path.is_absolute() or source_path.exists() else str(source)
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([clone_source, str(code_path)])
    else:
        if preserved_directory is not None:
            preserved_directory.rename(code_path)
        raise ValueError("git must be none, create, or clone.")

    result = run_git(command)
    if result.returncode != 0:
        if preserved_directory is not None and code_path.exists():
            failed_directory = code_path.with_name(f"{code_path.name}_git_failed_{os.getpid()}")
            code_path.rename(failed_directory)
            preserved_directory.rename(code_path)
        raise OSError(result.stderr.strip() or result.stdout.strip() or "Git operation failed.")

    if preserved_directory is not None:
        for preserved_item in preserved_directory.iterdir():
            if preserved_item.name == ".git":
                continue
            destination = code_path / preserved_item.name
            if preserved_item.is_dir():
                shutil.copytree(preserved_item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(preserved_item, destination)

    for config_command in (
        ["git", "-C", str(code_path), "config", "user.name", "PySYS"],
        ["git", "-C", str(code_path), "config", "user.email", "pysys@local"],
    ):
        config_result = run_git(config_command)
        if config_result.returncode != 0:
            raise OSError(config_result.stderr.strip() or "Unable to configure local Git identity.")
    run_git(["git", "-C", str(code_path), "add", "-A"])
    status_result = run_git(["git", "-C", str(code_path), "status", "--porcelain"])
    if status_result.returncode == 0 and status_result.stdout.strip():
        commit_result = run_git([
            "git",
            "-C",
            str(code_path),
            "commit",
            "-m",
            "Bootstrap existing code",
        ])
        if commit_result.returncode != 0:
            raise OSError(commit_result.stderr.strip() or "Unable to create the baseline Git commit.")

    status_result = run_git(["git", "-C", str(code_path), "status", "--short", "--branch"])
    if status_result.returncode != 0:
        raise OSError(status_result.stderr.strip() or "Unable to verify the Git repository.")
    return {
        "action": normalized_action,
        "code": code_path,
        "preserved": preserved_directory,
        "output": status_result.stdout.strip(),
    }


def parse_explicit_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Boolean value must be true or false: {value}")


def latest_model_file(project_directory: str | Path) -> Path:
    model_directory = model_store_directory(project_directory)
    candidates = [
        path
        for path in model_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    ]
    if not candidates:
        raise ValueError(f"No OPM HTML model was found in {model_directory}.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def results_directory(project_directory: str | Path) -> Path:
    project_path = Path(project_directory).expanduser().resolve()
    params = load_project_params(project_path)
    artifacts = params.get("Artifacts", {})
    results_store = artifacts.get("Results") if isinstance(artifacts, dict) else None
    if not isinstance(results_store, str) or not results_store.strip():
        results_store = "Results"
    results_path = Path(results_store).expanduser()
    if not results_path.is_absolute():
        results_path = project_path / results_path
    results_path.mkdir(parents=True, exist_ok=True)
    return results_path.resolve()


def write_run_status(project_directory: str | Path, status: dict) -> tuple[Path, Path]:
    project_path = Path(project_directory).expanduser().resolve()
    results_path = results_directory(project_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    status.setdefault("timestamp", timestamp)
    status.setdefault("project", str(project_path))

    json_path = results_path / "run_status.json"
    json_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# PySYS Run Status",
        "",
        f"- Timestamp: `{status['timestamp']}`",
        f"- Project: `{project_path}`",
        f"- Phase: `{status.get('phase', 'unknown')}`",
        f"- Status: `{status.get('status', 'unknown')}`",
    ]
    for key in ("reload_model", "refine_code", "regenerate_code", "run_code", "git"):
        if key in status:
            lines.append(f"- {key}: `{status[key]}`")
    for key in ("model", "code", "request", "response"):
        if status.get(key):
            lines.append(f"- {key}: `{status[key]}`")
    if status.get("error"):
        lines.extend(["", "## Error", "", str(status["error"])])
    md_path = results_path / "run_status.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def create_project_folder(
    project_name: str,
    target: str | Path | None = None,
    template: str | Path | None = None,
) -> Path:
    if not project_name.strip():
        raise ValueError("project_name cannot be empty.")
    if template is None:
        template_path = template_directory()
    else:
        template_path = Path(template).expanduser().resolve()

    if target is None:
        params = load_project_params(template_path)
        default_root = params.get("DefaultProjectRoot")
        if not isinstance(default_root, str) or not default_root.strip():
            raise ValueError("Params.DefaultProjectRoot must contain a path.")
        target_path = resolve_param_path(default_root) / project_name
    else:
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = (Path.cwd() / target_path).resolve()
    target_path = target_path.resolve()
    project_directory = copy_missing_items(template_path, target_path)

    params_path = project_directory / "Params" / "params.json"
    if params_path.is_file():
        with params_path.open("r", encoding="utf-8") as params_file:
            params = json.load(params_file)
        if params.get("ProjectName") in {None, "", "__Template__"}:
            params["ProjectName"] = project_name
            with params_path.open("w", encoding="utf-8") as params_file:
                json.dump(params, params_file, ensure_ascii=False, indent=4)
                params_file.write("\n")
        resources = params.get("CodeResources", [])
        if isinstance(resources, list):
            project_resources = project_directory / "Resources"
            for resource in resources:
                if not isinstance(resource, str) or not resource.strip():
                    continue
                source = Path(__file__).resolve().parent / resource
                if not source.is_file():
                    continue
                destination = project_resources / resource
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    return project_directory


def _resolve_file_value(
    value: str,
    instruction_directory: Path,
    project_directory: Path,
) -> str:
    candidates = [
        instruction_directory / value,
        project_directory / value,
        Path(__file__).resolve().parent / value,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return value


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

    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(visible_only=True)
    except Exception as error:
        print(
            f"Temporary Windows UIA overwrite-dialog inspection failure: {error}",
            flush=True,
        )
        return False

    for window in windows:
        try:
            descendants = window.descendants()
        except Exception as error:
            print(
                f"Temporary UIA wrapper failure while inspecting an overwrite dialog: {error}",
                flush=True,
            )
            continue
        confirmations = [
            control
            for control in descendants
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

    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(visible_only=True)
    except Exception as error:
        print(
            f"Temporary Windows UIA dialog inspection failure: {error}",
            flush=True,
        )
        return False

    for window in windows:
        try:
            controls = window.descendants()
        except Exception as error:
            print(
                f"Temporary UIA wrapper failure while inspecting a dialog: {error}",
                flush=True,
            )
            continue
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
    allowed_keys = {
        "source",
        "target",
        "downloads_dir",
        "timeout",
        "project",
        "project_target",
        "agent",
        "activate",
        "base_json",
        "output_file",
        "api_key",
        "model",
        "endpoint",
        "reasoning_effort",
        "input_cost_usd_per_million",
        "cached_input_cost_usd_per_million",
        "output_cost_usd_per_million",
        "reload_model",
        "refine_code",
        "regenerate_code",
        "run_code",
        "git",
        "git_source",
        "git_branch",
        "backfill_metrics",
    }

    for argument in arguments:
        key, separator, value = argument.partition("=")
        if not separator or not key or not value:
            parser.error(f"Arguments must use key=value syntax: {argument}")
        if key not in allowed_keys:
            parser.error(f"Unknown argument: {key}")
        if key in values:
            parser.error(f"Argument specified more than once: {key}")
        values[key] = value

    return values


def get_model_spec(
    source: str,
    output_path: str | Path | None = None,
    target: str | None = None,
    timeout: int | None = None,
    image_directory: str | Path | None = None,
) -> ModelSpecResult:
    url = export_url(source)
    if timeout is None:
        params = load_project_params()
        timeout = int(params.get("Timeout", 300))
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")
    if output_path is None:
        params = load_project_params()
        downloads = params.get("Downloads")
        if not isinstance(downloads, str):
            raise ValueError("Params.Downloads must contain a path.")
        output_path = resolve_param_path(downloads)
    downloads_directory = Path(output_path).expanduser().resolve()
    if not downloads_directory.is_dir():
        raise ValueError(f"Download directory does not exist: {downloads_directory}")
    target_directory, target_filename = (
        target_location(target) if target is not None else (None, None)
    )
    if target_directory is not None:
        target_directory = target_directory.resolve()
        os.makedirs(target_directory, exist_ok=True)
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
    if close_export_tab():
        print("Closed the OpCloud export tab after the download completed.", flush=True)
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

    if destination.is_file() and destination.suffix.lower() in {".html", ".htm"}:
        html_text = destination.read_text(encoding="utf-8")
        if image_directory is None:
            image_directory = destination.parent / "Artifacts" / "Images"
        sanitized_html, removed_images, saved_images = strip_base64_images(
            html_text,
            image_directory,
            link_prefix=str(Path(image_directory).resolve()),
        )
        if removed_images:
            destination.write_text(sanitized_html, encoding="utf-8")
            print(
                f"Extracted {removed_images} embedded image(s) to "
                f"{Path(image_directory).resolve()}; "
                f"updated {destination}",
                flush=True,
            )

    return {
        "url": url,
        "destination": destination,
        "save_dialog_confirmed": save_dialog_confirmed,
    }

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export an OpCloud model's HTML to the Downloads folder. "
            "Use key=value arguments. Use project=NAME to create a project "
            "from the __Template__ folder."
        )
    )
    parser.add_argument(
        "arguments",
        nargs="*",
        metavar="key=value",
        help=(
            "Required: source=URL. Optional: target=PROJECT_ROOT, "
            "downloads_dir=PATH, timeout=SECONDS, project=NAME, "
            "project_target=PATH, agent=OPM2PySYS, activate=true, "
            "base_json=PATH, output_file=PATH, api_key=KEY, "
            "model=MODEL, endpoint=URL, reasoning_effort=high, "
            "reload_model=true, refine_code=true, regenerate_code=false, run_code=false, "
            "git=none, git_source=PATH_OR_URL, git_branch=BRANCH, "
            "input_cost_usd_per_million=RATE, "
            "cached_input_cost_usd_per_million=RATE, "
            "output_cost_usd_per_million=RATE."
        ),
    )
    values = parse_key_value_arguments(parser, parser.parse_args().arguments)

    project_directory = None
    project_name = values.get("project")
    if values.get("target") and project_name is None:
        project_name = Path(values["target"]).expanduser().name or None
    if project_name or values.get("project_target"):
        try:
            project_directory = create_project_folder(
                project_name or "__Project__",
                target=values.get("target") or values.get("project_target"),
            )
        except ValueError as error:
            parser.error(str(error))

    central_params = load_project_params(project_directory)
    downloads = central_params.get("Downloads")
    if not isinstance(downloads, str):
        parser.error("Params.Downloads must contain a path.")
    timeout = int(values.get("timeout", central_params.get("Timeout", 300)))
    try:
        reload_model = parse_explicit_bool(
            values.get("reload_model"),
            bool(central_params.get("ReloadModel", True)),
        )
        regenerate_code = parse_explicit_bool(
            values.get("regenerate_code"),
            bool(central_params.get("RegenerateCode", False)),
        )
        refine_code = parse_explicit_bool(
            values.get("refine_code"),
            bool(central_params.get("RefineCode", True)),
        )
        run_code = parse_explicit_bool(
            values.get("run_code"),
            bool(central_params.get("RunCode", False)),
        )
    except ValueError as error:
        parser.error(str(error))

    if refine_code and regenerate_code:
        parser.error("refine_code=true and regenerate_code=true are mutually exclusive.")

    git_params = central_params.get("Git", {})
    if not isinstance(git_params, dict):
        git_params = {}
    git_action = values.get("git", git_params.get("Action", "none"))
    git_source = values.get("git_source", git_params.get("Source"))
    git_branch = values.get("git_branch", git_params.get("Branch"))
    git_result = None
    if project_directory is not None:
        try:
            git_result = setup_git_repo(
                code_store_directory(project_directory),
                action=str(git_action),
                source=git_source,
                branch=git_branch,
            )
            build_source = (
                Path(project_directory).expanduser().resolve()
                / "Resources"
                / "build.ps1"
            )
            if not build_source.is_file():
                build_source = (
                    Path(__file__).resolve().parent
                    / "Projects"
                    / "__Template__"
                    / "build.ps1"
                )
            code_build = git_result["code"] / "build.ps1"
            if build_source.is_file():
                shutil.copy2(build_source, code_build)
        except (ValueError, OSError) as error:
            parser.error(str(error))

    if project_directory is not None:
        artifacts = central_params.get("Artifacts", {})
        requests_relative = artifacts.get("Requests") if isinstance(artifacts, dict) else None
        if isinstance(requests_relative, str) and requests_relative.strip():
            requests_path = Path(requests_relative).expanduser()
            if not requests_path.is_absolute():
                requests_path = project_directory / requests_path
            backfill_result = backfill_request_metrics(
                requests_path.resolve(),
                central_params.get("LanguageModelSettings", {}),
            )
            if backfill_result["updated"] > 0:
                print(
                    f"Backfilled metrics in {backfill_result['updated']} "
                    f"of {backfill_result['examined']} request folders.",
                    flush=True,
                )

    status = {
        "phase": "initialized",
        "status": "running",
        "reload_model": reload_model,
        "refine_code": refine_code,
        "regenerate_code": regenerate_code,
        "run_code": run_code,
        "git": git_result["action"] if git_result is not None else str(git_action).lower(),
        "code": str(git_result["code"]) if git_result is not None else None,
    }
    if project_directory is not None:
        write_run_status(project_directory, status)
        if git_result is not None and git_result["action"] != "none":
            print(f"Git repository ready at {git_result['code']} ({git_result['action']}).")

    model_target = None
    if project_directory is not None:
        model_target = str(model_store_directory(project_directory))

    destination = None
    if reload_model:
        if "source" not in values:
            parser.error("reload_model=true requires source=OPCLOUD_URL.")
        try:
            result = get_model_spec(
                source=values["source"],
                output_path=values.get("downloads_dir", resolve_param_path(downloads)),
                target=model_target or values.get("target"),
                timeout=timeout,
                image_directory=(
                    image_store_directory(project_directory)
                    if project_directory is not None
                    else None
                ),
            )
        except (ValueError, OSError) as error:
            if project_directory is not None:
                status.update(phase="reload_model", status="failed", error=str(error), model=str(destination))
                write_run_status(project_directory, status)
            parser.error(str(error))
        destination = result["destination"]
        if project_directory is not None:
            status.update(phase="reload_model", status="completed", model=str(destination))
            write_run_status(project_directory, status)
        if result["save_dialog_confirmed"]:
            print("Confirmed the Windows Save As dialog.")
        print(f"Saved HTML export to {destination}")
    else:
        if project_directory is None:
            parser.error("reload_model=false requires target=PROJECT_ROOT or project=NAME.")
        try:
            destination = latest_model_file(project_directory)
        except (ValueError, OSError) as error:
            status.update(phase="reuse_model", status="failed", error=str(error))
            write_run_status(project_directory, status)
            parser.error(str(error))
        print(f"Using latest cached HTML model: {destination}")
        status.update(phase="reuse_model", status="completed", model=str(destination))
        write_run_status(project_directory, status)

    should_activate = (refine_code or regenerate_code) and project_directory is not None
    if should_activate:
        if project_directory is None:
            parser.error("activate=true requires project=NAME or target=PROJECT_ROOT.")
        base_json = values.get("base_json")
        if base_json is not None:
            base_json = Path(base_json).expanduser()
            if not base_json.is_absolute():
                base_json = project_directory / base_json
        else:
            base_json = (
                project_directory
                / "Agents"
                / "OPM2PySYS"
                / "Instructions"
                / "base.json"
            )
        try:
            output_file = values.get("output_file")
            if output_file is None:
                output_file = central_params.get("OutputFile")
                if not isinstance(output_file, str) or not output_file.strip():
                    parser.error("Params.OutputFile must contain a filename or path.")
            existing_code = None
            if refine_code and not regenerate_code:
                code_path = Path(output_file).expanduser()
                if not code_path.is_absolute():
                    code_path = code_store_directory(project_directory) / code_path
                code_path = code_path.resolve()
                if code_path.is_file():
                    existing_code = code_path.read_text(encoding="utf-8")
            agent = activate_opm2pysys_agent(project_directory, base_json)
            conversion = agent.convert(
                destination,
                target_file=output_file,
                api_key=values.get("api_key"),
                model=values.get("model"),
                endpoint=values.get("endpoint"),
                reasoning_effort=values.get("reasoning_effort"),
                existing_code=existing_code,
                code_mode="refine" if refine_code and existing_code is not None else "regenerate",
                input_cost_usd_per_million=(
                    float(values["input_cost_usd_per_million"])
                    if values.get("input_cost_usd_per_million")
                    else None
                ),
                cached_input_cost_usd_per_million=(
                    float(values["cached_input_cost_usd_per_million"])
                    if values.get("cached_input_cost_usd_per_million")
                    else None
                ),
                output_cost_usd_per_million=(
                    float(values["output_cost_usd_per_million"])
                    if values.get("output_cost_usd_per_million")
                    else None
                ),
            )
        except (ValueError, OSError, RuntimeError, TimeoutError) as error:
            if project_directory is not None:
                status.update(
                    phase="generate_code",
                    status="failed",
                    model=str(destination),
                    error=str(error),
                )
                write_run_status(project_directory, status)
            parser.error(str(error))
        print(f"Saved converted Python module to {conversion['target']}")
        print(f"Saved LLM request to {conversion['request']}")
        print(f"Saved LLM response to {conversion['response']}")
        print(f"Generation metrics: {conversion['metrics']}", flush=True)
        status.update(
            phase="generate_code",
            status="completed",
            model=str(destination),
            code=str(conversion["target"]),
            request=str(conversion["request"]),
            response=str(conversion["response"]),
        )
        write_run_status(project_directory, status)
    elif not refine_code and not regenerate_code:
        if project_directory is None:
            parser.error("regenerate_code=false requires target=PROJECT_ROOT or project=NAME.")
        output_file = values.get("output_file")
        if output_file is None:
            output_file = central_params.get("OutputFile")
        if not isinstance(output_file, str) or not output_file.strip():
            parser.error("Params.OutputFile must contain a filename or path.")
        code_path = Path(output_file).expanduser()
        if not code_path.is_absolute():
            code_path = code_store_directory(project_directory) / code_path
        code_path = code_path.resolve()
        if not code_path.is_file():
            parser.error(f"Cached code file does not exist: {code_path}")
        print(f"Using cached Python module: {code_path}")
        status.update(phase="reuse_code", status="completed", code=str(code_path))
        write_run_status(project_directory, status)

    if run_code:
        if project_directory is None:
            parser.error("run_code=true requires target=PROJECT_ROOT or project=NAME.")
        output_file = values.get("output_file")
        if output_file is None:
            output_file = central_params.get("OutputFile")
        if not isinstance(output_file, str) or not output_file.strip():
            parser.error("Params.OutputFile must contain a filename or path.")
        code_path = Path(output_file).expanduser()
        if not code_path.is_absolute():
            code_path = code_store_directory(project_directory) / code_path
        code_path = code_path.resolve()
        if not code_path.is_file():
            parser.error(f"Python module to run does not exist: {code_path}")
        try:
            run_result = run_python_module(code_path, timeout=int(central_params.get("Timeout", 300)))
        except (OSError, TimeoutError) as error:
            status.update(phase="run_code", status="failed", code=str(code_path), error=str(error))
            write_run_status(project_directory, status)
            parser.error(str(error))
        if run_result.returncode != 0:
            details = run_result.stderr.strip() or run_result.stdout.strip()
            error_message = "Python module failed." + (f"\n{details}" if details else "")
            status.update(phase="run_code", status="failed", code=str(code_path), error=error_message)
            write_run_status(project_directory, status)
            parser.error(
                error_message
            )
        print(f"Ran Python module: {code_path}")
        status.update(phase="run_code", status="completed", code=str(code_path))
        write_run_status(project_directory, status)

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


#Activations:
# Download the OpCloud model as an HTML file:
# python opcloud.py source=https://opcloud.systems/load/-P6XkN5y0ERH8FXUakYz target="Projects\MyProject"
# create a project, set up API Key
# python opcloud.py source=https://opcloud.systems/load/-P6XkN5y0ERH8FXUakYz target="Projects\MyProject" project=MyProject activate=true api_key=OPENAI_API_KEY

# Set the API key in the environment before running the activation command:
#$env:OPENAI_API_KEY = "YOUR_API_KEY"
# python opcloud.py source=https://opcloud.systems/load/-P6XkN5y0ERH8FXUakYz project=MyProject activate=true target="Projects\MyProject"