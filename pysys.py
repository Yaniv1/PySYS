from __future__ import annotations

import copy
import datetime as dt
import os
import sys
import json
import threading
import time
import uuid
import math
import random
import copy
import inspect
import tempfile
import webbrowser
from functools import wraps
from html import escape
from numbers import Real
from pathlib import Path
import pandas as pd

# from LogAnalyzer.LogAnalyzer.frontend.streamlit_app.api_client import get
import opcloud


ESSESNCES = ["physical", "informatical"]
AFFILIATIONS = ["systemic", "environmental"]


CORE_ATTRS = {
    "NAME": {"type": str, "card": "1", "semantics": "The name of the THING."},
    "ID": {"type": str, "card": "1", "default": lambda: str(uuid.uuid4()), "semantics": "The unique identifier of the THING."},
}


class THING:

    def __init__(self, **kwargs):
        if not hasattr(self, "REF_ATTRS"):
            self.REF_ATTRS = THING_ATTRS
        self.set(**kwargs)

    def set(self, **kwargs):

        for core_key in CORE_ATTRS:
            if not any(key.upper() == core_key for key in kwargs):
                if "default" in CORE_ATTRS[core_key]:
                    kwargs[core_key.lower()] = CORE_ATTRS[core_key]["default"]() if callable(CORE_ATTRS[core_key]["default"]) else CORE_ATTRS[core_key]["default"]

        for key, kdef in self.REF_ATTRS.items():
            if key.lower() not in kwargs and "default" in kdef:
                kwargs[key.lower()] = kdef["default"]() if callable(kdef["default"]) else kdef["default"]

        for key, value in kwargs.items():
            if key.upper() in self.REF_ATTRS:
                if value is not None:
                    if self.REF_ATTRS[key.upper()]["card"] == "*":
                        if not isinstance(value, list):
                            value = [value]
                        value = [v if isinstance(v, self.REF_ATTRS[key.upper()]["type"]) else self.REF_ATTRS[key.upper()]["type"](v) for v in value] if value else []
                    elif self.REF_ATTRS[key.upper()]["card"] == "1":
                        if isinstance(value, list):
                            if len(value) != 1:
                                raise ValueError(f"Expected a single value for key: {key}")
                            value = value[0]
                    setattr(self, key.upper(), value)
                
            else:
                if key.upper() in self.REF_ATTRS:
                    raise KeyError(f"Case mismatch for key: {key}")
                else:
                    raise KeyError(f"Unknown key: {key}")

    def append(self, **kwargs):
        for key, value in kwargs.items():
            if key.upper() in self.REF_ATTRS:
                if self.REF_ATTRS[key.upper()]["card"] != "*":
                    raise ValueError(f"Cannot append to non-list attribute: {key}")
                current_value = getattr(self, key.upper(), [])
                if not isinstance(current_value, list):
                    current_value = [current_value] if current_value is not None else []
                if not isinstance(value, list):
                    value = [value]
                setattr(self, key.upper(), current_value + value)
            else:
                raise KeyError(f"Unknown key: {key}")

    def get(self):
        
        d = {k: getattr(self, k) for k in self.REF_ATTRS if k in self.__dict__}
        for k,v in d.items():
            if isinstance(v, THING) and hasattr(v, "get"):
                d[k] = v.get()
            elif isinstance(v, list):
                d[k] = [item.get() if isinstance(item, THING) and hasattr(item, "get") else item for item in v]
            elif isinstance(v, dict):
                d[k] = {sub_k: sub_v.get() if isinstance(sub_v, THING) and hasattr(sub_v, "get") else sub_v for sub_k, sub_v in v.items()}
        return d

    def get_item(self, group, **kwargs):
        if group.upper() not in self.REF_ATTRS:
            raise KeyError(f"Unknown group: {group}")
        group_value = getattr(self, group.upper(), None)
        if group_value is None:
            return None
        for k,v in kwargs.items():
            if type(v) is not list:
                kwargs[k] = [v]
        if isinstance(group_value, list):
            match = [item for item in group_value if all(getattr(item, k.upper(), None) in v for k, v in kwargs.items())]
            if len(match) == 1:
                return match[0]            
            return match if match else None
        elif isinstance(group_value, THING):
            if all(getattr(group_value, k.upper(), None) in v for k, v in kwargs.items()):
                return group_value
            return None
        return None

import opcloud


class MODEL(THING):

    
    def __init__(self, **kwargs):
        self.REF_ATTRS = MODEL_ATTRS
        super().__init__(**kwargs)
        self.URL = opcloud.export_url(opcloud.construct_url(self.ID))

    def load(self):        
        self.spec_info = opcloud.get_model_spec(self.URL)
        self.spec = opcloud.load_html_file(self.spec_info.get("destination"))

    def generate_pysys_code(self):
        """
        Generate PySYS code based on the loaded HTML specification.
        """
        if not hasattr(self, "spec"):
            raise ValueError("Specification not loaded. Call load() first.")

        
        # Implement the code generation logic here based on self.spec
        # This is a placeholder implementation
        return f"# PySYS code generated for model {self.ID}"

    

class STATE(THING):
    def __init__(self, **kwargs):
        """
        Represents a state that can optionally include a unit.
        Examples:  STATE(1500, "m"), STATE("apron")
        """
        self.REF_ATTRS = STATE_ATTRS
        super().__init__(**kwargs)


class OBJECT(THING):
    """
    Represents an object within the system.
    """
    def __init__(self, **kwargs):
        self.REF_ATTRS = OBJECT_ATTRS
        super().__init__(**kwargs)


def BEHAVIOR(behavior):
    """
    Decorator for user-defined behavior functions.
    Automatically provides:
    - caller locals as context
    - timing / duration measurement
    - optional logging
    """
    @wraps(behavior)
    def wrapper(model, *args, **kwargs):
        # ----------------------------
        # Retrieve caller locals
        # ----------------------------
        caller_locals = inspect.currentframe().f_back.f_locals
        process = caller_locals.get("self")  # PROCESS instance
        if process is None:
            raise ValueError("Cannot find calling PROCESS instance in caller frame")

        owner_obj = caller_locals.get("self_object", None) or (args[0] if args else None)
        context = caller_locals  # just return caller locals as context for now

        # Start timing
        start_time = dt.datetime.now()

        # Optional start logging
        if getattr(process, "verbose", True):
            print(f"[{start_time}] Starting process '{process.NAME}' (ID: {process.ID})")

        # Call user behavior
        kwargs = {**model, **context, **kwargs}
        result = behavior(*args, **kwargs)

        # End timing
        end_time = dt.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Optional end logging
        if getattr(process, "verbose", True):
            print(f"[{end_time}] Process '{process.NAME}' completed in {duration:.4f} seconds")

        return result

    return wrapper

class PROCESS(THING):
    """
    Represents a process within the system.
    """
    def __init__(self, **kwargs):
        self.REF_ATTRS = PROCESS_ATTRS
        super().__init__(**kwargs)
    
    def run(self, *args, **kwargs):        
        return self.BEHAVIOR(*args, **kwargs)
        
    def activate(self, *args, **kwargs):
        """Start or restart the process."""
        self.is_running = True
        # Reset results if needed
        self.results = None
        # Start thread if not alive
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run_cyclically,
                                            args=args, kwargs=kwargs, daemon=True)
            self.thread.start()
    
    def deactivate(self):
        """Stop the process loop without removing it from finished_procs."""
        self.is_running = False
        
    def run_cyclically(self, *args, **kwargs):
        while self.is_running:
            self.run(*args, **kwargs)
            time.sleep(getattr(self, "CYCLE", 1.0))  # default cycle 1 second
        


# defining a class SYSTEM that represents a system with a name and an ID. 
class SYSTEM(THING):
    
    # constructor method that initializes the SYSTEM object with a name and an ID. If no name is provided, it defaults to an empty string. 
    # If no ID is provided, it generates a unique ID using the uuid module.
    # the constructor's first parameter is always self, which refers to the instance of the class being created. 
    # This allows us to access and modify the instance's attributes and methods within the class.
    def __init__(self, **kwargs):
        self.REF_ATTRS = SYSTEM_ATTRS                
        super().__init__(**kwargs)
        # the constructor calls another method of the class which deactivates the system - we don't know how yet.
        # but this is a common pattern to separate concerns and behaviors - what vs how.
        self.deactivate()
                
    # a method that takes any number of keyword arguments and sets the corresponding attributes of the SYSTEM instance to the provided values.
    def set_inputs(self, **kwargs):
        for k,v in kwargs.items():
            self.INPUTS[k] = v

    def get_inputs(self, *keys):
        if keys:
            return {k: self.INPUTS.get(k) for k in keys if k in self.INPUTS}
        return {k: self.INPUTS.get(k) for k in self.INPUTS}
            
    # a method that returns a dictionary containing the attributes of the SYSTEM instance.
    # if the attributes parameter is provided, it filters the output to include only those attributes; otherwise, it returns all attributes.
    def provide_output(self, attributes=[]):
        return {k:v for k,v in self.__dict__.items() if k in attributes or attributes==[]}
    
    # a method that activates the system by setting its state to 'ON', starting a new thread to run the system's main loop, and setting the _running attribute to True.
    def activate(self, do=[{"func":print, "args":[], "kwargs":{}}], cycle=1.0, cycles=10):        
        self.set_inputs(state='ON', is_running=True, do=do, cycle=cycle, cycles=cycles)
        # a thread is created to run the system's main loop in the background.
        # a thread is a separate flow of execution that allows the program to perform multiple tasks concurrently. 
        # In this case, the thread will run the run() method of the SYSTEM class, which contains the main loop of the system.
        self.thread = threading.Thread(target=self.run, kwargs={"cycle": cycle, "cycles": cycles}, daemon=True)
        self.thread.start()       
        
    # a method that deactivates the system by setting its state to 'OFF' and setting the _running attribute to False, which will stop the main loop in the run() method.
    def deactivate(self):
        self.set_inputs(state='OFF', is_running=False)
        
    # a method that runs the main loop of the system. 
    # It takes a list of functions to execute (do) and a cycle time (cycle) as parameters. The loop continues to run as long as the _running attribute is True.
    def run(self, cycle=1.0, cycles=10):
        self.cycle = cycle
        cycle_count = 0
        while self.INPUTS.get('is_running', False) and (cycle_count < cycles):
            # runs the loop as long as the _running attribute is True. 
            # The getattr() function is used to safely access the _running attribute, providing a default value of False if it doesn't exist.
            self.pclock = time.time()
            print(f"{self.NAME} running cycle {cycle_count+1}/{cycles} at {self.pclock} milliseconds with cycle time {self.cycle} seconds.")
            # execute each function in the do list, passing each function its own arguments and keyword arguments. 
            for f in self.INPUTS.get('do', [{"func":print, "args":[], "kwargs":{}}]):
                r = f.get("func", print)(*f.get("args", []), **f.get("kwargs", {}))
                # if the return value of the function is a dictionary, it calls the get_input method to update the SYSTEM instance's attributes with the key-value pairs from the returned dictionary.
                if type(r) is dict:
                    self.set_inputs(**r)
                # the results of each step function are stored in the variable r, which can be used for further processing or analysis if needed.
            # the time.sleep() function is used to pause the execution of the loop for a duration calculated as the difference between the specified cycle time and the actual time taken for the current iteration of the loop.
            cycle_count+=1
            self.clock = time.time()
            elapsed = self.clock - self.pclock
            print(f"{elapsed=} idle={cycle - elapsed}")
            time.sleep(max(0, cycle - elapsed))


THING_ATTRS = {
    **CORE_ATTRS,
    "ESSENCE": {"type": str, "card": "1", "default": ESSESNCES[0], "semantics": "The essence of the THING."},
    "AFFILIATION": {"type": str, "card": "1", "default": AFFILIATIONS[0], "semantics": "The affiliation of the THING."},
    "PARTS": {"type": OBJECT, "card": "*", "semantics": "A list of OBJECT items that the parent THING consists of if it is an object"},
    "ATTRIBUTES": {"type": OBJECT, "card": "*", "semantics": "A list of OBJECT items that the parent THING exhibits."},
    "SUBPROCESSES": {"type": PROCESS, "card": "*", "semantics": "A list of PROCESS items that the parent THING consists of if it is a process."},
    "METHODS": {"type": PROCESS, "card": "*", "semantics": "A list of PROCESS items that the parent THING exhibits."},
    "ORGANS": {"type": OBJECT, "card": "*", "semantics": "A list of OBJECT items that the parent THING zooms into."},
    "STEPS": {"type": PROCESS, "card": "*", "semantics": "A list of PROCESS items that the parent THING zooms into."}
}

MODEL_ATTRS = {
    **CORE_ATTRS,
    "URL": {"type": str, "card": "1", "default": lambda id: opcloud.export_url(opcloud.construct_url(id)), "semantics": "The URL of the MODEL."},
    "THINGS": {"type": THING, "card": "*", "semantics": "A list of THING items contained in the MODEL."},
}

OBJECT_ATTRS = {
    **THING_ATTRS,
    "STATES": {"type": STATE, "card": "*", "semantics": "A list of STATE items that the OBJECT can have."},
    "STATE": {"type": STATE, "card": "1", "semantics": "The current STATE of the OBJECT."}
}

PROCESS_ATTRS = {
    **THING_ATTRS,
    "CYCLE": {"type": float, "card": "1", "default": 1.0, "semantics": "The cycle time in seconds for the PROCESS to run cyclically."},
    "BEHAVIOR": {"type": callable, "card": "1", "default": print, "semantics": "The behavior function of the PROCESS."}
}

STATE_ATTRS = {
    **CORE_ATTRS,
    "VALUE": {"type": object, "card": "1", "semantics": "The value of the STATE."},
    "UNIT": {"type": str, "card": "1", "semantics": "The unit of the STATE, if applicable."}
}

SYSTEM_ATTRS = {
    **THING_ATTRS,
    "INPUTS": {"type": dict, "card": "1", "default": dict, "semantics": "A mapping of inputs to the SYSTEM."},
    "OUTPUTS": {"type": dict, "card": "1", "default": dict, "semantics": "A mapping of outputs from the SYSTEM."}
}


# --------------------------
# Baseline Scenario
# --------------------------
def SCENARIO(   System, 
                Environment,
                name = "Baseline Scenario",
                steps = [],
                freq = 1.0):
    """
    Generic scenario:
    """
    
    print(name)

    def stepwrap(step, System, Environment):

        print(f"Step {i}:")

        System, Environment = step(System, Environment)

        time.sleep(freq)
        
        return System, Environment

    results = []

    for i, step in enumerate(steps, start=1):
        System, Environment = stepwrap(step, System, Environment)        

        result = {
            "Step": i,

            "SystemState": System.get_item("ATTRIBUTES", name=STATE_VAR).STATE,
            "EnvironmentState": Environment.get_item("ATTRIBUTES", name=STATE_VAR).STATE
        }

        pprint(result, sort_dicts=False)
        results.append(result)

    pprint(results, sort_dicts=False)

    return results


       

# --------------------------
# Example usage
# --------------------------
STATE_VAR = 'Number'
STATE_VAR_STATES = list(range(10))


def rand_state(EnvStateVar='EnvState'):

    new_env_state_idx = random.randint(0,len(STATE_VAR_STATES)-1)
    new_env_state = STATE_VAR_STATES[new_env_state_idx]

    return {EnvStateVar: new_env_state}


def get_states(Environment, MySystem, EnvStateVar='EnvState', SysStateVar='SysState', print_result=False):

    result = {
        EnvStateVar: Environment.get_inputs().get(EnvStateVar),
        SysStateVar: MySystem.get_inputs().get(SysStateVar),
    }
    if print_result:
        pprint(result, sort_dicts=False)
    return result

def mirror_env_state(Environment, EnvStateVar='EnvState', SysStateVar='SysState'):

    r = {SysStateVar: -1}
    env_state = Environment.get_inputs().get(EnvStateVar)
    if env_state in STATE_VAR_STATES:
        env_state_idx = STATE_VAR_STATES.index(env_state)
        new_sys_state = STATE_VAR_STATES[-1-env_state_idx]
        r[SysStateVar] = new_sys_state

    return r

def archive_attr(Obj, attr, attr_archive):
    inputs = Obj.get_inputs(attr, attr_archive)
    if attr not in inputs:
        return {}
    history = inputs.get(attr_archive, [])
    if not isinstance(history, list):
        raise TypeError(f"{attr_archive} must be a list.")
    entry = {attr: copy.deepcopy(inputs[attr]), "timestamp": time.time()}
    return {attr_archive: [*history, entry]}


def sampling_offsets(duration, interval):
    """Return sampling times including both zero and the duration endpoint."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be a positive finite number.")
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Sampling interval must be a positive finite number.")
    return [i * interval for i in range(math.ceil(duration / interval))
            if i * interval < duration] + [duration]


def plot_state_history(ts, series):
    """Plot named numeric series against a shared sequence of timestamps."""
    ts = list(ts)
    if not ts:
        raise ValueError("No state history is available to plot.")
    if not series:
        raise ValueError("At least one state series is required.")
    if any(not isinstance(t, Real) or not math.isfinite(t) for t in ts):
        raise ValueError("Timestamps must be finite numbers.")
    if any(a > b for a, b in zip(ts, ts[1:])):
        raise ValueError("Timestamps must be in chronological order.")
    data = []
    for name, history in series.items():
        history = list(history)
        if len(history) != len(ts):
            raise ValueError(f"{name} must have one value for each timestamp.")
        points = []
        for t, value in zip(ts, history):
            if not pd.api.types.is_scalar(value):
                raise ValueError(f"{name} must contain numeric values or missing values.")
            if pd.isna(value):
                value = None
            elif not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must contain finite numeric values or missing values.")
            points.append((t, value))
        data.append((name, points))
    return _plot_series(data, "Timestamp (seconds)", "State", "State history",
                        step=True, x_ticks=list(dict.fromkeys(ts)))


def plot_df(df, x_column, series_columns):
    """Plot numeric dataframe series against a numeric or datetime column.

    Missing series values are gaps. Returns the path of the SVG opened in the browser.
    """
    if isinstance(series_columns, str):
        raise ValueError("series_columns must be a non-empty sequence of column names.")
    series_columns = list(series_columns)
    if not series_columns:
        raise ValueError("series_columns must be a non-empty sequence of column names.")
    if not df.columns.is_unique:
        raise ValueError("Dataframe column names must be unique.")
    missing_columns = [name for name in [x_column, *series_columns] if name not in df.columns]
    if missing_columns:
        raise KeyError(f"Dataframe columns not found: {missing_columns}")
    if df.empty:
        raise ValueError("Cannot plot an empty dataframe.")

    x_values = df[x_column].tolist()
    if any(not pd.api.types.is_scalar(value) for value in x_values):
        raise ValueError(f"{x_column} must contain scalar values.")
    if any(pd.isna(value) for value in x_values):
        raise ValueError(f"{x_column} must not contain missing x values.")
    if all(isinstance(value, (dt.datetime, dt.date)) for value in x_values):
        dates = [pd.Timestamp(value) for value in x_values]
        try:
            origin = min(dates)
            x_values = [(value - origin).total_seconds() for value in dates]
        except TypeError as exc:
            raise ValueError("Datetime x values must have compatible timezones.") from exc
        x_label = f"{x_column} (seconds since {origin.isoformat()})"
        def format_x(value):
            return f"{value:.2f}"
    elif all(isinstance(value, Real) and math.isfinite(value) for value in x_values):
        x_label = str(x_column)
        def format_x(value):
            return f"{value:.8g}"
    else:
        raise ValueError(f"{x_column} must contain finite numeric or datetime values.")

    data = []
    for name in series_columns:
        points = []
        for x, value in zip(x_values, df[name].tolist()):
            if not pd.api.types.is_scalar(value):
                raise ValueError(f"{name} must contain scalar values.")
            if pd.isna(value):
                value = None
            elif not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must contain finite numeric values or missing values.")
            points.append((x, value))
        data.append((name, points))
    return _plot_series(data, x_label, "Value", "Dataframe plot", format_x=format_x)


def _plot_series(series, x_label, y_label, title, *, step=False, format_x=None, x_ticks=None):
    x_values = [x for _, points in series for x, _ in points]
    values = [value for _, points in series for _, value in points if value is not None]
    xmin, xmax = min(x_values), max(x_values)
    duration = xmax - xmin or 1
    ymin, ymax = (min(values), max(values)) if values else (0, 1)
    if ymin == ymax:
        ymin, ymax = ymin - 1, ymax + 1
    legend_rows = (len(series) + 1) // 2
    left, top, width, height = 90, 56 + 24 * legend_rows, 650, 360
    svg_height = top + height + 90
    colors = ("#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#ef6c00", "#00695c")
    format_x = format_x or (lambda value: f"{value:.2f}")
    right_margin = 60
    if x_ticks is not None:
        tick_labels = [str(value) for value in x_ticks]
        width = max(width, len(x_ticks) * (max(map(len, tick_labels)) * 7 + 16))
        right_margin = max(right_margin, max(map(len, tick_labels)) * 4 + 8)

    def x_pos(timestamp):
        return left + (timestamp - xmin) / duration * width

    def y_pos(value):
        return top + (ymax - value) / (ymax - ymin) * height

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{left + width + right_margin}" height="{svg_height}" '
        f'viewBox="0 0 {left + width + right_margin} {svg_height}" role="img" aria-label="{escape(title, quote=True)}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="13" fill="#222">',
        f'<text x="{left + width / 2}" y="30" text-anchor="middle" font-size="20">{escape(title)}</text>',
    ]
    for i in range(6):
        y = top + height * i / 5
        svg.extend([
            f'<path d="M {left} {y:.2f} H {left + width}" '
            'stroke="#ddd" fill="none"/>',
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end">{ymax - (ymax - ymin) * i / 5:.3g}</text>',
        ])
    ticks = ([(value, str(value)) for value in x_ticks] if x_ticks is not None else
             [(xmin + duration * i / 5, format_x(xmin + duration * i / 5)) for i in range(6)])
    for value, label in ticks:
        x = x_pos(value)
        svg.extend([
            f'<path d="M {x:.2f} {top} V {top + height}" stroke="#ddd" fill="none"/>',
            f'<text x="{x:.2f}" y="{top + height + 20}" text-anchor="middle">{escape(label)}</text>',
        ])
    svg.extend([
        f'<rect x="{left}" y="{top}" width="{width}" height="{height}" fill="none" stroke="#333"/>',
        f'<text x="{left + width / 2}" y="{top + height + 60}" text-anchor="middle">{escape(x_label)}</text>',
        f'<text x="22" y="{top + height / 2}" text-anchor="middle" '
        f'transform="rotate(-90 22 {top + height / 2})">{escape(y_label)}</text>',
    ])
    for index, (name, data) in enumerate(series):
        color = colors[index % len(colors)]
        legend_x = 120 + 300 * (index % 2)
        legend_y = 55 + 24 * (index // 2)
        svg.append(f'<path d="M {legend_x} {legend_y} h 24" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{legend_x + 30}" y="{legend_y + 4}">{escape(str(name))}</text>')
        commands = []
        points = []
        previous = False
        for x_value, value in data:
            if value is None:
                previous = False
                continue
            x, y = x_pos(x_value), y_pos(value)
            if previous:
                commands.append(f"H {x:.2f} V {y:.2f}" if step else f"L {x:.2f} {y:.2f}")
            else:
                commands.append(f"M {x:.2f} {y:.2f}")
            points.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"/>')
            previous = True
        svg.append(f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="2"/>')
        svg.extend(points)
    if not values:
        svg.append(f'<text x="{left + width / 2}" y="{top + height / 2}" text-anchor="middle">No recorded numeric values</text>')
    svg.append("</g></svg>")

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="pysys-state-history-",
                                     suffix=".svg", delete=False) as file:
        file.write("\n".join(svg))
        path = Path(file.name)
    print(f"State history plot saved to {path}")
    if not webbrowser.open(path.as_uri()):
        raise RuntimeError(f"Could not open the plot in a browser. Open {path} manually.")
    return path


from pprint import pprint


def demo(auto=False):

    print(f"""
    This is a demo of the PYSYS scenario simulation.
    It demonstrates how the system and environment states evolve through a series of {len(STATE_VAR_STATES)} simulation steps.
    On each step:
        1. The environment state is randomly selected from the available states.
        2. The system state is set to the complement of the environment state.
    Note:
        - The complement of a state is determined by its index in the STATE_VAR_STATES list.
        - The system state is always set to the complement of the environment state.
        - Both the System and the Environment are actively looping themselves on individual concurrent threads.
    """)

    inputs = {"EnvFreq": 1.0, "SysFreq": 0.5, "Duration": 10.0}
    for k,v in inputs.items():
        if auto:
            inputs[k] = v
        else:
            inputs[k] = float(input(f"Enter the {k} frequency, default={v}: ").strip() or v) if k != "Duration" else float(input(f"Enter the {k}, default={v}: ").strip() or v)

    for name in ("EnvFreq", "SysFreq"):
        if not math.isfinite(inputs[name]) or inputs[name] <= 0:
            raise ValueError(f"{name} must be a positive finite cycle interval.")
    sample_interval = min(inputs["EnvFreq"], inputs["SysFreq"])
    sample_times = sampling_offsets(inputs["Duration"], sample_interval)
    
    StateVar1 = OBJECT(name=STATE_VAR, states=[STATE(name=f"St_{s}", id=str(uuid.uuid4())[:6], value=s) for s in STATE_VAR_STATES])
    StateVar2 = OBJECT(name=STATE_VAR, states=[STATE(name=f"St_{s}", id=str(uuid.uuid4())[:6], value=s) for s in STATE_VAR_STATES])
    
    Environment = SYSTEM(name='Environment', id='Env', affiliation=AFFILIATIONS[1], attributes=[StateVar1])
    MySystem = SYSTEM(name='MY System',id='MySys', affiliation=AFFILIATIONS[0], attributes=[StateVar2])

    ModelManager = SYSTEM(name='ModelManager', id='MM', affiliation=AFFILIATIONS[1], attributes=[])

    pprint(Environment.get(), sort_dicts=False)
    pprint(MySystem.get(), sort_dicts=False)

    MySystem.deactivate()
    Environment.deactivate()

    # Activate the environment to randomly update its state and print it
    EnvStateVar = 'EnvState'
    SysStateVar = 'SysState'

    
    Environment.activate(do=[{"func":rand_state, "args":[EnvStateVar], "kwargs":{}}], 
                             cycle=inputs["EnvFreq"], 
                             cycles=math.ceil(inputs["Duration"]/inputs["EnvFreq"]))

    # Activate the system to mirror the environment state and print it
    MySystem.activate(do=[{"func": time.sleep, "args":[min(inputs["EnvFreq"], inputs["SysFreq"])*0.1], "kwargs":{}},
                          {"func":mirror_env_state, "args":[Environment, EnvStateVar, SysStateVar], "kwargs":{}}], 
                          cycle=inputs["SysFreq"], 
                          cycles=math.ceil(inputs["Duration"]/inputs["SysFreq"]))

    sample_offsets = iter(sample_times)
    sample_start = None

    def wait_for_sample():
        nonlocal sample_start
        if sample_start is None:
            sample_start = time.monotonic() + sample_interval * 0.2
        deadline = sample_start + next(sample_offsets)
        time.sleep(max(0, deadline - time.monotonic()))

    # Sample on the manager's schedule without synchronizing the other threads.
    ModelManager.activate(do=[
                              {"func": wait_for_sample, "args": [], "kwargs": {}},
                              {"func": get_states, "args": [Environment, MySystem, EnvStateVar, SysStateVar, True], "kwargs": {}},
                              {"func": archive_attr, "args": [ModelManager, EnvStateVar, f"{EnvStateVar}_history"], "kwargs":{}},
                              {"func": archive_attr, "args": [ModelManager, SysStateVar, f"{SysStateVar}_history"], "kwargs":{}},
                             ], 
                             cycle=0,
                             cycles=len(sample_times))

        
    # SCENARIO(MySystem, Environment, name="Baseline Scenario", 
    #          steps=[complement for i in STATE_VAR_STATES])

    ModelManager.thread.join()
    MySystem.deactivate()
    Environment.deactivate()
    ModelManager.deactivate()

    manager_inputs = ModelManager.get_inputs()
    env_history = manager_inputs.get(f"{EnvStateVar}_history", [])
    sys_history = manager_inputs.get(f"{SysStateVar}_history", [])
    pprint(env_history)
    pprint(sys_history)
    
    history_df = pd.DataFrame(env_history).join(pd.DataFrame(sys_history), lsuffix=f"_{EnvStateVar}", rsuffix=f"_{SysStateVar}")
    history_df['StateMean'] = history_df[[EnvStateVar, SysStateVar]].mean(axis=1)
    history_df['ts'] = history_df[[f"timestamp_{EnvStateVar}", f"timestamp_{SysStateVar}"]].mean(axis=1)
    history_df['ts'] = history_df['ts']-history_df['ts'].min()
    resolution = len(str(inputs["SysFreq"]).split(".")[-1].lstrip("0"))
    resolution = max(resolution, len(str(inputs["EnvFreq"]).split(".")[-1].lstrip("0")))
    history_df['ts'] = history_df['ts'].apply(lambda x: round(x, resolution))
    pprint(history_df)
    history_df.to_csv("history.csv", index=False)
    
    plot_state_history(history_df["ts"].tolist(), {
        EnvStateVar: history_df[EnvStateVar].tolist(),
        SysStateVar: history_df[SysStateVar].tolist(),
        'StateMean': history_df['StateMean'].tolist(),
    })
    

if __name__ == "__main__":
    
    demo(auto=True)
