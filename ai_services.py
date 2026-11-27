"""AI prompt resolution, LLM interaction, and sandbox validation."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import statistics
import re
import base64
from datetime import datetime, timezone
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


def strip_base64_images(
    html_text: str,
    image_directory: str | Path,
    link_prefix: str = "images",
) -> tuple[str, int, list[Path]]:
    if not html_text:
        return html_text, 0, []

    pattern = re.compile(
        r"data:(image/[a-zA-Z0-9.+-]+);base64,"
        r"([A-Za-z0-9+/=\r\n\t]+)",
        re.IGNORECASE,
    )
    image_path = Path(image_directory).expanduser().resolve()
    image_path.mkdir(parents=True, exist_ok=True)
    count = 0
    saved_images = []

    def replace(match: re.Match) -> str:
        nonlocal count
        count += 1
        media_type = match.group(1).lower()
        extension = media_type.split("/", 1)[1].split("+", 1)[0]
        if extension == "jpeg":
            extension = "jpg"
        elif extension not in {"png", "jpg", "gif", "webp", "svg"}:
            extension = "bin"
        filename = f"embedded-{count:04d}.{extension}"
        destination = image_path / filename
        payload = re.sub(r"[\r\n\t]", "", match.group(2))
        try:
            decoded = base64.b64decode(payload, validate=True)
        except Exception:
            return "[invalid embedded image omitted]"
        destination.write_bytes(decoded)
        saved_images.append(destination)
        return f"{link_prefix.rstrip('/')}/{filename}"

    return pattern.sub(replace, html_text), count, saved_images


def resolve_instruction_prompt(
    base_json: str | Path,
    project_directory: str | Path | None = None,
) -> str:
    base_path = Path(base_json).expanduser().resolve()
    if not base_path.is_file():
        raise ValueError(f"Instruction base file does not exist: {base_path}")
    with base_path.open("r", encoding="utf-8") as instruction_file:
        instructions = json.load(instruction_file)
    if not isinstance(instructions, dict):
        raise ValueError("The instruction base must contain a JSON object.")

    instruction_directory = base_path.parent
    project_path = (
        Path(project_directory).expanduser().resolve()
        if project_directory is not None
        else instruction_directory.parents[2]
    )

    def resolve_value(key: str, value):
        if isinstance(value, dict):
            if value.get("type") in {"file", "path"}:
                file_value = value.get("value", value.get("path"))
                if not isinstance(file_value, str):
                    raise ValueError(f"File instruction {key} must have a string path.")
                return _resolve_file_value(file_value, instruction_directory, project_path)
            return {
                nested_key: resolve_value(nested_key, nested_value)
                for nested_key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [resolve_value(key, nested_value) for nested_value in value]
        if isinstance(value, str):
            suffix = Path(value).suffix.lower()
            if suffix in {".md", ".txt", ".html", ".htm", ".py", ".json"}:
                resolved = _resolve_file_value(value, instruction_directory, project_path)
                if resolved != value:
                    return resolved
        return value

    lines = [
        "Convert the following OPM/OpCloud model into a working PySYS Python module.",
        "Follow every instruction and use only facts contained in the model.",
        "",
    ]
    for key, value in instructions.items():
        if key.lower() in {"languagemodelsettings", "language_model_settings"}:
            continue
        resolved = resolve_value(key, value)
        lines.append(f"{key}:")
        if isinstance(resolved, str):
            lines.append(resolved)
        else:
            lines.append(json.dumps(resolved, ensure_ascii=False, indent=2))
        lines.append("")
    return "\n".join(lines).strip()


def load_agent_settings(base_json: str | Path, project_directory: str | Path) -> dict:
    base_path = Path(base_json).expanduser().resolve()
    project_path = Path(project_directory).expanduser().resolve()
    settings = {}

    params_path = project_path / "Params" / "params.json"
    if params_path.is_file():
        with params_path.open("r", encoding="utf-8") as params_file:
            params = json.load(params_file)
        settings.update(params.get("LanguageModelSettings", {}))

    with base_path.open("r", encoding="utf-8") as instruction_file:
        instructions = json.load(instruction_file)
    settings.update(instructions.get("LanguageModelSettings", {}))
    settings.update(instructions.get("language_model_settings", {}))
    return settings


def _timestamp_request_directory(requests_directory: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    request_directory = requests_directory / timestamp
    if request_directory.exists():
        request_directory = requests_directory / f"{timestamp}-{os.getpid()}"
    request_directory.mkdir(parents=True, exist_ok=False)
    return request_directory


def resolve_api_key(api_key) -> str:
    if api_key in {None, "", "OPENAI_API_KEY"}:
        api_key = os.environ.get("OPENAI_API_KEY")

    if isinstance(api_key, str):
        environment_key = os.environ.get(api_key)
        if environment_key:
            api_key = environment_key
        else:
            key_path = Path(api_key).expanduser()
            if key_path.is_file():
                api_key = key_path.read_text(encoding="utf-8").strip()
            elif key_path.is_absolute() or api_key.startswith("~") or "\\" in api_key or "/" in api_key:
                raise OSError(f"API key file does not exist: {key_path}")

    if not isinstance(api_key, str) or not api_key.strip():
        raise OSError("No LLM API key is configured. Set OPENAI_API_KEY or LanguageModelSettings.api_key.")
    return api_key.strip()


def estimate_previous_requests(
    requests_directory: str | Path,
    coding_mode: str | None = None,
) -> dict:
    requests_path = Path(requests_directory).expanduser().resolve()
    durations = []
    costs = []
    request_tokens = []
    response_tokens = []
    if requests_path.is_dir():
        for metadata_path in requests_path.rglob("request.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                historical_mode = metadata.get("coding_mode", "refine")
                if historical_mode not in {"refine", "regenerate"}:
                    historical_mode = "refine"
                if coding_mode is not None and historical_mode != coding_mode:
                    continue
                request_timestamp = datetime.fromisoformat(metadata["request_timestamp"].replace("Z", "+00:00"))
                response_timestamp = datetime.fromisoformat(metadata["response_timestamp"].replace("Z", "+00:00"))
                durations.append((response_timestamp - request_timestamp).total_seconds())
                if isinstance(metadata.get("request_cost_usd"), (int, float)):
                    costs.append(metadata["request_cost_usd"])
                if isinstance(metadata.get("request_tokens"), (int, float)):
                    request_tokens.append(metadata["request_tokens"])
                if isinstance(metadata.get("response_tokens"), (int, float)):
                    response_tokens.append(metadata["response_tokens"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
                continue
    median = lambda values: round(statistics.median(values), 2) if values else None
    return {
        "duration_seconds": median(durations),
        "cost_usd": median(costs),
        "request_tokens": median(request_tokens),
        "response_tokens": median(response_tokens),
        "request_count": len(durations),
    }


def format_estimate(
    requests_directory: str | Path,
    coding_mode: str | None = None,
    prompt: str | None = None,
    settings: dict | None = None,
) -> str:
    estimate = estimate_previous_requests(requests_directory, coding_mode)
    duration = estimate["duration_seconds"]
    request_tokens = estimate_tokens(prompt or "")
    response_tokens = (
        max(2000, request_tokens // 10)
        if coding_mode == "refine"
        else max(4000, request_tokens // 5)
    )
    cost = calculate_request_cost(
        settings or {},
        {},
        request_tokens,
        response_tokens,
    )
    parts = [
        f"estimated time: {duration:.1f}s"
        if duration is not None
        else "estimated time: unavailable"
    ]
    if cost is not None:
        parts.append(f"estimated cost: ${cost:.4f}")
    parts.append(
        f"estimated tokens: {request_tokens} request / {response_tokens} response"
    )
    return ", ".join(parts)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def calculate_request_cost(
    settings: dict,
    usage: dict,
    request_tokens: int,
    response_tokens: int,
) -> float | None:
    explicit_cost = usage.get("cost_usd")
    if not isinstance(explicit_cost, (int, float)):
        explicit_cost = usage.get("cost")
    if isinstance(explicit_cost, (int, float)):
        return float(explicit_cost)

    if int(request_tokens) > 272_000:
        input_rate = settings.get("long_input_cost_usd_per_million")
        cached_rate = settings.get("long_cached_input_cost_usd_per_million")
        output_rate = settings.get("long_output_cost_usd_per_million")
    else:
        input_rate = settings.get("input_cost_usd_per_million")
        cached_rate = settings.get("cached_input_cost_usd_per_million")
        output_rate = settings.get("output_cost_usd_per_million")

    cached_tokens = 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached_tokens = details.get("cached_tokens", 0)
    if not isinstance(cached_tokens, (int, float)):
        cached_tokens = 0

    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        if int(request_tokens) > 272_000:
            input_rate, cached_rate, output_rate = 4.0, 0.20, 15.0
        else:
            input_rate, cached_rate, output_rate = 2.0, 0.10, 10.0

    input_tokens = max(0, int(request_tokens) - int(cached_tokens))
    if not isinstance(cached_rate, (int, float)):
        cached_rate = input_rate

    return (
        input_tokens * input_rate / 1_000_000
        + int(cached_tokens) * cached_rate / 1_000_000
        + int(response_tokens) * output_rate / 1_000_000
    )


def format_completion_metrics(metadata_path: str | Path) -> str:
    path = Path(metadata_path).expanduser().resolve()
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        request_timestamp = datetime.fromisoformat(
            metadata["request_timestamp"].replace("Z", "+00:00")
        )
        response_timestamp = datetime.fromisoformat(
            metadata["response_timestamp"].replace("Z", "+00:00")
        )
        duration = (response_timestamp - request_timestamp).total_seconds()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return "Duration unavailable; token usage unavailable; cost unavailable"

    request_tokens = metadata.get("request_tokens")
    response_tokens = metadata.get("response_tokens")
    reasoning_tokens = metadata.get("reasoning_tokens")
    cost = metadata.get("request_cost_usd")
    request_text = str(request_tokens) if isinstance(request_tokens, (int, float)) else "unavailable"
    response_text = str(response_tokens) if isinstance(response_tokens, (int, float)) else "unavailable"
    cost_text = f"${float(cost):.6f}" if isinstance(cost, (int, float)) else "unavailable"
    return (
        f"Duration: {duration:.2f}s; "
        f"request tokens: {request_text}; "
        f"response tokens: {response_text}; "
        f"cost: {cost_text}"
    )


def write_request_metadata(
    request_directory: str | Path,
    prompt: str,
    response: str,
    request_timestamp,
    response_timestamp,
    settings: dict,
    usage: dict | None = None,
    coding_mode: str = "refine",
) -> Path:
    request_path = Path(request_directory).expanduser().resolve()
    usage = usage or {}
    request_tokens = usage.get("prompt_tokens")
    response_tokens = usage.get("completion_tokens")
    if request_tokens is None:
        request_tokens = usage.get("input_tokens")
    if response_tokens is None:
        response_tokens = usage.get("output_tokens")
    if request_tokens is None:
        request_tokens = usage.get("total_tokens")
    if not isinstance(request_tokens, (int, float)):
        request_tokens = estimate_tokens(prompt)
    if not isinstance(response_tokens, (int, float)):
        response_tokens = estimate_tokens(response)

    reasoning_tokens = usage.get("reasoning_tokens")
    if not isinstance(reasoning_tokens, (int, float)):
        output_details = usage.get("output_tokens_details")
        if isinstance(output_details, dict):
            reasoning_tokens = output_details.get("reasoning_tokens")
    if not isinstance(reasoning_tokens, (int, float)):
        reasoning_tokens = 0

    request_cost = calculate_request_cost(
        settings,
        usage,
        int(request_tokens),
        int(response_tokens),
    )

    metadata = {
        "request": "request.md",
        "response": "response.md",
        "coding_mode": coding_mode if coding_mode in {"refine", "regenerate"} else "refine",
        "request_timestamp": request_timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "response_timestamp": response_timestamp.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "request_tokens": int(request_tokens),
        "response_tokens": int(response_tokens),
        "reasoning_tokens": int(reasoning_tokens),
        "model": settings.get("model"),
        "request_cost_usd": request_cost,
        "openai_request_id": usage.get("request_id"),
        "openai_response_id": usage.get("response_id"),
    }
    metadata_path = request_path / "request.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata_path


def backfill_request_metrics(
    requests_directory: str | Path,
    settings: dict,
) -> dict:
    requests_path = Path(requests_directory).expanduser().resolve()
    updated = 0
    examined = 0
    for metadata_path in requests_path.rglob("request.json"):
        examined += 1
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        changed = False
        if "coding_mode" not in metadata:
            metadata["coding_mode"] = "refine"
            changed = True
        if "reasoning_tokens" not in metadata:
            metadata["reasoning_tokens"] = None
            changed = True
        if "openai_request_id" not in metadata:
            metadata["openai_request_id"] = None
            changed = True
        if "openai_response_id" not in metadata:
            metadata["openai_response_id"] = None
            changed = True

        request_tokens = metadata.get("request_tokens")
        response_tokens = metadata.get("response_tokens")
        if isinstance(request_tokens, (int, float)) and isinstance(response_tokens, (int, float)):
            usage = {}
            if metadata.get("reasoning_tokens") is not None:
                usage["reasoning_tokens"] = metadata["reasoning_tokens"]
            estimated_cost = calculate_request_cost(
                settings,
                usage,
                int(request_tokens),
                int(response_tokens),
            )
            if estimated_cost is not None and metadata.get("request_cost_usd") is None:
                metadata["request_cost_usd"] = estimated_cost
                changed = True

        if changed:
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated += 1
    return {
        "examined": examined,
        "updated": updated,
    }


def send_llm_request_details(prompt: str, settings: dict, llm_client=None) -> tuple[str, dict]:
    resolved_settings = dict(settings)
    resolved_api_key = resolve_api_key(settings.get("api_key"))
    resolved_settings["api_key"] = resolved_api_key

    if llm_client is not None:
        if hasattr(llm_client, "chat"):
            response = llm_client.chat(prompt=prompt, settings=resolved_settings)
            return response, {}
        if callable(llm_client):
            response = llm_client(prompt, resolved_settings)
            return response, {}
        raise TypeError("llm_client must be callable or provide a chat(prompt, settings) method.")

    provider = str(resolved_settings.get("provider", "openai")).lower()
    if provider not in {"openai", "openai-compatible"}:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    endpoint = resolved_settings.get("endpoint", "https://api.openai.com/v1/chat/completions")
    model = resolved_settings.get("model")
    if not model:
        raise ValueError("LanguageModelSettings.model is required.")

    reasoning = resolved_settings.get("reasoning")
    effort = None
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(
                "reasoning.effort must be low, medium, high, xhigh, or max."
            )
    elif resolved_settings.get("reasoning_effort"):
        effort = resolved_settings["reasoning_effort"]
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(
                "reasoning_effort must be low, medium, high, xhigh, or max."
            )

    api_format = resolved_settings.get("api_format")
    if api_format is None:
        api_format = "responses" if endpoint.rstrip("/").endswith("/responses") else "chat_completions"

    if api_format == "responses":
        payload = {
            "model": model,
            "input": prompt,
        }
        if effort is not None:
            payload["reasoning"] = {"effort": effort}
    elif api_format == "chat_completions":
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if effort is not None:
            payload["reasoning_effort"] = effort
    else:
        raise ValueError("api_format must be chat_completions or responses.")

    if "temperature" in resolved_settings:
        payload["temperature"] = resolved_settings["temperature"]

    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resolved_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=int(resolved_settings.get("timeout", 300))) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            raise OSError(
                "The LLM endpoint rejected the API key (HTTP 401 Unauthorized). "
                "Verify the key and endpoint/model settings."
            ) from error
        details = error.read().decode("utf-8", errors="replace").strip()
        raise OSError(
            f"The LLM endpoint returned HTTP {error.code}"
            + (f": {details}" if details else "")
        ) from error
    except TimeoutError as error:
        raise TimeoutError(
            f"The LLM request timed out after {resolved_settings.get('timeout', 300)} seconds "
            "while reading the response."
        ) from error
    except URLError as error:
        reason = getattr(error, "reason", error)
        raise OSError(f"The LLM request could not connect: {reason}") from error

    if api_format == "responses":
        if isinstance(data.get("output_text"), str):
            usage = dict(data.get("usage", {}) or {})
            usage["response_id"] = data.get("id")
            usage["request_id"] = data.get("request_id")
            return data["output_text"], usage
        try:
            for item in data["output"]:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        usage = dict(data.get("usage", {}) or {})
                        usage["response_id"] = data.get("id")
                        usage["request_id"] = data.get("request_id")
                        return content["text"], usage
        except (KeyError, IndexError, TypeError):
            pass
        raise OSError("The LLM response did not contain output_text.")
    try:
        usage = dict(data.get("usage", {}) or {})
        usage["response_id"] = data.get("id")
        usage["request_id"] = data.get("request_id")
        return data["choices"][0]["message"]["content"], usage
    except (KeyError, IndexError, TypeError) as error:
        raise OSError("The LLM response did not contain choices[0].message.content.") from error


def send_llm_request(prompt: str, settings: dict, llm_client=None) -> str:
    response, _ = send_llm_request_details(prompt, settings, llm_client)
    return response


def extract_python_code(raw_response: str) -> str:
    response = raw_response.strip()
    fence_lines = response.splitlines()
    for index, line in enumerate(fence_lines):
        if line.strip().lower() in {"```python", "```py"}:
            closing = None
            for closing_index in range(index + 1, len(fence_lines)):
                if fence_lines[closing_index].strip() == "```":
                    closing = closing_index
                    break
            if closing is not None:
                response = "\n".join(fence_lines[index + 1:closing]).strip()
                break
    try:
        ast.parse(response)
    except SyntaxError as error:
        raise ValueError(f"The LLM response does not contain valid Python: {error}") from error
    return response + "\n"


def test_python_in_sandbox(
    code: str,
    project_directory: str | Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    project_path = Path(project_directory).expanduser().resolve()
    del project_path
    source_directory = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="pysys-sandbox-") as temporary_directory:
        sandbox = Path(temporary_directory)
        generated = sandbox / "generated_model.py"
        generated.write_text(code, encoding="utf-8")
        for filename in ("pysys.py", "plotting.py", "opcloud.py", "ai_services.py"):
            source = source_directory / filename
            if source.is_file():
                shutil.copy2(source, sandbox / filename)
        return subprocess.run(
            [sys.executable, str(generated)],
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )


def code_store_directory(project_directory: str | Path) -> Path:
    project_path = Path(project_directory).expanduser().resolve()
    params_path = project_path / "Params" / "params.json"
    if not params_path.is_file():
        raise ValueError(f"Project params file does not exist: {params_path}")
    with params_path.open("r", encoding="utf-8") as params_file:
        project_params = json.load(params_file)
    artifacts = project_params.get("Artifacts", {})
    code_store = artifacts.get("Code") if isinstance(artifacts, dict) else None
    if not isinstance(code_store, str) or not code_store.strip():
        raise ValueError("Params.Artifacts.Code must contain a relative or absolute path.")
    project_name = project_params.get("ProjectName")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = project_path.name
    code_path = Path(code_store).expanduser()
    if not code_path.is_absolute():
        code_path = project_path / code_path
    if code_path.name.casefold() != project_name.strip().casefold():
        code_path = code_path / project_name.strip()
    return code_path.resolve()


def copy_code_resources(project_directory: str | Path, code_directory: str | Path) -> list[Path]:
    project_path = Path(project_directory).expanduser().resolve()
    code_path = Path(code_directory).expanduser().resolve()
    code_path.mkdir(parents=True, exist_ok=True)
    params_path = project_path / "Params" / "params.json"
    with params_path.open("r", encoding="utf-8") as params_file:
        project_params = json.load(params_file)
    resources = project_params.get("CodeResources", [])
    if not isinstance(resources, list):
        raise ValueError("Params.CodeResources must contain a list of filenames.")

    source_directory = Path(__file__).resolve().parent
    copied = []
    for resource in resources:
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("Params.CodeResources entries must be filenames.")
        destination = code_path / resource
        destination.parent.mkdir(parents=True, exist_ok=True)

        candidates = [
            project_path / "Resources" / resource,
            project_path / resource,
            source_directory / resource,
        ]
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise ValueError(f"Code resource does not exist: {resource}")
        if resource.casefold() != "build.ps1" and destination.is_file():
            continue
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def run_python_module(
    code_file: str | Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    code_path = Path(code_file).expanduser().resolve()
    if not code_path.is_file():
        raise OSError(f"Python module does not exist: {code_path}")
    try:
        return subprocess.run(
            [sys.executable, str(code_path)],
            cwd=code_path.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"Python module timed out after {timeout} seconds.") from error


class OPM2PySYSAgent:
    """Standby agent that converts an OPM HTML model to a PySYS module."""

    def __init__(
        self,
        project_directory: str | Path,
        base_json: str | Path | None = None,
    ):
        self.project_directory = Path(project_directory).expanduser().resolve()
        self.project_directory.mkdir(parents=True, exist_ok=True)
        if base_json is None:
            base_json = (
                self.project_directory
                / "Agents"
                / "OPM2PySYS"
                / "Instructions"
                / "base.json"
            )
        self.base_json = Path(base_json).expanduser().resolve()
        self.active = False

    def activate(self) -> "OPM2PySYSAgent":
        if not self.base_json.is_file():
            raise ValueError(f"Agent instruction file does not exist: {self.base_json}")
        self.active = True
        return self

    def convert(
        self,
        opm_model: str | Path,
        target_file: str | Path | None = None,
        llm_client=None,
        sandbox_timeout: int = 30,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        reasoning_effort: str | None = None,
        existing_code: str | None = None,
        code_mode: str = "regenerate",
        input_cost_usd_per_million: float | None = None,
        cached_input_cost_usd_per_million: float | None = None,
        output_cost_usd_per_million: float | None = None,
    ) -> dict:
        if not self.active:
            raise RuntimeError("The OPM2PySYS agent is not active. Call activate() first.")
        model_path = Path(opm_model).expanduser().resolve()
        if not model_path.is_file():
            raise ValueError(f"OPM model file does not exist: {model_path}")

        prompt = resolve_instruction_prompt(
            self.base_json,
            project_directory=self.project_directory,
        )
        model_html = model_path.read_text(encoding="utf-8")
        params_path = self.project_directory / "Params" / "params.json"
        if not params_path.is_file():
            raise ValueError(f"Project params file does not exist: {params_path}")
        with params_path.open("r", encoding="utf-8") as params_file:
            project_params = json.load(params_file)
        artifacts = project_params.get("Artifacts", {})
        images_relative = artifacts.get("Images") if isinstance(artifacts, dict) else None
        if not isinstance(images_relative, str) or not images_relative.strip():
            images_relative = "Artifacts/Images"
        images_path = Path(images_relative).expanduser()
        if not images_path.is_absolute():
            images_path = self.project_directory / images_path
        model_html, removed_base64_images, saved_images = strip_base64_images(
            model_html,
            images_path.resolve(),
            link_prefix=str(images_path.resolve()),
        )
        prompt += "\n\nOPM MODEL HTML:\n" + model_html
        if code_mode not in {"regenerate", "refine"}:
            raise ValueError("code_mode must be regenerate or refine.")
        if code_mode == "refine":
            if existing_code is None:
                code_mode = "regenerate"
            else:
                prompt += (
                    "\n\nExisting Python code to refine:\n"
                    "Build on top of this code. Preserve compatible behavior and resources "
                    "while applying only changes required by the model and instructions.\n\n"
                    "```python\n"
                    + existing_code
                    + "\n```\n"
                )

        params_path = self.project_directory / "Params" / "params.json"
        if not params_path.is_file():
            raise ValueError(f"Project params file does not exist: {params_path}")
        with params_path.open("r", encoding="utf-8") as params_file:
            project_params = json.load(params_file)
        artifacts = project_params.get("Artifacts", {})
        requests_relative = artifacts.get("Requests") if isinstance(artifacts, dict) else None
        if not isinstance(requests_relative, str) or not requests_relative.strip():
            raise ValueError("Params.Artifacts.Requests must contain a path.")
        requests_path = Path(requests_relative).expanduser()
        if not requests_path.is_absolute():
            requests_path = self.project_directory / requests_path
        requests_directory = requests_path.resolve()
        requests_directory.mkdir(parents=True, exist_ok=True)
        request_directory = _timestamp_request_directory(requests_directory)
        (request_directory / "request.md").write_text(prompt, encoding="utf-8")

        settings = load_agent_settings(self.base_json, self.project_directory)
        if api_key:
            settings["api_key"] = api_key
        if model:
            settings["model"] = model
        if endpoint:
            settings["endpoint"] = endpoint
        if reasoning_effort:
            settings["reasoning"] = {"effort": reasoning_effort}
        if input_cost_usd_per_million is not None:
            settings["input_cost_usd_per_million"] = input_cost_usd_per_million
        if cached_input_cost_usd_per_million is not None:
            settings["cached_input_cost_usd_per_million"] = cached_input_cost_usd_per_million
        if output_cost_usd_per_million is not None:
            settings["output_cost_usd_per_million"] = output_cost_usd_per_million
        request_timestamp = datetime.now(timezone.utc)
        print(
            f"Starting LLM request for {code_mode} code generation "
            f"(model={settings.get('model', 'unknown')}). "
            f"{format_estimate(requests_directory, code_mode, prompt, settings)}",
            flush=True,
        )
        try:
            raw_response, usage = send_llm_request_details(prompt, settings, llm_client=llm_client)
        except (OSError, TimeoutError) as error:
            (request_directory / "response.md").write_text(str(error), encoding="utf-8")
            write_request_metadata(
                request_directory,
                prompt,
                str(error),
                request_timestamp,
                datetime.now(timezone.utc),
                settings,
                coding_mode=code_mode,
            )
            raise
        if not isinstance(raw_response, str):
            raise TypeError("The LLM client must return a string response.")
        (request_directory / "response.md").write_text(raw_response, encoding="utf-8")
        metadata_path = write_request_metadata(
            request_directory,
            prompt,
            raw_response,
            request_timestamp,
            datetime.now(timezone.utc),
            settings,
            usage,
            coding_mode=code_mode,
        )

        python_code = extract_python_code(raw_response)
        test_result = test_python_in_sandbox(
            python_code,
            self.project_directory,
            timeout=sandbox_timeout,
        )
        if test_result.returncode != 0:
            details = test_result.stderr.strip() or test_result.stdout.strip()
            raise RuntimeError(
                "Generated Python failed in the sandbox."
                + (f"\n{details}" if details else "")
            )

        code_directory = code_store_directory(self.project_directory)
        if target_file is None:
            target_file = project_params.get("OutputFile")
            if not isinstance(target_file, str) or not target_file.strip():
                raise ValueError("Params.OutputFile must contain a filename or path.")
        destination = Path(target_file).expanduser()
        if not destination.is_absolute():
            destination = code_directory / destination
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(python_code, encoding="utf-8")
        copy_code_resources(self.project_directory, code_directory)

        return {
            "project": self.project_directory,
            "request": request_directory / "request.md",
            "response": request_directory / "response.md",
            "metadata": metadata_path,
            "metrics": format_completion_metrics(metadata_path),
            "target": destination,
            "test": test_result,
            "code_mode": code_mode,
            "removed_base64_images": removed_base64_images,
            "saved_images": [str(path) for path in saved_images],
        }


def activate_opm2pysys_agent(
    project_directory: str | Path,
    base_json: str | Path | None = None,
) -> OPM2PySYSAgent:
    agent = OPM2PySYSAgent(project_directory, base_json=base_json)
    return agent.activate()
