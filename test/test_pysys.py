import unittest
import threading
import tempfile
import os
import xml.etree.ElementTree as ET
from unittest.mock import patch
from pathlib import Path

import pandas as pd
import plotting
import pysys


class AttributeMetadataTests(unittest.TestCase):
    def test_metadata_contains_class_objects(self):
        self.assertIs(pysys.MODEL_ATTRS["THINGS"]["type"], pysys.THING)
        for key in ("PARTS", "ATTRIBUTES", "ORGANS"):
            with self.subTest(key=key):
                self.assertIs(pysys.THING_ATTRS[key]["type"], pysys.OBJECT)
                self.assertIs(pysys.OBJECT_ATTRS[key]["type"], pysys.OBJECT)
                self.assertIs(pysys.PROCESS_ATTRS[key]["type"], pysys.OBJECT)
        for key in ("SUBPROCESSES", "METHODS", "STEPS"):
            with self.subTest(key=key):
                self.assertIs(pysys.THING_ATTRS[key]["type"], pysys.PROCESS)
                self.assertIs(pysys.OBJECT_ATTRS[key]["type"], pysys.PROCESS)
                self.assertIs(pysys.PROCESS_ATTRS[key]["type"], pysys.PROCESS)
        for key in ("STATE", "STATES"):
            self.assertIs(pysys.OBJECT_ATTRS[key]["type"], pysys.STATE)

    def test_subclasses_use_their_own_metadata(self):
        state = pysys.STATE(NAME="ready", VALUE=1)
        process = pysys.PROCESS(NAME="run", CYCLE=2.0)
        obj = pysys.OBJECT(NAME="item", STATES=[state], METHODS=[process])
        model = pysys.MODEL(NAME="model", ID="example", THINGS=[obj])
        system = pysys.SYSTEM(NAME="system")

        self.assertIs(state.REF_ATTRS, pysys.STATE_ATTRS)
        self.assertIs(process.REF_ATTRS, pysys.PROCESS_ATTRS)
        self.assertIs(obj.REF_ATTRS, pysys.OBJECT_ATTRS)
        self.assertIs(model.REF_ATTRS, pysys.MODEL_ATTRS)
        self.assertIs(system.REF_ATTRS, pysys.SYSTEM_ATTRS)
        self.assertIs(obj.STATES[0], state)
        self.assertIs(obj.METHODS[0], process)
        self.assertIs(model.THINGS[0], obj)
        self.assertEqual(model.URL, "https://opcloud.systems/load/example?export-html=true")

    def test_thing_uses_thing_metadata(self):
        part = pysys.OBJECT(NAME="part")
        thing = pysys.THING(NAME="parent", PARTS=[part])
        self.assertIs(thing.REF_ATTRS, pysys.THING_ATTRS)
        self.assertIs(thing.PARTS[0], part)


class ArchiveTests(unittest.TestCase):
    def test_sampling_schedule_includes_duration_endpoint(self):
        self.assertEqual(pysys.sampling_offsets(10, 1), list(range(11)))
        self.assertEqual(pysys.sampling_offsets(2.5, 1), [0, 1, 2, 2.5])
        self.assertEqual(pysys.sampling_offsets(0.5, 1), [0, 0.5])
        for duration, interval in ((0, 1), (10, 0), (float("inf"), 1)):
            with self.subTest(duration=duration, interval=interval), self.assertRaises(ValueError):
                pysys.sampling_offsets(duration, interval)

    def test_demo_records_endpoint_with_nondivisible_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "history.csv"
            with patch("builtins.input", side_effect=["0.1", "0.1", "0.25"]), \
                 patch.object(pysys, "plot_state_history", wraps=plotting.plot_state_history) as plot, \
                 patch.object(plotting.webbrowser, "open", return_value=True) as browser, \
                 patch.object(pysys.random, "randint", return_value=4):
                pysys.demo(output_dir=directory)
            frame = pd.read_csv(output)
            self.assertEqual(len(frame), 4)
            self.assertEqual(frame["SysState"].iloc[0], 5)
            self.assertLess(frame["ts"].iloc[-1], 0.4)
            self.assertGreaterEqual(frame["ts"].iloc[-1], 0.23)
            self.assertEqual(len(plot.call_args.args[0]), len(frame))
            self.assertEqual(plot.call_args.kwargs["output_dir"], Path(directory).resolve())
            files = list(Path(directory).glob("*.svg"))
            self.assertEqual(len(files), 1)
            ET.parse(files[0])
            browser.assert_called_once_with(files[0].resolve().as_uri())

    def test_archives_previous_inputs_across_cycles(self):
        manager = pysys.SYSTEM(name="manager")
        self.assertEqual(pysys.archive_attr(manager, "EnvState", "EnvState_history"), {})
        with patch.object(pysys.time, "time", side_effect=[100.0, 101.0]):
            for value in (8, 4):
                manager.set_inputs(EnvState=value)
                manager.set_inputs(**pysys.archive_attr(manager, "EnvState", "EnvState_history"))
        self.assertEqual(manager.get_inputs()["EnvState_history"], [
            {"EnvState": 8, "timestamp": 100.0},
            {"EnvState": 4, "timestamp": 101.0},
        ])

    def test_explicit_none_is_archived(self):
        manager = pysys.SYSTEM(name="manager")
        manager.set_inputs(SysState=None)
        with patch.object(pysys.time, "time", return_value=123.0):
            history = pysys.archive_attr(manager, "SysState", "SysState_history")
        self.assertEqual(history, {"SysState_history": [{"SysState": None, "timestamp": 123.0}]})

    def test_archived_mutable_values_are_snapshots(self):
        manager = pysys.SYSTEM(name="manager")
        value = {"items": [1]}
        manager.set_inputs(EnvState=value)
        history = pysys.archive_attr(manager, "EnvState", "EnvState_history")
        value["items"].append(2)
        self.assertEqual(history["EnvState_history"][0]["EnvState"], {"items": [1]})

    def test_non_list_history_is_rejected(self):
        manager = pysys.SYSTEM(name="manager")
        manager.set_inputs(EnvState=1, EnvState_history="invalid")
        with self.assertRaisesRegex(TypeError, "EnvState_history must be a list"):
            pysys.archive_attr(manager, "EnvState", "EnvState_history")

    def test_manager_archives_previous_sample_each_cycle(self):
        manager = pysys.SYSTEM(name="manager")
        samples = iter(({"EnvState": 8, "SysState": 1}, {"EnvState": 4, "SysState": 5},
                        {"EnvState": 3, "SysState": 6}))
        manager.activate(
            do=[
                {"func": pysys.archive_attr, "args": [manager, "EnvState", "EnvState_history"]},
                {"func": pysys.archive_attr, "args": [manager, "SysState", "SysState_history"]},
                {"func": lambda: next(samples)},
            ],
            cycle=0,
            cycles=3,
        )
        manager.thread.join(timeout=3)
        self.assertFalse(manager.thread.is_alive())
        inputs = manager.get_inputs()
        self.assertEqual([x["EnvState"] for x in inputs["EnvState_history"]], [8, 4])
        self.assertEqual([x["SysState"] for x in inputs["SysState_history"]], [1, 5])
        self.assertEqual((inputs["EnvState"], inputs["SysState"]), (3, 6))

    def test_final_archive_includes_tenth_sample(self):
        manager = pysys.SYSTEM(name="manager")
        samples = iter({"EnvState": i, "SysState": 9 - i} for i in range(10))
        manager.activate(
            do=[
                {"func": pysys.archive_attr, "args": [manager, "EnvState", "EnvState_history"]},
                {"func": pysys.archive_attr, "args": [manager, "SysState", "SysState_history"]},
                {"func": lambda: next(samples)},
            ],
            cycle=0,
            cycles=10,
        )
        manager.thread.join(timeout=3)
        self.assertFalse(manager.thread.is_alive())
        for name in ("EnvState", "SysState"):
            manager.set_inputs(**pysys.archive_attr(manager, name, f"{name}_history"))
        inputs = manager.get_inputs()
        self.assertEqual([entry["EnvState"] for entry in inputs["EnvState_history"]], list(range(10)))
        self.assertEqual([entry["SysState"] for entry in inputs["SysState_history"]], list(reversed(range(10))))


class StateHistoryPlotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        previous_cwd = os.getcwd()
        os.chdir(temp.name)
        self.addCleanup(os.chdir, previous_cwd)

    def test_plot_output_directories_and_unique_files(self):
        frame = pd.DataFrame({"time": [0, 1], "value": [1, 2]})
        with patch.object(plotting.webbrowser, "open", return_value=True):
            first = plotting.plot_state_history([0, 1], {"state": [1, 2]})
            second = plotting.plot_state_history([0, 1], {"state": [1, 2]})
            custom = plotting.plot_df(frame, "time", ["value"], output_dir=Path("custom") / "nested")
        self.assertEqual(first.parent, (Path.cwd() / "results").resolve())
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file() and second.is_file())
        self.assertEqual(custom.parent, (Path.cwd() / "custom" / "nested").resolve())
        self.assertTrue(custom.is_file())

    def test_unusable_output_directory_raises(self):
        path = Path("not-a-directory")
        path.write_text("existing", encoding="utf-8")
        with self.assertRaises(OSError):
            plotting.plot_state_history([0], {"state": [1]}, output_dir=path)

    def test_plots_both_histories_on_shared_elapsed_time_axis(self):
        with patch.object(plotting.webbrowser, "open", return_value=True) as open_browser:
            path = pysys.plot_state_history([100.0, 101.0, 102.0, 103.0], {
                "EnvState": [None, 8, None, 4], "SysState": [None, None, 1, None]})
        open_browser.assert_called_once_with(path.as_uri())
        root = ET.parse(path).getroot()
        ns = {"svg": "http://www.w3.org/2000/svg"}
        paths = root.findall(".//svg:path", ns)
        lines = {item.attrib["stroke"]: item.attrib["d"] for item in paths
                 if item.attrib.get("stroke") in ("#1565c0", "#c62828")
                 and item.attrib.get("fill") == "none"}
        self.assertEqual(lines["#1565c0"], "M 306.67 80.00 M 740.00 285.71")
        self.assertEqual(lines["#c62828"], "M 523.33 440.00")
        texts = [node.text for node in root.findall(".//svg:text", ns)]
        self.assertIn("EnvState", texts)
        self.assertIn("SysState", texts)
        self.assertIn("Timestamp (seconds)", texts)

    def test_state_history_ticks_match_actual_irregular_timestamps(self):
        ts = [1000.125, 1001.25, 1004.5]
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_state_history(ts, {"State": [1, 2, 3]})
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        texts = {node.text: float(node.attrib["x"]) for node in root.iter(ns + "text")
                 if node.text in {str(t) for t in ts}}
        circles = list(root.iter(ns + "circle"))
        self.assertEqual(set(texts), {str(t) for t in ts})
        for timestamp, circle in zip(ts, circles):
            self.assertAlmostEqual(texts[str(timestamp)], float(circle.attrib["cx"]), places=2)
        self.assertLess(float(circles[1].attrib["cx"]) - float(circles[0].attrib["cx"]),
                        float(circles[2].attrib["cx"]) - float(circles[1].attrib["cx"]))

    def test_state_history_single_timestamp_does_not_invent_ticks(self):
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_state_history([100.5], {"State": [1]})
        root = ET.parse(path).getroot()
        texts = [node.text for node in root.iter("{http://www.w3.org/2000/svg}text")]
        self.assertEqual(texts.count("100.5"), 1)

    def test_plot_df_multiple_series_and_missing_values(self):
        df = pd.DataFrame({"time": [10, 12, 15], "A": [1, None, 3],
                           "B": [3, 2, 1], "C": [2, 3, 4]})
        with patch.object(plotting.webbrowser, "open", return_value=True) as browser:
            path = pysys.plot_df(df, "time", ["A", "B", "C"])
        browser.assert_called_once_with(path.as_uri())
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        texts = [node.text for node in root.iter(ns + "text")]
        self.assertTrue({"time", "A", "B", "C", "10", "15"}.issubset(texts))
        lines = {node.attrib["stroke"]: node.attrib["d"] for node in root.iter(ns + "path")
                 if node.attrib.get("stroke") in ("#1565c0", "#c62828", "#2e7d32")
                 and node.attrib.get("fill") == "none"}
        self.assertEqual(lines["#1565c0"].count("M "), 2)
        self.assertEqual(lines["#c62828"].count("L "), 2)
        self.assertEqual(len(lines), 3)

    def test_plot_df_datetime_axis_and_single_point(self):
        df = pd.DataFrame({"when": pd.to_datetime(["2025-01-01T00:00:00Z"]),
                           "temperature": [42]})
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_df(df, "when", ["temperature"])
        root = ET.parse(path).getroot()
        texts = [node.text for node in root.iter("{http://www.w3.org/2000/svg}text")]
        self.assertIn("when (seconds since 2025-01-01T00:00:00+00:00)", texts)

    def test_plot_df_invalid_inputs(self):
        df = pd.DataFrame({"x": [1, 2], "y": [2, 3]})
        with self.assertRaises(KeyError):
            pysys.plot_df(df, "x", ["missing"])
        with self.assertRaises(ValueError):
            pysys.plot_df(df, "x", [])
        with self.assertRaises(ValueError):
            pysys.plot_df(df.iloc[:0], "x", ["y"])
        with self.assertRaises(ValueError):
            pysys.plot_df(pd.DataFrame({"x": [None], "y": [1]}), "x", ["y"])
        with self.assertRaises(ValueError):
            pysys.plot_df(pd.DataFrame({"x": [1], "y": ["bad"]}), "x", ["y"])

    def test_empty_histories_report_error(self):
        with self.assertRaisesRegex(ValueError, "No state history"):
            pysys.plot_state_history([], {})

    def test_one_history_and_custom_name(self):
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_state_history([7], {"temp<&": [42]})
        root = ET.parse(path).getroot()
        texts = [node.text for node in root.iter("{http://www.w3.org/2000/svg}text")]
        self.assertIn("temp<&", texts)

    def test_missing_values_break_step_line(self):
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_state_history([1, 2, 3], {"EnvState": [1, None, 2]})
        root = ET.parse(path).getroot()
        paths = root.findall(".//{http://www.w3.org/2000/svg}path")
        line = next(p for p in paths if p.attrib.get("stroke") == "#1565c0"
                    and p.attrib.get("fill") == "none")
        self.assertEqual(line.attrib["d"].count("M "), 2)
        self.assertNotIn(" H ", line.attrib["d"])

    def test_invalid_values_and_timestamps_are_rejected(self):
        for ts, history in (([1], [float("inf")]), ([2, 1], [1, 2]), ([1, 2], [1])):
            with self.subTest(ts=ts, history=history), self.assertRaises(ValueError):
                pysys.plot_state_history(ts, {"EnvState": history})

    def test_browser_failure_reports_saved_path(self):
        with patch.object(plotting.webbrowser, "open", return_value=False):
            with self.assertRaisesRegex(RuntimeError, r"Could not open.*\.svg"):
                pysys.plot_state_history([1], {"EnvState": [1]})

    def test_state_mean_has_a_path_and_full_series(self):
        frame = pd.DataFrame({"ts": [100.0, 101.0, 102.0],
                              "EnvState": [2, 4, 6], "SysState": [7, 5, 3]})
        frame["StateMean"] = frame[["EnvState", "SysState"]].mean(axis=1)
        with patch.object(plotting.webbrowser, "open", return_value=True):
            path = pysys.plot_state_history(frame["ts"].tolist(), {
                name: frame[name].tolist() for name in ("EnvState", "SysState", "StateMean")
            })
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        self.assertIn("StateMean", [node.text for node in root.iter(ns + "text")])
        mean = next(node for node in root.iter(ns + "path")
                    if node.attrib.get("stroke") == "#2e7d32"
                    and node.attrib.get("fill") == "none")
        self.assertEqual(mean.attrib["d"].count("H "), 2)


class SystemInputTests(unittest.TestCase):
    def test_initialization_and_independent_mappings(self):
        state_variable = pysys.OBJECT(name="Number")
        first = pysys.SYSTEM(name="Environment", id="Env", attributes=[state_variable])
        second = pysys.SYSTEM(name="Other")

        self.assertEqual(first.ID, "Env")
        self.assertEqual(first.get_inputs(), {"state": "OFF", "is_running": False})
        self.assertEqual(first.OUTPUTS, {})
        self.assertEqual(first.ATTRIBUTES, [state_variable])
        first.set_inputs(temperature=20)
        first.OUTPUTS["result"] = 1
        self.assertNotIn("temperature", second.INPUTS)
        self.assertEqual(second.OUTPUTS, {})

    def test_supplied_mappings_are_preserved_and_copied(self):
        inputs = {"temperature": 20}
        outputs = {"result": 1}
        system = pysys.SYSTEM(name="System", inputs=inputs, outputs=outputs)
        self.assertEqual(system.get_inputs("temperature"), {"temperature": 20})
        self.assertEqual(system.OUTPUTS, outputs)
        self.assertIsNot(system.INPUTS, inputs)
        self.assertIsNot(system.OUTPUTS, outputs)
        self.assertNotIn("state", inputs)

    def test_non_mapping_inputs_are_rejected(self):
        with self.assertRaisesRegex(TypeError, "INPUTS must be a dictionary"):
            pysys.SYSTEM(name="System", inputs=[1, 2])

    def test_activation_executes_actions_and_stores_results(self):
        system = pysys.SYSTEM(name="System")
        called = threading.Event()

        def action():
            called.set()
            return {"result": 42}

        system.activate(do=[{"func": action}], cycle=0, cycles=1)
        system.thread.join(timeout=3)
        self.assertFalse(system.thread.is_alive())
        self.assertTrue(called.is_set())
        self.assertEqual(system.get_inputs("state", "result"), {"state": "ON", "result": 42})
        system.deactivate()
        self.assertEqual(system.get_inputs("state", "is_running"), {"state": "OFF", "is_running": False})


if __name__ == "__main__":
    unittest.main()
