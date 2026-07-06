# PySYS

PySYS is a small Python modeling framework for representing systems with Object Process Methodology-style building blocks. It provides base classes for objects, processes, states, and executable models, plus a TaxiBot example that compares aircraft taxiing scenarios.

## Repository Layout

- `main/pysys.py` - lightweight core classes: `THING`, `OBJECT`, `PROCESS`, and `System`.
- `pysys.py` - same lightweight core module at the project root.
- `sysmodel.py` - fuller modeling toolkit with `STATE`, `MODEL`, threaded `PROCESS` execution, snapshots, and the `@BEHAVIOR` decorator.
- `taxiing.py` - TaxiBot domain model, scenario summaries, and a synchronous scenario runner.
- `taxiing_opm.txt` - source OPM/OPL-style model text for the TaxiBot example.
- `generic_instructions.txt` and `specific_instructions.txt` - modeling/code-generation guidance.
- `Scenarios/` - generated scenario output files.

## Requirements

The examples use Python 3 and these packages:

```bash
pip install pandas numpy
```

## Core Concepts

`THING` is the shared base entity. It stores a name, ID, sub-objects, and sub-processes.

`OBJECT` represents a model object and stores its states.

`PROCESS` represents behavior. A process can wrap a callable and execute it with `RUN(...)`.

`MODEL` groups free objects and processes and can execute or snapshot a model.

`@BEHAVIOR` decorates model behavior functions so they can be attached to a `PROCESS`.

## Quick Start

From the `PYSYS` directory:

```python
from sysmodel import OBJECT, PROCESS, MODEL, BEHAVIOR

class Battery(OBJECT):
    def __init__(self):
        super().__init__(name="Battery", states={"charge": 100})

@BEHAVIOR
def drain(model, context, amount=10):
    battery = next(obj for obj in model.OBJECTS if obj.NAME == "Battery")
    battery.STATES["charge"] -= amount
    context["self"]._running = False
    return {"charge": battery.STATES["charge"]}

battery = Battery()
drain_process = PROCESS(name="Drain", behavior=drain, verbose=False)
battery.PROCESSES.append(drain_process)

model = MODEL(objects=[battery], processes=[drain_process])
result = drain_process.RUN(model, amount=15)

print(result)
print(battery.STATES)
```

## TaxiBot Example

The TaxiBot model defines three scenario summaries:

- `baseline` - aircraft taxis without TaxiBot.
- `taxibot` - TaxiBot moves the aircraft for the full taxi distance.
- `hybrid` - TaxiBot handles part of the taxi distance, then aircraft engines complete the trip.

Example:

```python
from taxiing import (
    scenario_summary_baseline,
    scenario_summary_taxibot,
    scenario_summary_hybrid,
    run_scenario_simulation,
)

print(scenario_summary_baseline())
print(scenario_summary_taxibot())
print(scenario_summary_hybrid())

df, summary = run_scenario_simulation(mode="hybrid", switch_distance_m=750)
print(summary)
print(df)
```

To save a simulation result:

```python
df, summary = run_scenario_simulation(
    mode="taxibot",
    store=True,
    store_path="Scenarios/Taxiing/taxibot.csv",
)
```

## Notes

- The TaxiBot model currently assumes a 1,500 m taxi distance and 10 m/s taxi speed.
- The hybrid scenario defaults to switching at 50% of the taxi distance because the OPL model does not specify a switch point.
- Some framework pieces are still experimental. For example, `main/pysys.py` contains a minimal `SCENARIO` helper, while the fuller execution path lives in `sysmodel.py` and `taxiing.py`.
