# PySYS

PySYS is a lightweight, OPM-inspired Python framework for representing model
elements and experimenting with system and environment behavior over time.
`pysys.py` contains the model classes, a synchronous scenario helper, and a
separate threaded simulation demo.

## What It Provides

- `THING` - the common base class, with metadata-driven attributes and helpers
  for setting, retrieving, and finding items.
- `MODEL` - a container for `THINGS` with an OpCloud export URL and a method
  for loading an HTML specification.
- `STATE` and `OBJECT` - state values and objects that can reference possible
  `STATES` and a current `STATE`.
- `PROCESS` - a thing with a `BEHAVIOR` callable and a `run(...)` method.
- `SYSTEM` - a container with input and output mappings that can execute
  functions on a background cycle.
- `SCENARIO(...)` - a synchronous helper that applies step functions to a
  system and environment and collects their `Number` object states.

The mechanism is useful when you want to describe how a system and its environment influence each other without committing to a heavy simulation framework.

## Building a project

Run the project-local build script:

```powershell
.\.venv\Scripts\python.exe --version
.\build.ps1
```

`build.ps1` creates `.venv`, installs `requirements.txt`, activates the environment
for the current PowerShell session, and sets these defaults from `Params/params.json`
unless they are already set:

- `PYSYS_TIMEOUT`
- `PYSYS_OUTPUT_FILE`
- `PYSYS_RUN_CODE`
- `PYSYS_MODEL`
- `PYSYS_ENDPOINT`
- `PYSYS_REASONING_EFFORT`

Use `.\build.ps1 -NoActivate` to create/install without activation, or
`.\build.ps1 -Upgrade` to upgrade all requirements.

## Requirements

Python 3.10 or later is required. On Windows, run the build script from the
project directory to create or reuse `.venv` and install the dependencies in
`requirements.txt`:

```powershell
.\build.ps1
```

The script uses `python` from your PATH to create the environment, installs the
requirements, and activates the environment in the current PowerShell session.
Run it directly in that session, not via `powershell -File`, which starts a
separate process and cannot activate its parent. Afterward, `python pysys.py`
uses the project environment; run `deactivate` to leave it. Rerun the script
after changing dependencies. If execution policy blocks local scripts, consult
your administrator or PowerShell's execution-policy documentation.

SVG rendering uses only the Python standard library. The demo also uses pandas;
the OpCloud Save As automation uses `pywinauto` on Windows.

### Exporting an OpCloud model

Run the export utility with a model URL:

```powershell
.\.venv\Scripts\python.exe opcloud.py source=https://opcloud.systems/load/MODEL_ID
```

The command opens the export in your browser, waits for an HTML file in Downloads,
and then copies it to `target`, leaving the original download in place. `target`
may be an existing directory, a full HTML file path, or a filename in Downloads.
If omitted, the file remains in Downloads. A directory target gets a numbered
filename if needed; an explicit filename replaces an existing file.

On Windows, the build script installs `pywinauto` to handle the Save As dialog
automatically. If automation is unavailable, the command asks you to save in
Downloads manually. The browser's automatic download location must also be
Downloads. If your browser uses another directory, provide it as
`downloads_dir=PATH`. Set `timeout=SECONDS` to change the 300-second timeout.

Avoid downloading unrelated HTML files at the same time: the script selects the
newest HTML file modified after the export started and cannot verify its origin.

### Creating projects and converting OPM models

Create a project from the template and activate the OPM-to-PySYS agent with:

```powershell
.\.venv\Scripts\python.exe opcloud.py `
  source=https://opcloud.systems/load/MODEL_ID `
  project=MyProject `
  agent=OPM2PySYS
```

`target=PROJECT_ROOT` is the project root. The downloaded OPM HTML is stored under
`PROJECT_ROOT/Artifacts/Models`, and project params are stored under
`PROJECT_ROOT/Params`. If `target` is omitted, the default project root
`~/Code/PySYS-Projects/NAME` is read from `Params/params.json` in the template.
Existing files are preserved; only missing template files and directories are copied.

The generated software is written according to `Artifacts.Code`. An absolute
code location is used as-is; a relative code location is resolved from the
project root. `CodeResources` lists the framework resources copied into the code
location, including `pysys.py` by default.

The agent resolves `Projects/__Template__/Agents/OPM2PySYS/Instructions/base.json`
and referenced files into a plain prompt. Each request and raw response is stored
under the project's `Requests` directory in timestamped folders. The generated
Python is syntax-checked and executed in a temporary sandbox before it is written
to `pysys_model.py` in the project folder.

LLM settings can be overridden for a run:

```powershell
api_key=... model=MODEL_NAME endpoint=https://HOST/v1/chat/completions
```

Prefer setting `OPENAI_API_KEY` instead of placing an API key on the command line.

Reasoning effort can be set to `low`, `medium`, `high`, `xhigh`, or `max`:

```powershell
reasoning_effort=high
```

Explicit workflow flags default to values in `Params/params.json`:

```powershell
reload_model=true
refine_code=true
regenerate_code=false
run_code=false
```

With `reload_model=false`, the latest HTML model under `Artifacts.Models` is used
instead of contacting OpCloud. `refine_code=true` uses the existing module under
`Artifacts.Code` as a base and asks the agent to refine it. `regenerate_code=true`
ignores existing code and creates it from scratch. The two generation flags are
mutually exclusive. With both false, the existing output file is reused without
an LLM call. With `run_code=true`, the selected code is executed after generation
or reuse.

Git repositories can be initialized or cloned in `Artifacts.Code`:

```powershell
git=create
git=clone git_source="C:\Repos\FlightReservation"
git=clone git_source="https://github.com/ORG/REPOSITORY.git" git_branch=main
```

If `git=create`, the code directory is initialized with `git init`. If
`git=clone`, the source may be a local path or remote URL. An existing Git
repository in `Artifacts.Code` is detected and left unchanged.

If a target code folder contains files but is not a Git repository, it is
renamed to a sibling `<Folder>_pre_git_<timestamp>` folder. A fresh code folder
is created, initialized or cloned, and the preserved contents are copied back.
All preserved contents are committed as a local baseline so subsequent refinements
and regeneration are visible as Git changes.

Git repositories are created under the project-specific code folder:
`<Artifacts.Code>/<ProjectName>`. For example, a FlightReservation project uses
`C:\Users\ymord\Code\PySYS-Projects\FlightReservation`. Framework resources listed
by `CodeResources` are first stored in the project's `Resources` directory, so
each project retains an independent resource version.

## Framework concepts

### Things, objects, and states

Constructors accept keyword arguments such as `name`, `id`, `states`, and
`attributes`. Recognized attributes are stored using uppercase names, for
example `NAME`, `STATES`, and `ATTRIBUTES`. An `ID` is generated when none is
provided. The `*_ATTRS` dictionaries describe accepted fields, defaults,
cardinality, and intended types; they are defined after the classes so that
references such as `OBJECT_ATTRS["STATES"]["type"]` point to actual classes.
They are not a complete runtime type-validation system.

`THING.get()` returns a dictionary of the recognized attributes that exist,
converting nested things to dictionaries. `get_item(group, name=...)` searches a
group and returns one matching object, a list of multiple matches, or `None`.
Use `append(...)` for list-valued metadata fields.

```python
from pysys import OBJECT, STATE, SYSTEM

off = STATE(name="off", value=0)
on = STATE(name="on", value=1)
number = OBJECT(name="Number", states=[off, on], state=off)
system = SYSTEM(name="System", attributes=[number])

print(system.get_item("ATTRIBUTES", name="Number").STATE.VALUE)  # 0
number.STATE = on
```

`STATE` and `STATES` are object metadata; the threaded demo instead stores its
sampled numeric states in `SYSTEM.INPUTS`. Updating an input does not
automatically update an object's `STATE`.

### Running system actions

`SYSTEM.activate(do=..., cycle=..., cycles=...)` starts a daemon thread.
Each action in `do` is a dictionary with a `func` and optional `args` and
`kwargs`; actions run in order on every cycle. A plain `dict` returned by an
action is merged into the system's inputs. `cycle` is the minimum target
period in seconds, and `cycles` limits iterations (default 10). Actions that
take longer than the period can make a cycle late.

```python
from pysys import SYSTEM

counter = SYSTEM(name="Counter")

def increment(counter):
    return {"count": counter.get_inputs().get("count", 0) + 1}

counter.activate(do=[{"func": increment, "args": [counter]}], cycle=0, cycles=3)
counter.thread.join()
print(counter.get_inputs("count"))  # {'count': 3}
counter.deactivate()
```

Arguments in `args` are evaluated when the action is constructed. Pass an
object or a callable that reads current state inside the action when a fresh
value is needed each cycle. `deactivate()` requests a stop; it does not join
the thread or interrupt an action or sleep already in progress. A loop reaching
its cycle limit does not itself call `deactivate()`. The mappings are not
protected as atomic snapshots across threads.

`SYSTEM.set_inputs(...)` updates inputs, `get_inputs(...)` returns a new
dictionary of requested existing keys (or all inputs), and `provide_output`
filters instance attributes rather than solely the `OUTPUTS` mapping.

### Synchronous scenarios

`SCENARIO(system, environment, steps=[...], freq=...)` runs each step
synchronously. Each step receives the current system and environment and returns
the pair for the next step. The runner sleeps `freq` seconds after each step and
returns a list containing `Step`, `SystemState`, and `EnvironmentState`.

Currently the runner specifically looks for an object named `Number` in each
system's `ATTRIBUTES` and reads its `STATE`. Both objects and their `STATE`
attributes must be present. The returned state entries are references to
`STATE` objects, not copied snapshots.

```python
from pysys import OBJECT, SCENARIO, STATE, SYSTEM

def make_number():
    states = [STATE(name="zero", value=0), STATE(name="one", value=1)]
    return OBJECT(name="Number", states=states, state=states[0])

system = SYSTEM(name="System", attributes=[make_number()])
environment = SYSTEM(name="Environment", attributes=[make_number()])

def set_environment_to_one(system, environment):
    number = environment.get_item("ATTRIBUTES", name="Number")
    number.STATE = number.STATES[1]
    return system, environment

results = SCENARIO(system, environment, steps=[set_environment_to_one], freq=0)
print(results[0]["EnvironmentState"].VALUE)  # 1
```

The demo below uses threaded `SYSTEM` actions and is not run through
`SCENARIO`.

### Models and processes

`MODEL(name=..., id=..., things=[...])` groups model elements. Its `URL` is
constructed from the ID as an OpCloud export URL. `load()` requests the
OpCloud HTML export and reads the resulting file into `spec`;
`generate_pysys_code()` currently returns only a placeholder string.

`PROCESS(behavior=...)` stores a callable, and `run(*args, **kwargs)` forwards
its arguments to that callable. The optional `BEHAVIOR` decorator injects
caller context and emits timing logs; it expects a model mapping and a calling
process context. The process's cyclic `activate()` currently expects a
`thread` attribute to have been initialized by the caller.

## Running the demo

After activating the project environment, run:

```powershell
python pysys.py
```

The demo starts separate environment, system, and manager threads. The
environment selects a random state from `0` through `10`. The system reads the
environment and responds with the state at the opposite index in that list
(`10 - EnvState`). The manager samples both values independently of their
updates, so a recorded system state can reflect an earlier environment state.
The offset between updates and sampling reduces, but does not eliminate, this
possibility.

By default the demo runs automatically with:

| Setting | Default | Meaning |
| --- | --- | --- |
| `EnvFreq` | `1.0` | Environment cycle interval in seconds |
| `SysFreq` | `0.5` | System cycle interval in seconds |
| `Duration` | `10.0` | Sampling duration in seconds |
| `output_dir` | `Results` | Directory for demo output |
| `plot_name` | `plot` | Plot subdirectory and filename prefix |

Despite their names, `EnvFreq` and `SysFreq` are **intervals**, not rates in
Hz. The manager samples at the shorter interval, including the first reading
and the duration endpoint. With the defaults, the demo schedules 21 readings
from zero through 10 seconds. The first reading is delayed by 20% of the
sampling interval; the system's intended response delay is 10%. These delays
do not synchronize the threads, and actual sampling times can vary.

To enter different settings interactively, run:

```powershell
python pysys.py auto=False
```

Enter a value for each prompt or press Enter to use its default. This includes
prompts for `auto`, `output_dir`, and `plot_name`. In the current implementation,
other `key=value` command-line arguments and keyword arguments to `demo()` do
not override those settings: automatic mode uses the defaults, while
interactive mode takes values from the prompts.

The demo prints its samples and histories, then writes `history.csv` to the
output directory. The CSV contains `EnvState`, `SysState`, their archive
timestamps, `StateMean`, and a rounded elapsed-time `ts` column. It overwrites
the previous `history.csv` in that directory. The SVG plot is saved under a
subdirectory named by `plot_name`, with a unique filename beginning with that
name; with the defaults this is `Results\plot`. The plot opens in the default
browser, and its path is printed. The output directory is relative to the
current working directory unless an absolute path is entered.

## What This Can Be Used For

This pattern can be used for small, inspectable simulations where the important part is how state changes over a sequence of steps.

Good fits include:

- System-environment interaction models.
- Early architecture or concept-of-operations experiments.
- State-machine-like behavior prototypes.
- Scenario playback for requirements or OPM-inspired models.
- Monte Carlo-style experiments where environment inputs vary randomly.
- Teaching examples for objects, processes, state transitions, and threaded execution.
- Lightweight digital twin sketches before introducing a larger simulation stack.

## Notes

- The current scenario runner is deliberately simple and prints directly to the console.
- `SYSTEM.activate()` starts a background thread that repeatedly calls `run(...)`.
- Scenario steps are synchronous; they update and return the current system/environment pair.
- `OBJECT.STATES` stores allowed or known states, while `OBJECT.STATE` refers to
  the current state when set.
- `SYSTEM.INPUTS` and `SYSTEM.OUTPUTS` are per-instance dictionaries. Activation
  and deactivation update `INPUTS["state"]` and `INPUTS["is_running"]`; actions
  returning a dictionary add their values to `INPUTS`.
- In the demo, when the duration is not a multiple of the sampling interval,
  the last interval is shorter. The duration is measured from the first
  scheduled reading.
- The plot shows archived states and their mean against `ts`, calculated from
  the mean archive timestamp of each row relative to the first row. Tick labels
  correspond to the supplied timestamps; missing values appear as gaps.

The plotting functions are in `plotting.py`. To plot dataframe columns:

```python
from pathlib import Path
from plotting import plot_df, plot_state_history

plot_df(history_df, "timestamp_EnvState", ["EnvState", "SysState"],
        output_dir=Path("results"))
plot_state_history([0, 1], {"State": [2, 3]}, output_dir=Path("results"))
```

Both functions open the SVG in the default browser and return its path. In the
current implementation, pass `output_dir` as a `Path`, as shown above: the
string default `"results"` cannot currently be combined with the plot
subdirectory. The helper creates the directory if needed. `plot_state_history`
uses the `plot` subdirectory by default; `plot_df` uses `plot.png`.
`plot_state_history` accepts timestamps and equally sized numeric series.
`plot_df` draws straight lines in row order, supports
numeric or datetime x values and numeric series, and shows missing series values
as gaps. Datetime axes are labeled in seconds from the earliest timestamp.
When using one timestamp column for both series, the resulting plot uses that
column's times for both, which may differ from their separate archive times.
