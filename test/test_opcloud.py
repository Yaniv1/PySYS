import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import opcloud


URL = "https://opcloud.systems/load/-example"


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
            self.assertEqual(url, URL + "?export-html=true")
            return True

        def wait(*args, **kwargs):
            calls.append("wait")
            return download, False

        with patch.object(opcloud.webbrowser, "open", side_effect=open_browser), \
             patch.object(opcloud, "wait_for_export", side_effect=wait):
            result = opcloud.get_model_spec(URL, self.downloads)
        self.assertEqual(calls, ["open", "wait"])
        self.assertEqual(result["destination"], download)
        self.assertEqual(opcloud.load_html_file(result["destination"]), "model")

    def test_invalid_inputs_are_rejected_before_browser_opens(self):
        with patch.object(opcloud.webbrowser, "open") as browser:
            with self.assertRaises(ValueError):
                opcloud.get_model_spec(URL, self.downloads, timeout=0)
            with self.assertRaises(ValueError):
                opcloud.get_model_spec(URL, self.downloads / "missing")
            with self.assertRaises(ValueError):
                opcloud.get_model_spec(
                    URL, self.downloads, target=str(self.downloads / "missing" / "model.html")
                )
            browser.assert_not_called()

    def test_browser_failure_does_not_wait(self):
        with patch.object(opcloud.webbrowser, "open", return_value=False), \
             patch.object(opcloud, "wait_for_export") as wait:
            with self.assertRaisesRegex(OSError, "Open this URL manually"):
                opcloud.get_model_spec(URL, self.downloads)
            wait.assert_not_called()

    def test_timeout_even_when_dialog_was_confirmed(self):
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(None, True)):
            with self.assertRaisesRegex(TimeoutError, "No completed HTML export"):
                opcloud.get_model_spec(URL, self.downloads, timeout=1)

    def test_filename_target_copies_download(self):
        download = self.downloads / "original.html"
        download.write_text("model", encoding="utf-8")
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)):
            result = opcloud.get_model_spec(URL, self.downloads, target="chosen")
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
            result = opcloud.get_model_spec(URL, self.downloads, target=str(target_directory))
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
            result = opcloud.get_model_spec(URL, browser_downloads, target=str(target), timeout=1)
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
                URL, browser_downloads, target=str(target / "chosen.html"), timeout=1
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

    def test_unavailable_automation_instructs_manual_directory_selection(self):
        with patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "Desktop", None), \
             patch.object(opcloud, "wait_for_export", return_value=(None, False)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(TimeoutError):
                opcloud.get_model_spec(URL, self.downloads, target="chosen.html", timeout=1)
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
            result = opcloud.get_model_spec(URL, self.downloads, timeout=1)
        self.assertEqual(result["destination"], download)

    def test_cli_reports_saved_path(self):
        download = self.downloads / "model.html"
        download.write_text("model", encoding="utf-8")
        args = ["opcloud.py", f"source={URL}", f"downloads_dir={self.downloads}"]
        with patch.object(opcloud.sys, "argv", args), \
             patch.object(opcloud.webbrowser, "open", return_value=True), \
             patch.object(opcloud, "wait_for_export", return_value=(download, False)), \
             patch.object(opcloud, "close_export_tab", return_value=False), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(opcloud.main(), 0)
        self.assertIn(f"Saved HTML export to {download}", output.getvalue())


if __name__ == "__main__":
    unittest.main()
