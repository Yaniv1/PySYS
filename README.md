# PySYS

PySYS is a lightweight Python mechanism for modeling a system, its environment, and the processes that change their states over time. PySYS is based on **Object Process Methodology (OPM)**. 
`pysys.py` gives you a few generic building blocks, then demonstrates them with an executable scenario.

## What It Provides

- `THING` - the common base class for named model elements with IDs, owned objects, and owned processes.
- `OBJECT` - a state-bearing thing. It can hold a list of possible `STATES` and a current `state`.
- `PROCESS` - a wrapper around a behavior function that can be run with `RUN(...)`.
- `SYSTEM` - a runnable container that can receive inputs, expose outputs, activate, deactivate, and execute functions on a timed cycle.
- `SCENARIO(...)` - a simple scenario runner that applies step functions to a `System` and an `Environment`.

The mechanism is useful when you want to describe how a system and its environment influence each other without committing to a heavy simulation framework.

## Requirements

The current module uses only the Python standard library.

```bash
python pysys.py
```

## Core Mechanism

A model is built from state-bearing objects attached to a `SYSTEM`. Scenario steps are plain Python functions that accept:

```python
System, Environment
```

Each step updates one or both containers, then returns:

```python
return System, Environment
```

`SCENARIO(...)` executes those steps in order, prints the system and environment after each step, and reports final system state information.

## Example Scenario

The included example creates a simple complement relationship between a system number and an environment number.

```python
STATE_VAR = 'Number'
STATE_VAR_STATES = list(range(10))
```

Both the system and the environment receive a `Number` object whose valid states are `0` through `9`.

```python
MySystem = SYSTEM('MY System', id='MySys')
Environment = SYSTEM('Enviornemnt', id='Env')

setattr(Environment, STATE_VAR, OBJECT(STATE_VAR, states=STATE_VAR_STATES))
setattr(MySystem, STATE_VAR, OBJECT(STATE_VAR, states=STATE_VAR_STATES))
```

The `complement` step randomly chooses an environment state, copies the `Number` object, updates the environment, then sets the system state to the complementary value from the same state list.

```python
def complement(System, Environment):
    new_env_state_idx = random.randint(0, len(STATE_VAR_STATES) - 1)
    new_env_state = STATE_VAR_STATES[new_env_state_idx]

    env_state_var = copy.deepcopy(getattr(Environment, STATE_VAR))
    env_state_var.state = new_env_state
    setattr(Environment, STATE_VAR, env_state_var)

    new_sys_state = STATE_VAR_STATES[-new_env_state_idx]
    sys_state_var = copy.deepcopy(getattr(System, STATE_VAR))
    sys_state_var.state = new_sys_state
    setattr(System, STATE_VAR, sys_state_var)

    return System, Environment
```

The baseline scenario runs that same step ten times:

```python
SCENARIO(
    MySystem,
    Environment,
    name="Baseline Scenario",
    steps=[complement for i in range(10)],
)
```

Running `python pysys.py` activates the system and environment, executes the scenario, prints each step, and deactivates both containers at the end.

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

## Extending A Scenario

To create a new scenario:

1. Define one or more `OBJECT` instances with possible states.
2. Attach those objects to a `SYSTEM` or environment with `setattr(...)`.
3. Write step functions that accept and return `(System, Environment)`.
4. Pass the step functions to `SCENARIO(...)` in the order you want them executed.

Example:

```python
def set_environment_to_zero(System, Environment):
    number = copy.deepcopy(getattr(Environment, "Number"))
    number.state = 0
    setattr(Environment, "Number", number)
    return System, Environment

SCENARIO(MySystem, Environment, steps=[set_environment_to_zero, complement])
```

## Notes

- The current scenario runner is deliberately simple and prints directly to the console.
- `SYSTEM.activate()` starts a background thread that repeatedly calls `run(...)`.
- Scenario steps are synchronous; they update and return the current system/environment pair.
- `OBJECT.STATES` stores allowed or known states, while `OBJECT.state` stores the current state.
