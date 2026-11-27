import contextlib
import io
import json
import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import opcloud
import ai_services


OPCLOUD_URL = "https://opcloud.systems/load/-example"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.downloads = Path(self.temp.name).resolve()

    def test_browser_opens_before_wait_and_returns_download(self):
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        calls = []

        def open_browser(url, new):
            calls.append("open")
            self.assertEqual(url, OPCLOUD_URL + "?export-html=true")
            return True

        def wait(*args, **kwargs):
            calls.append("wait")
            return download, False

        with patch.object(opcloud.webbrowser, "open", side_effect=open_browser), \
             patch.object(opcloud, "wait_for_export", side_effect=wait):
            result = opcloud.get_model_spec(OPCLOUD_URL, self.downloads)
        self.assertEqual(calls, ["open", "wait"])
        self.assertEqual(result["destination"], download)
        self.assertEqual(opcloud.load_html_file(result["destination"]), "model")

    def test_invalid_inputs_are_rejected_before_browser_opens(self):
        with patch.object(opcloud.webbrowser, "open") as browser:
            with self.assertRaises(ValueError):
                opcloud.get_model_spec(OPCLOUD_URL, self.downloads, timeout=0)
            with self.assertRaises(ValueError):
                opcloud.get_model_spec(OPCLOUD_URL, self.downloads / "missing")
            browser.assert_not_called()

    def test_browser_failure_does_not_wait(self):
        with patch.object(opcloud.webbrowser, "open", return_value=False), \
             patch.object(opcloud, "wait_for_export") as wait:
            with self.assertRaisesRegex(OSError, "Open this URL manually"):
                opcloud.get_model_spec(OPCLOUD_URL, self.downloads)
            wait.assert_not_called()

    def test_timeout_even_when_dialog_was_confirmed(self):
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(None, True)):
            with self.assertRaisesRegex(TimeoutError, "No completed HTML export"):
                opcloud.get_model_spec(OPCLOUD_URL, self.downloads, timeout=1)

    def test_reload_sanitizes_downloaded_html_and_extracts_images(self):
        target_directory = self.downloads / "Model"
        image_directory = target_directory / "Artifacts" / "Images"
        download = self.downloads / "model.html"
        download.write_text(
            '<html><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"></html>',
            encoding="utf-8",
        )
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)), \
             patch.object(opcloud, "close_export_tab", return_value=True):
            result = opcloud.get_model_spec(
                OPCLOUD_URL,
                self.downloads,
                target=str(target_directory),
                image_directory=image_directory,
            )

        sanitized = result["destination"].read_text(encoding="utf-8")
        self.assertNotIn("iVBORw0KGgo", sanitized)
        self.assertIn("embedded-0001.png", sanitized)
        self.assertTrue((image_directory / "embedded-0001.png").is_file())

    def test_filename_target_copies_download(self):
        download = self.downloads / "original.html"
        download.write_text("model", encoding="utf-8")
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)):
            result = opcloud.get_model_spec(OPCLOUD_URL, self.downloads, target="chosen")
        self.assertEqual(result["destination"], self.downloads / "chosen.html")
        self.assertEqual(result["destination"].read_text(encoding="utf-8"), "model")
        self.assertTrue(download.exists())

    def test_target_directory_keeps_download_filename(self):
        target_directory = self.downloads / "target"
        target_directory.mkdir()
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, True)):
            result = opcloud.get_model_spec(OPCLOUD_URL, self.downloads, target=str(target_directory))
        self.assertEqual(result["destination"], target_directory / "model.html")
        self.assertEqual(result["destination"].read_text(encoding="utf-8"), "model")
        self.assertTrue(download.exists())
        self.assertTrue(result["save_dialog_confirmed"])

    def test_browser_default_download_is_copied_to_target(self):
        browser_downloads = self.downloads / "Browser Downloads"
        target = self.downloads / "Target"
        browser_downloads.mkdir()
        target.mkdir()
        source = browser_downloads / "model.html"
        existing = target / "model.html"
        existing.write_text("existing", encoding="utf-8")

        def open_browser(url, new):
            source.write_text("export", encoding="utf-8")
            timestamp = opcloud.time.time() + 1
            os.utime(source, (timestamp, timestamp))
            return True

        with patch.object(opcloud.webbrowser, "open", side_effect=open_browser), \
             patch.object(opcloud, "save_from_dialog", return_value=False), \
             patch.object(opcloud.time, "sleep"):
            result = opcloud.get_model_spec(OPCLOUD_URL, browser_downloads, target=str(target), timeout=1)
        self.assertEqual(result["destination"], target / "model (1).html")
        self.assertEqual(result["destination"].read_text(encoding="utf-8"), "export")
        self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
        self.assertEqual(source.read_text(encoding="utf-8"), "export")

    def test_browser_default_download_can_be_copied_to_target_filename(self):
        browser_downloads = self.downloads / "Browser Downloads"
        target = self.downloads / "Target"
        browser_downloads.mkdir()
        target.mkdir()
        source = browser_downloads / "model.html"

        def open_browser(url, new):
            source.write_text("export", encoding="utf-8")
            timestamp = opcloud.time.time() + 1
            os.utime(source, (timestamp, timestamp))
            return True

        with patch.object(opcloud.webbrowser, "open", side_effect=open_browser), \
             patch.object(opcloud, "save_from_dialog", return_value=False), \
             patch.object(opcloud.time, "sleep"):
            result = opcloud.get_model_spec(
                OPCLOUD_URL, browser_downloads, target=str(target / "chosen.html"), timeout=1
            )
        self.assertEqual(result["destination"], target / "chosen.html")
        self.assertEqual(result["destination"].read_text(encoding="utf-8"), "export")
        self.assertTrue(source.exists())

    def test_old_browser_download_is_not_used(self):
        browser_downloads = self.downloads / "Browser Downloads"
        target = self.downloads / "Target"
        browser_downloads.mkdir()
        target.mkdir()
        source = browser_downloads / "model.html"
        source.write_text("old export", encoding="utf-8")
        os.utime(source, (1, 1))
        with patch.object(opcloud, "save_from_dialog", return_value=False), \
             patch.object(opcloud.time, "monotonic", side_effect=[0, 0, 2]), \
             patch.object(opcloud.time, "sleep"):
            result = opcloud.wait_for_export(browser_downloads, 2, 1)
        self.assertEqual(result, (None, False))

    def test_confirmed_dialog_does_not_finish_before_download(self):
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        with patch.object(opcloud, "save_from_dialog", return_value=True), \
             patch.object(opcloud, "latest_download", return_value=download), \
             patch.object(opcloud.time, "sleep"):
            result = opcloud.wait_for_export(self.downloads, 0, 1)
        self.assertEqual(result, (download, True))

    def test_downloads_directory_is_passed_to_save_dialog(self):
        downloads = self.downloads / "My Drive" / "Model Files"
        downloads.mkdir(parents=True)
        with patch.object(opcloud, "save_from_dialog", return_value=False) as save, \
             patch.object(opcloud.time, "monotonic", side_effect=[0, 0, 2]), \
             patch.object(opcloud.time, "sleep"):
            opcloud.wait_for_export(downloads, 0, 1)
        save.assert_called_once_with(downloads)

    def test_save_dialog_ignores_transient_uia_wrapper_failure(self):
        window = Mock()
        window.descendants.side_effect = RuntimeError("element_info control type unknown")
        desktop = Mock()
        desktop.windows.return_value = [window]
        with patch.object(opcloud.sys, "platform", "win32"), \
             patch.object(opcloud, "Desktop", return_value=desktop), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(opcloud.save_from_dialog(self.downloads))
        self.assertIn("Temporary UIA wrapper failure", output.getvalue())

    def test_unavailable_automation_instructs_manual_directory_selection(self):
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "Desktop", None), \
             patch.object(opcloud, "wait_for_export", return_value=(None, False)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(TimeoutError):
                opcloud.get_model_spec(OPCLOUD_URL, self.downloads, target="chosen.html", timeout=1)
        self.assertIn("Select the directory", output.getvalue())
        self.assertIn(str(self.downloads), output.getvalue())

    def test_save_dialog_uses_downloads_directory_with_spaces(self):
        directory = self.downloads / "My Drive" / "Model Files"
        directory.mkdir(parents=True)
        filename = Mock()
        filename.element_info.control_type = "Edit"
        filename.element_info.automation_id = "1001"
        filename.is_visible.return_value = True
        filename.is_enabled.return_value = True
        filename.get_value.side_effect = ["model", str(directory / "model.html")]
        button = Mock()
        button.element_info.control_type = "Button"
        button.element_info.automation_id = "1"
        button.window_text.return_value = "Save"
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        window = Mock()
        window.descendants.return_value = [button, filename]
        desktop = Mock()
        desktop.windows.return_value = [window]
        keyboard = Mock()
        with patch.object(opcloud.sys, "platform", "win32"), \
             patch.object(opcloud, "Desktop", return_value=desktop), \
             patch.object(opcloud, "keyboard", keyboard), \
             patch.object(opcloud.time, "sleep"):
            self.assertTrue(opcloud.save_from_dialog(directory))
        filename.set_edit_text.assert_called_once_with(str(directory / "model.html"))
        filename.type_keys.assert_called_once_with("{END}{SPACE}{BACKSPACE}")
        button.click_input.assert_called_once()

    def test_browser_and_actual_wait_find_export(self):
        download = self.downloads / "model.html"

        def open_browser(url, new):
            download.write_text("model", encoding="utf-8")
            timestamp = opcloud.time.time() + 1
            os.utime(download, (timestamp, timestamp))
            return True

        with patch.object(opcloud.webbrowser, "open", side_effect=open_browser), \
             patch.object(opcloud, "save_from_dialog", return_value=False), \
             patch.object(opcloud.time, "sleep"):
            result = opcloud.get_model_spec(OPCLOUD_URL, self.downloads, timeout=1)
        self.assertEqual(result["destination"], download)

    def test_cli_reports_saved_path(self):
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        args = ["opcloud.py", f"source={OPCLOUD_URL}", f"downloads_dir={self.downloads}"]
        with patch.object(opcloud.sys, "argv", args), \
             patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)), \
             patch.object(opcloud, "close_export_tab", return_value=False), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(opcloud.main(), 0)
        self.assertIn(f"Saved HTML export to {download}", output.getvalue())

    def test_http_401_reports_authentication_without_key(self):
        error = HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"invalid api key"}'),
        )
        with patch.object(ai_services, "urlopen", side_effect=error):
            with self.assertRaisesRegex(OSError, "HTTP 401 Unauthorized"):
                ai_services.send_llm_request(
                    "prompt",
                    {
                        "provider": "openai",
                        "model": "test-model",
                        "api_key": "never-print-this",
                        "endpoint": "https://api.openai.com/v1/chat/completions",
                    },
                )

    def test_llm_read_timeout_is_reported_clearly(self):
        with patch.object(ai_services, "urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaisesRegex(TimeoutError, "timed out after 300 seconds"):
                ai_services.send_llm_request(
                    "prompt",
                    {
                        "provider": "openai",
                        "model": "test-model",
                        "api_key": "test-key",
                        "timeout": 300,
                    },
                )

    def test_llm_request_includes_reasoning_effort(self):
        response = Mock()
        response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.object(ai_services, "urlopen", return_value=response) as request:
            result = ai_services.send_llm_request(
                "prompt",
                {
                    "provider": "openai",
                    "model": "test-model",
                    "api_key": "test-key",
                    "reasoning": {"effort": "high"},
                },
            )

        self.assertEqual(result, "ok")
        sent_request = request.call_args.args[0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertNotIn("reasoning", payload)

    def test_request_metadata_and_previous_estimate(self):
        request_directory = Path(self.temp.name) / "Request"
        request_directory.mkdir()
        request_timestamp = ai_services.datetime(2026, 11, 23, 10, 0, 0, tzinfo=ai_services.timezone.utc)
        response_timestamp = ai_services.datetime(2026, 11, 23, 10, 0, 12, tzinfo=ai_services.timezone.utc)

        metadata_path = ai_services.write_request_metadata(
            request_directory,
            "request text",
            "response text",
            request_timestamp,
            response_timestamp,
            {"model": "gpt-6.2-sol"},
            usage={"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0125},
        )

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["request"], "request.md")
        self.assertEqual(metadata["response"], "response.md")
        self.assertEqual(metadata["request_tokens"], 100)
        self.assertEqual(metadata["response_tokens"], 50)
        self.assertEqual(metadata["model"], "gpt-6.2-sol")
        self.assertEqual(metadata["request_cost_usd"], 0.0125)
        self.assertEqual(metadata["coding_mode"], "refine")
        self.assertIsNone(metadata["openai_request_id"])
        self.assertIsNone(metadata["openai_response_id"])
        estimate = ai_services.estimate_previous_requests(request_directory.parent, "refine")
        self.assertEqual(estimate["duration_seconds"], 12.0)
        metrics = ai_services.format_completion_metrics(metadata_path)
        self.assertIn("Duration: 12.00s", metrics)
        self.assertIn("request tokens: 100", metrics)
        self.assertIn("response tokens: 50", metrics)
        self.assertIn("cost: $0.012500", metrics)

    def test_calculate_request_cost_from_pricing_and_usage(self):
        cost = ai_services.calculate_request_cost(
            {
                "input_cost_usd_per_million": 2.0,
                "cached_input_cost_usd_per_million": 0.5,
                "output_cost_usd_per_million": 8.0,
            },
            {"prompt_tokens_details": {"cached_tokens": 100}},
            request_tokens=1000,
            response_tokens=500,
        )
        self.assertAlmostEqual(cost, 0.00585, places=8)

    def test_gpt62_standard_and_long_context_cost_tiers(self):
        standard = ai_services.calculate_request_cost(
            {
                "input_cost_usd_per_million": 2.0,
                "cached_input_cost_usd_per_million": 0.10,
                "output_cost_usd_per_million": 10.0,
                "long_input_cost_usd_per_million": 4.0,
                "long_cached_input_cost_usd_per_million": 0.20,
                "long_output_cost_usd_per_million": 15.0,
            },
            {"prompt_tokens_details": {"cached_tokens": 100}},
            request_tokens=272_000,
            response_tokens=1000,
        )
        long_context = ai_services.calculate_request_cost(
            {
                "input_cost_usd_per_million": 2.0,
                "cached_input_cost_usd_per_million": 0.10,
                "output_cost_usd_per_million": 10.0,
                "long_input_cost_usd_per_million": 4.0,
                "long_cached_input_cost_usd_per_million": 0.20,
                "long_output_cost_usd_per_million": 15.0,
            },
            {"prompt_tokens_details": {"cached_tokens": 100}},
            request_tokens=272001,
            response_tokens=1000,
        )
        self.assertAlmostEqual(standard, 0.55381, places=8)
        self.assertAlmostEqual(long_context, 1.102624, places=8)

    def test_backfill_request_metrics_adds_missing_fields_and_cost(self):
        requests_directory = Path(self.temp.name) / "Requests"
        request_directory = requests_directory / "past"
        request_directory.mkdir(parents=True)
        (request_directory / "request.json").write_text(
            json.dumps({
                "request": "request.md",
                "response": "response.md",
                "request_timestamp": "2026-11-23T10:00:00Z",
                "response_timestamp": "2026-11-23T10:00:10Z",
                "request_tokens": 1000,
                "response_tokens": 500,
                "model": "gpt-6.2-sol",
                "request_cost_usd": None,
            }),
            encoding="utf-8",
        )

        result = ai_services.backfill_request_metrics(
            requests_directory,
            {
                "input_cost_usd_per_million": 2.0,
                "cached_input_cost_usd_per_million": 0.10,
                "output_cost_usd_per_million": 10.0,
            },
        )
        metadata = json.loads(
            (request_directory / "request.json").read_text(encoding="utf-8")
        )

        self.assertEqual(result["examined"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(metadata["coding_mode"], "refine")
        self.assertIsNone(metadata["reasoning_tokens"])
        self.assertEqual(metadata["request_cost_usd"], 0.007)

    def test_format_estimate_uses_prompt_and_pricing_not_historical_median(self):
        requests_directory = Path(self.temp.name) / "Requests"
        past = requests_directory / "past"
        past.mkdir(parents=True)
        past.joinpath("request.json").write_text(
            json.dumps({
                "coding_mode": "refine",
                "request_timestamp": "2026-11-23T10:00:00Z",
                "response_timestamp": "2026-11-23T10:10:00Z",
                "request_tokens": 100,
                "response_tokens": 100,
                "request_cost_usd": 99.0,
            }),
            encoding="utf-8",
        )
        prompt = "x" * 4000
        estimate = ai_services.format_estimate(
            requests_directory,
            "refine",
            prompt,
            {
                "input_cost_usd_per_million": 2.0,
                "cached_input_cost_usd_per_million": 0.10,
                "output_cost_usd_per_million": 10.0,
            },
        )
        self.assertIn("estimated tokens: 1000 request / 2000 response", estimate)
        self.assertNotIn("$99", estimate)
        self.assertIn("estimated cost: $0.0220", estimate)

    def test_coding_mode_separates_refine_and_regenerate_estimates(self):
        requests_directory = Path(self.temp.name) / "Requests"
        refine_directory = requests_directory / "refine"
        regenerate_directory = requests_directory / "regenerate"
        refine_directory.mkdir(parents=True)
        regenerate_directory.mkdir()
        timestamp = ai_services.datetime(2026, 11, 23, 10, 0, tzinfo=ai_services.timezone.utc)

        ai_services.write_request_metadata(
            refine_directory,
            "refine prompt",
            "refine response",
            timestamp,
            ai_services.datetime(2026, 11, 23, 10, 0, 10, tzinfo=ai_services.timezone.utc),
            {"model": "gpt-6.2-sol"},
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cost": 0.01,
                "response_id": "resp_refine",
            },
            coding_mode="refine",
        )
        ai_services.write_request_metadata(
            regenerate_directory,
            "regenerate prompt",
            "regenerate response",
            timestamp,
            ai_services.datetime(2026, 11, 23, 10, 0, 30, tzinfo=ai_services.timezone.utc),
            {"model": "gpt-6.2-sol"},
            usage={
                "prompt_tokens": 300,
                "completion_tokens": 100,
                "cost": 0.03,
                "response_id": "resp_regenerate",
            },
            coding_mode="regenerate",
        )

        refine_estimate = ai_services.estimate_previous_requests(requests_directory, "refine")
        regenerate_estimate = ai_services.estimate_previous_requests(requests_directory, "regenerate")

        self.assertEqual(refine_estimate["duration_seconds"], 10.0)
        self.assertEqual(regenerate_estimate["duration_seconds"], 30.0)
        regenerate_metadata = json.loads(
            (regenerate_directory / "request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(regenerate_metadata["coding_mode"], "regenerate")
        self.assertEqual(regenerate_metadata["openai_response_id"], "resp_regenerate")

    def test_api_key_is_read_from_file_only_when_sending_request(self):
        key_file = Path(self.temp.name) / "api-key.txt"
        key_file.write_text("  test-file-key\n", encoding="utf-8")
        settings = {
            "provider": "openai",
            "model": "test-model",
            "api_key": str(key_file),
        }

        self.assertEqual(settings["api_key"], str(key_file))
        resolved = ai_services.resolve_api_key(settings["api_key"])
        self.assertEqual(resolved, "test-file-key")
        self.assertEqual(settings["api_key"], str(key_file))

    def test_client_receives_resolved_key_but_settings_path_is_preserved(self):
        key_file = Path(self.temp.name) / "api-key.txt"
        key_file.write_text("test-file-key", encoding="utf-8")
        settings = {
            "provider": "openai",
            "model": "test-model",
            "api_key": str(key_file),
        }

        class MockClient:
            def chat(self, prompt, settings):
                self.prompt = prompt
                self.settings = dict(settings)
                return "ok"

        client = MockClient()
        result = ai_services.send_llm_request("prompt", settings, llm_client=client)

        self.assertEqual(result, "ok")
        self.assertEqual(client.settings["api_key"], "test-file-key")
        self.assertEqual(settings["api_key"], str(key_file))

    def test_missing_target_directory_is_created_before_copy(self):
        target = self.downloads / "new" / "nested"
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)):
            result = opcloud.get_model_spec(
                OPCLOUD_URL,
                self.downloads,
                target=str(target),
            )
        self.assertTrue(target.is_dir())
        self.assertEqual(result["destination"], target / "model.html")

    def test_missing_images_param_defaults_to_artifacts_images(self):
        project = Path(self.temp.name) / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "Project",
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                },
            }),
            encoding="utf-8",
        )

        self.assertEqual(
            opcloud.image_store_directory(project),
            (project / "Artifacts" / "Images").resolve(),
        )

    def test_absolute_artifact_code_location_is_not_relative_to_project(self):
        project = Path(self.temp.name) / "Project"
        code_location = Path(self.temp.name) / "External" / "Code"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "Project",
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": str(code_location),
                },
                "CodeResources": ["pysys.py"],
            }),
            encoding="utf-8",
        )

        self.assertEqual(
            ai_services.code_store_directory(project),
            (code_location / "Project").resolve(),
        )
        ai_services.copy_code_resources(project, ai_services.code_store_directory(project))
        self.assertTrue(((code_location / "Project") / "pysys.py").is_file())

    def test_project_resource_is_copied_instead_of_shared_resource(self):
        project = Path(self.temp.name) / "Project"
        code_location = Path(self.temp.name) / "External" / "Code"
        (project / "Params").mkdir(parents=True)
        (project / "Resources").mkdir()
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "Project",
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": str(code_location),
                },
                "CodeResources": ["pysys.py"],
            }),
            encoding="utf-8",
        )
        (project / "Resources" / "pysys.py").write_text(
            "# project-specific pysys version\n",
            encoding="utf-8",
        )

        code_directory = ai_services.code_store_directory(project)
        ai_services.copy_code_resources(project, code_directory)

        self.assertEqual(
            (code_directory / "pysys.py").read_text(encoding="utf-8"),
            "# project-specific pysys version\n",
        )

    def test_explicit_boolean_flags_are_parsed(self):
        self.assertTrue(opcloud.parse_explicit_bool("true", False))
        self.assertFalse(opcloud.parse_explicit_bool("false", True))
        self.assertTrue(opcloud.parse_explicit_bool(None, True))
        with self.assertRaisesRegex(ValueError, "true or false"):
            opcloud.parse_explicit_bool("sometimes", False)

    def test_latest_model_file_selects_newest_html(self):
        project = Path(self.temp.name) / "Project"
        models = project / "Artifacts" / "Models"
        models.mkdir(parents=True)
        (project / "Params").mkdir()
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Code": "Artifacts/Code",
                    "Requests": "Requests",
                },
            }),
            encoding="utf-8",
        )
        older = models / "older.html"
        newer = models / "newer.html"
        older.write_text("older", encoding="utf-8")
        newer.write_text("newer", encoding="utf-8")
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

        self.assertEqual(opcloud.latest_model_file(project), newer)

    def test_run_python_module_executes_from_code_directory(self):
        code_directory = Path(self.temp.name) / "Code"
        code_directory.mkdir()
        code_file = code_directory / "outcome.py"
        code_file.write_text(
            "from pathlib import Path\n"
            "print(Path.cwd().name)\n",
            encoding="utf-8",
        )

        result = ai_services.run_python_module(code_file, timeout=30)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "Code")

    def test_refine_prompt_includes_existing_code(self):
        project = Path(self.temp.name) / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                    "Images": "Artifacts/Images",
                },
                "OutputFile": "pysys_model.py",
            }),
            encoding="utf-8",
        )
        base = project / "Agents" / "OPM2PySYS" / "Instructions" / "base.json"
        base.parent.mkdir(parents=True)
        base.write_text(
            json.dumps({
                "Project": "Project",
                "Task": "Refine",
                "LanguageModelSettings": {"provider": "openai", "model": "test-model"},
            }),
            encoding="utf-8",
        )
        model = Path(self.temp.name) / "model.html"
        model.write_text("<html>model</html>", encoding="utf-8")

        class MockClient:
            def chat(self, prompt, settings):
                self.prompt = prompt
                return "```python\nprint('refined')\n```"

        client = MockClient()
        agent = ai_services.activate_opm2pysys_agent(project, base)
        result = agent.convert(
            model,
            target_file="pysys_model.py",
            llm_client=client,
            api_key="test-key",
            existing_code="print('existing')\n",
            code_mode="refine",
        )

        self.assertEqual(result["code_mode"], "refine")
        self.assertIn("print('existing')", client.prompt)
        self.assertIn("Build on top of this code", client.prompt)

    def test_base64_html_images_are_removed_from_llm_prompt(self):
        project = Path(self.temp.name) / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                },
                "OutputFile": "pysys_model.py",
            }),
            encoding="utf-8",
        )
        base = project / "Agents" / "OPM2PySYS" / "Instructions" / "base.json"
        base.parent.mkdir(parents=True)
        base.write_text(
            json.dumps({
                "Project": "Project",
                "Task": "Convert",
                "LanguageModelSettings": {"provider": "openai", "model": "test-model"},
            }),
            encoding="utf-8",
        )
        model = Path(self.temp.name) / "model.html"
        model.write_text(
            '<html><body><p>Diagram</p>'
            '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA">'
            '</body></html>',
            encoding="utf-8",
        )

        class MockClient:
            def chat(self, prompt, settings):
                self.prompt = prompt
                return "```python\nprint('safe')\n```"

        client = MockClient()
        agent = ai_services.activate_opm2pysys_agent(project, base)
        result = agent.convert(
            model,
            target_file="pysys_model.py",
            llm_client=client,
            api_key="test-key",
        )

        self.assertEqual(result["removed_base64_images"], 1)
        self.assertNotIn("iVBORw0KGgo", client.prompt)
        self.assertIn("embedded-0001.png", client.prompt)
        self.assertEqual(len(result["saved_images"]), 1)
        saved_image = Path(result["saved_images"][0])
        self.assertTrue(saved_image.is_file())
        self.assertGreater(saved_image.stat().st_size, 0)

    def test_regenerate_prompt_excludes_existing_code(self):
        project = Path(self.temp.name) / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                },
                "OutputFile": "pysys_model.py",
            }),
            encoding="utf-8",
        )
        base = project / "Agents" / "OPM2PySYS" / "Instructions" / "base.json"
        base.parent.mkdir(parents=True)
        base.write_text(
            json.dumps({
                "Project": "Project",
                "Task": "Regenerate",
                "LanguageModelSettings": {"provider": "openai", "model": "test-model"},
            }),
            encoding="utf-8",
        )
        model = Path(self.temp.name) / "model.html"
        model.write_text("<html>model</html>", encoding="utf-8")

        class MockClient:
            def chat(self, prompt, settings):
                self.prompt = prompt
                return "```python\nprint('regenerated')\n```"

        client = MockClient()
        agent = ai_services.activate_opm2pysys_agent(project, base)
        result = agent.convert(
            model,
            target_file="pysys_model.py",
            llm_client=client,
            api_key="test-key",
            existing_code="print('must-not-be-in-regenerate-prompt')\n",
            code_mode="regenerate",
        )

        self.assertEqual(result["code_mode"], "regenerate")
        self.assertNotIn("must-not-be-in-regenerate-prompt", client.prompt)
        self.assertNotIn("Existing Python code to refine:", client.prompt)

    def test_create_git_repository_in_code_directory(self):
        code_directory = Path(self.temp.name) / "Code"
        result = opcloud.setup_git_repo(code_directory, action="create")
        self.assertEqual(result["action"], "create")
        self.assertTrue((code_directory / ".git").is_dir())

        existing = opcloud.setup_git_repo(code_directory, action="clone", source="unused")
        self.assertEqual(existing["action"], "existing")

    def test_create_git_repository_bootstraps_existing_files(self):
        code_directory = Path(self.temp.name) / "Code"
        code_directory.mkdir()
        (code_directory / "existing.py").write_text("print('existing')\n", encoding="utf-8")

        result = opcloud.setup_git_repo(code_directory, action="create")

        self.assertEqual(result["action"], "create")
        self.assertTrue((code_directory / ".git").is_dir())
        self.assertEqual((code_directory / "existing.py").read_text(encoding="utf-8"), "print('existing')\n")
        self.assertIsInstance(result["preserved"], Path)
        self.assertTrue(result["preserved"].is_dir())
        status = subprocess.run(
            ["git", "-C", str(code_directory), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(status.stdout.strip(), "")

    def test_clone_git_repository_bootstraps_existing_files_and_commits_them(self):
        source = Path(self.temp.name) / "Source"
        source.mkdir()
        subprocess.run(["git", "-C", str(source), "init"], capture_output=True, check=True)
        (source / "tracked.txt").write_text("tracked", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
            capture_output=True,
            check=True,
        )
        code_directory = Path(self.temp.name) / "Code"
        code_directory.mkdir()
        (code_directory / "existing.py").write_text("print('existing')\n", encoding="utf-8")

        result = opcloud.setup_git_repo(code_directory, action="clone", source=source)

        self.assertEqual(result["action"], "clone")
        self.assertEqual((code_directory / "tracked.txt").read_text(encoding="utf-8"), "tracked")
        self.assertEqual((code_directory / "existing.py").read_text(encoding="utf-8"), "print('existing')\n")
        status = subprocess.run(
            ["git", "-C", str(code_directory), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(status.stdout.strip(), "")

    def test_clone_local_git_repository_into_empty_code_directory(self):
        source = Path(self.temp.name) / "Source"
        source.mkdir()
        subprocess.run(["git", "-C", str(source), "init"], capture_output=True, check=True)
        (source / "tracked.txt").write_text("tracked", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
            capture_output=True,
            check=True,
        )
        code_directory = Path(self.temp.name) / "Code"

        result = opcloud.setup_git_repo(code_directory, action="clone", source=source)

        self.assertEqual(result["action"], "clone")
        self.assertEqual((code_directory / "tracked.txt").read_text(encoding="utf-8"), "tracked")
        self.assertTrue((code_directory / ".git").is_dir())

    def test_project_code_folder_is_project_specific(self):
        project = Path(self.temp.name) / "FlightReservation"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "FlightReservation",
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": str(Path(self.temp.name) / "CodeRoot"),
                },
                "CodeResources": ["pysys.py"],
            }),
            encoding="utf-8",
        )

        code_directory = opcloud.code_store_directory(project)

        self.assertEqual(code_directory, (Path(self.temp.name) / "CodeRoot" / "FlightReservation").resolve())

    def test_template_build_script_is_a_project_resource(self):
        params = json.loads(
            (Path(opcloud.__file__).resolve().parent
             / "Projects" / "__Template__" / "Params" / "params.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("build.ps1", params["CodeResources"])
        self.assertTrue(
            (Path(opcloud.__file__).resolve().parent
             / "Projects" / "__Template__" / "build.ps1").is_file()
        )

    def test_build_script_is_copied_to_project_code_folder(self):
        project = Path(self.temp.name) / "Project"
        code_directory = Path(self.temp.name) / "CodeRoot" / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Resources").mkdir()
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "Project",
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": str(Path(self.temp.name) / "CodeRoot"),
                },
                "CodeResources": ["build.ps1"],
            }),
            encoding="utf-8",
        )
        (project / "Resources" / "build.ps1").write_text(
            "Write-Host 'project build'\n",
            encoding="utf-8",
        )

        ai_services.copy_code_resources(project, code_directory)

        self.assertEqual(
            (code_directory / "build.ps1").read_text(encoding="utf-8"),
            "Write-Host 'project build'\n",
        )

    def test_project_creation_copies_only_missing_template_items(self):
        template = Path(self.temp.name) / "Template"
        (template / "Agents").mkdir(parents=True)
        (template / "Agents" / "base.txt").write_text("template", encoding="utf-8")
        (template / "keep.txt").write_text("new", encoding="utf-8")
        destination = Path(self.temp.name) / "Project"
        destination.mkdir()
        (destination / "keep.txt").write_text("existing", encoding="utf-8")

        result = opcloud.copy_missing_items(template, destination)

        self.assertEqual(result, destination)
        self.assertEqual((destination / "keep.txt").read_text(), "existing")
        self.assertEqual(
            (destination / "Agents" / "base.txt").read_text(),
            "template",
        )

    def test_explicit_target_is_project_root_and_model_store_is_nested(self):
        template = Path(self.temp.name) / "Template"
        (template / "Params").mkdir(parents=True)
        (template / "Params" / "params.json").write_text(
            json.dumps({
                "ProjectName": "__Template__",
                "DefaultProjectRoot": str(Path(self.temp.name) / "Default"),
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                },
                "OutputFile": "pysys_model.py",
                "CodeResources": [],
            }),
            encoding="utf-8",
        )
        (template / "Agents" / "Nested").mkdir(parents=True)
        (template / "Agents" / "Nested" / "instruction.txt").write_text(
            "instruction",
            encoding="utf-8",
        )
        target = Path(self.temp.name) / "FlightReservation"

        project = opcloud.copy_missing_items(template, target)
        model_store = opcloud.model_store_directory(project)
        code_store = opcloud.code_store_directory(project)

        self.assertEqual(project, target)
        self.assertEqual(model_store, target / "Artifacts" / "Models")
        self.assertEqual(code_store, target / "Artifacts" / "Code" / "__Template__")
        self.assertEqual(
            (project / "Agents" / "Nested" / "instruction.txt").read_text(),
            "instruction",
        )

    def test_instruction_prompt_resolves_file_parameters(self):
        instruction_directory = Path(self.temp.name) / "Instructions"
        instruction_directory.mkdir()
        model = instruction_directory / "model.html"
        model.write_text("<html>model</html>", encoding="utf-8")
        base = instruction_directory / "base.json"
        base.write_text(
            json.dumps({
                "Project": "Example",
                "OpcloudModel": "model.html",
                "Specific_Instructions": {
                    "type": "file",
                    "path": "specific.md",
                },
            }),
            encoding="utf-8",
        )
        (instruction_directory / "specific.md").write_text(
            "Specific instruction",
            encoding="utf-8",
        )

        prompt = opcloud.resolve_instruction_prompt(base, Path(self.temp.name))

        self.assertIn("<html>model</html>", prompt)
        self.assertIn("Specific instruction", prompt)

    def test_agent_records_raw_request_and_response_and_writes_python(self):
        project = Path(self.temp.name) / "Project"
        (project / "Params").mkdir(parents=True)
        (project / "Params" / "params.json").write_text(
            json.dumps({
                "Artifacts": {
                    "Models": "Artifacts/Models",
                    "Requests": "Requests",
                    "Code": "Artifacts/Code",
                },
                "OutputFile": "pysys_model.py",
                "CodeResources": [],
            }),
            encoding="utf-8",
        )
        base = project / "Agents" / "OPM2PySYS" / "Instructions" / "base.json"
        base.parent.mkdir(parents=True)
        base.write_text(
            json.dumps({
                "Project": "Project",
                "Task": "Convert",
                "LanguageModelSettings": {
                    "provider": "openai",
                    "model": "test-model",
                },
            }),
            encoding="utf-8",
        )
        model = Path(self.temp.name) / "model.html"
        model.write_text("<html>model</html>", encoding="utf-8")

        class MockClient:
            def chat(self, prompt, settings):
                self.prompt = prompt
                self.settings = settings
                return "```python\nprint('sandbox ok')\n```"

        client = MockClient()
        agent = opcloud.activate_opm2pysys_agent(project, base)
        result = agent.convert(
            model,
            target_file="generated.py",
            llm_client=client,
            api_key="test-api-key",
        )

        self.assertEqual(result["test"].returncode, 0)
        self.assertEqual(client.settings["api_key"], "test-api-key")
        self.assertEqual((result["request"]).read_text(encoding="utf-8"),
                         client.prompt)
        self.assertIn("```python", (result["response"]).read_text(encoding="utf-8"))
        self.assertEqual(
            (result["target"]).read_text(encoding="utf-8"),
            "print('sandbox ok')\n",
        )
        request_folders = list((project / "Requests").iterdir())
        self.assertEqual(len(request_folders), 1)


if __name__ == "__main__":
    unittest.main()
