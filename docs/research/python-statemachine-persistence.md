# python-statemachine (fgmacedo) — Persistence and State Resumption

**Research date:** 2026-03-13
**Researcher:** Teaparty Research Agent
**Purpose:** Deep-dive into how python-statemachine v3.0.0 handles state persistence,
serialization, and resumption from an arbitrary state — specifically to evaluate whether
the orchestrator's crash-recovery pattern (save CfA state as JSON to disk, reconstruct
machine at exact prior state on resume) is supportable with this library.

---

## Source Material

- Docs (v3.0.0): https://python-statemachine.readthedocs.io/en/latest/
- Persistent domain model example: https://python-statemachine.readthedocs.io/en/latest/auto_examples/persistent_model_machine.html
- API reference: https://python-statemachine.readthedocs.io/en/latest/api.html
- Domain models docs: https://python-statemachine.readthedocs.io/en/latest/models.html
- Integrations docs: https://python-statemachine.readthedocs.io/en/latest/integrations.html
- GitHub issue #358 ("how to save state to disk"): https://github.com/fgmacedo/python-statemachine/issues/358
- GitHub source (develop branch): https://github.com/fgmacedo/python-statemachine/blob/develop/statemachine/statemachine.py

---

## 1. Built-in Serialization/Deserialization

**There is no built-in serialization or deserialization API.** The library does not provide
`to_json()`, `from_json()`, `pickle`, or any similar method. State persistence is entirely
the application's responsibility.

This was explicitly confirmed by the maintainer (Fernando Macedo) in GitHub issue #358,
where he wrote that while there is no built-in serialization function, the `current_state_value`
property and the domain model pattern make it straightforward to implement.

The library's philosophy is that the *machine definition* is code (declarative class),
and only the *current state value* (a small string or integer) needs to be persisted.

---

## 2. Saving State to Disk — The Official Pattern

The library's official answer is the **persistent domain model pattern**, documented
in the examples gallery and in the response to issue #358.

### The Core Mechanism

Every `StateChart` / `StateMachine` instance owns a **model** object. The model has a
`state` attribute that holds the current state's value (or ID string). When the machine
transitions, it writes the new state value to `model.state`. When the machine initializes,
it reads `model.state` to determine where to start.

This means: **whatever object you use as the model, if its `state` attribute is persistent,
the machine is persistent.**

### Official AbstractPersistentModel Pattern

The docs provide an abstract base class as a recipe:

```python
from abc import ABC, abstractmethod
from statemachine import State, StateChart

class AbstractPersistentModel(ABC):
    """Abstract Base Class for persistent models.

    Subclasses implement concrete strategies for:
    - _read_state: Read the state from the concrete persistent layer.
    - _write_state: Write the state from the concrete persistent layer.
    """

    def __init__(self):
        self._state = None

    @property
    def state(self):
        if self._state is None:
            self._state = self._read_state()
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        self._write_state(value)

    @abstractmethod
    def _read_state(self): ...

    @abstractmethod
    def _write_state(self, value): ...
```

### Official FilePersistentModel (Concrete Implementation)

```python
class FilePersistentModel(AbstractPersistentModel):
    def __init__(self, file):
        super().__init__()
        self.file = file

    def _read_state(self):
        self.file.seek(0)
        state = self.file.read().strip()
        return state if state != "" else None

    def _write_state(self, value):
        self.file.seek(0)
        self.file.truncate(0)
        self.file.write(value or "")
```

### Usage — Save and Restore Lifecycle

```python
class ResourceManagement(StateChart):
    power_off = State(initial=True)
    power_on = State()
    turn_on = power_off.to(power_on)
    shutdown = power_on.to(power_off)

# First run — create model backed by a file
state_file = open("/tmp/machine_state.txt", "r+")
model = FilePersistentModel(file=state_file)
sm = ResourceManagement(model=model)

sm.send("turn_on")  # transitions to power_on; file is written automatically

del sm     # instance is gone
del model  # model is gone; state is safe on disk

# Later — reconstruct at the saved state
model = FilePersistentModel(file=state_file)
sm = ResourceManagement(model=model)
# sm is now at power_on, not power_off (the initial state)
```

The key point: **reconstruction automatically reads the persisted state**. The machine
does not restart from `initial=True` if the model already has a non-None `state` value.

### JSON / Database Variants

Any storage backend works by implementing `_read_state` and `_write_state`. For the
TeaParty orchestrator's JSON-to-disk pattern:

```python
import json

class JsonFilePersistentModel(AbstractPersistentModel):
    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def _read_state(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
                return data.get("state")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_state(self, value):
        # Load existing JSON blob, update state key, write back
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["state"] = value
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)
```

This lets the model's state key coexist with other orchestrator fields (session_id,
timestamps, etc.) in the same JSON file the orchestrator already writes.

---

## 3. The current_state_value Property

`current_state_value` is a **low-level read/write property** that bypasses all hooks,
guards, validations, and transition callbacks. It directly reads or sets the active
state value on the model.

From the source:

```python
# Getter: returns the value or ID of the currently active state
sm.current_state_value  # e.g., "power_on" or 2

# Setter: directly assigns the state, bypassing all hooks
sm.current_state_value = "power_on"
```

**Important caveat from the docs:** "bypasses all the hooks and validations." This means:
- `on_enter_*` callbacks are NOT called
- `on_exit_*` callbacks are NOT called
- Guards are NOT evaluated
- Transition callbacks are NOT called

The setter is appropriate for **restoring saved state** (where you want the machine at
a specific state without re-running entry actions), but should not be used to drive
normal transitions.

The `current_state` property is documented as **deprecated** in v3.0.0. The modern
replacement is the `configuration` property (an `OrderedSet` of currently active states).

---

## 4. Initializing at an Arbitrary State (Not the Initial State)

Yes — there are two supported mechanisms.

### Method A: Via the model's state attribute (recommended for persistence)

If the model object already has a non-None `state` value when the machine is constructed,
the machine starts at that state rather than at `initial=True`.

```python
class MyModel:
    state = "power_on"   # pre-set to a specific state value

sm = ResourceManagement(model=MyModel())
# sm starts at power_on, not power_off
```

This is the mechanism the `FilePersistentModel` / `JsonFilePersistentModel` patterns
above use. The state is read lazily from disk on first access.

### Method B: Via the start_value constructor parameter

The `StateChart.__init__` accepts a `start_value` parameter:

```python
sm = ResourceManagement(start_value="power_on")
```

From the constructor source:

```python
def __init__(
    self,
    model: "TModel | None" = None,
    state_field: str = "state",
    start_value: Any = None,
    listeners: "List[object] | None" = None,
    **kwargs: Any,
):
    self.start_configuration_values = (
        [start_value] if start_value is not None else list(self.start_configuration_values)
    )
```

The docs describe `start_value` as: "An optional start state value if there's no current
state assigned on the Domain models."

Note the precedence: if the model already has a state assigned, `start_value` is ignored.
`start_value` is the fallback when there is no model state to read.

### Method C: Via start_configuration_values class attribute

For complex (hierarchical) machines, you can override `start_configuration_values` at
the class level to specify multiple active states (parent + child in a compound hierarchy):

```python
class MyMachine(StateChart):
    start_configuration_values = ["editing", "draft"]  # parent + child
    ...
```

This is used when restoring hierarchical state (see section 6 below).

---

## 5. Transition History Tracking

**There is no built-in transition history log that persists to disk.** The library does
not accumulate a journal of past transitions.

The `history_values` instance dict (set in `__init__` as `self.history_values: Dict[str,
List[State]] = {}`) is **in-memory only**. It records which child states were most recently
active inside each compound state, used by `HistoryState()` pseudo-states to restore
sub-state on re-entry. It is reset to an empty dict on every `__init__` call — it does
not survive process death.

If the orchestrator needs a transition audit log (for debugging or compliance), it must
be implemented explicitly, for example via an `on_enter_state` listener that appends to
an external log:

```python
class AuditingListener:
    def after_transition(self, event, source, target):
        log_transition(event=event, source=source.id, target=target.id)

sm = MyMachine(listeners=[AuditingListener()])
```

---

## 6. Hierarchical / Compound States — Serialization and Restoration

This is the most nuanced area, and has an important gap.

### What configuration_values captures

For a flat machine, `current_state_value` (a single string) fully describes the active
configuration. For a hierarchical machine with compound or parallel states, the full
configuration is a *set* of active states — the parent and all active children.

The `configuration_values` property returns an `OrderedSet` of all currently active
state values. For example, in a machine where `editing` is a compound state with child
`draft`:

```python
sm.configuration_values  # OrderedSet(["editing", "draft"])
```

### The Persistence Gap for Compound States

The **domain model pattern persists only a single `state` field**. For a flat machine
this is sufficient. For a compound machine, a single field does not capture the full
active configuration.

There are two sub-problems:

1. **Active leaf state in a compound hierarchy.** The single `state` field on the model
   stores one value. For compound states, you would need to store all values in
   `configuration_values` and use `start_configuration_values` to restore them.

2. **HistoryState memory.** The `history_values` dict is in-memory only. If you exit a
   compound state and the process crashes, on restart the history pseudo-state will not
   know which child was previously active. The machine will fall back to the compound
   state's declared `initial` child.

### Approach for Hierarchical Persistence

To handle compound states properly, serialize and restore `configuration_values`:

```python
# Save
state_snapshot = list(sm.configuration_values)  # e.g., ["editing", "draft"]
json.dump({"configuration": state_snapshot, ...}, f)

# Restore: use start_configuration_values
class MyMachine(StateChart):
    ...

saved = json.load(f)
sm = MyMachine()
sm.start_configuration_values = saved["configuration"]  # set before engine.start()
```

However, `start_configuration_values` is a class attribute that gets resolved during
`__init__`. Setting it after `__init__` is fragile. The safer approach is to subclass
or use `start_value` with a single terminal state value if your hierarchy is shallow
enough that the leaf state fully determines the configuration:

```python
# If "draft" can only appear inside "editing", just restore the leaf:
sm = MyMachine(start_value="draft")
# The engine will enter "editing" and then "draft" per the hierarchy definition
```

Whether this works correctly depends on whether the compound state's entry logic is
idempotent (i.e., safe to re-execute on restore). Test this explicitly.

**Bottom line for the orchestrator:** if the CfA state machine only uses flat states
or shallow compound states where the leaf uniquely identifies the configuration, the
standard `start_value` / model `state` attribute approach is sufficient. For deep
hierarchies with history pseudo-states, `history_values` is not persistable without
custom serialization of that dict.

---

## 7. Django and Database Integrations

### MachineMixin (official)

The library ships `MachineMixin`, documented at https://python-statemachine.readthedocs.io/en/latest/integrations.html

`MachineMixin` lets any Python class (including Django ORM models) attach a state machine
automatically. The machine reads/writes its state to a named field on the host object.

```python
from statemachine.mixins import MachineMixin

class Campaign(models.Model, MachineMixin):
    state_machine_name = 'campaign.statemachines.CampaignMachine'
    state_machine_attr = 'sm'    # self.sm is the StateChart instance
    state_field_name = 'step'    # Django IntegerField or CharField holding state value
    bind_events_as_methods = True  # campaign.produce() delegates to sm.produce()

    name = models.CharField(max_length=30)
    step = models.IntegerField()
```

Django handles persistence: when you call `campaign.save()`, the `step` field (which
`MachineMixin` keeps in sync with `sm.current_state_value`) is written to the database.
On reload from DB, the machine reconstructs at the saved state value because the Django
field already has the value.

This is the **recommended pattern for Django projects**. The mixin also includes a fix
for Django data migrations (issue #551 in v2.6.0): it skips state machine initialization
for Django historical models, preventing `ValueError` during `makemigrations`.

**Note:** There is no `SQLAlchemy`-specific mixin in the library. For SQLAlchemy, apply
the same pattern manually: a model attribute stores the state string, and you pass a
model instance (or a custom persistent model) to the StateChart constructor.

### No ORM Abstraction Beyond Django

No SQLAlchemy, Peewee, Tortoise ORM, or other integrations exist in the official library.
These require the manual `AbstractPersistentModel` approach described in section 2.

---

## Summary: What Works for the TeaParty Orchestrator

The orchestrator saves a JSON blob per CfA run. Here is how each requirement maps to
the library's capabilities:

| Requirement | Supported? | Mechanism |
|-------------|-----------|-----------|
| Save current state to JSON | Yes | `model.state` or `sm.current_state_value`; write to existing JSON blob |
| Restore machine at saved state (flat FSM) | Yes | Model's `state` attribute pre-set, or `start_value=` constructor param |
| Restore machine mid-hierarchy (compound) | Partial | `start_value` works if leaf state uniquely identifies config; deep history is NOT persisted |
| Bypass entry/exit hooks on restore | Yes | `current_state_value` setter bypasses all hooks |
| Transition history / audit log | No (built-in) | Must implement manually via listener |
| Django integration | Yes | `MachineMixin` + Django field |
| SQLAlchemy integration | Manual only | Implement `AbstractPersistentModel` |
| Persist HistoryState memory | No | `history_values` is in-memory only; no serialization support |

### Recommended Implementation Sketch for the Orchestrator

```python
import json
from abc import ABC, abstractmethod
from statemachine import State, StateChart


class OrchestratorStatePersistentModel(ABC):
    """Bridges python-statemachine's model protocol to the orchestrator's JSON state file."""

    def __init__(self, state_path: str):
        self._state_path = state_path
        self._state = None  # lazy-loaded

    @property
    def state(self):
        if self._state is None:
            self._state = self._read_state()
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        self._write_state(value)

    def _read_state(self):
        try:
            with open(self._state_path) as f:
                data = json.load(f)
            return data.get("sm_state")  # coexists with other orchestrator fields
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_state(self, value):
        try:
            with open(self._state_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["sm_state"] = value
        with open(self._state_path, "w") as f:
            json.dump(data, f, indent=2)


class CfARunnerSM(StateChart):
    idle      = State(initial=True)
    launching = State()
    streaming = State()
    stalled   = State()
    done      = State(final=True)
    failed    = State(final=True)
    killed    = State(final=True)

    launch  = idle.to(launching)
    stream  = launching.to(streaming)
    stall   = streaming.to(stalled)
    kill    = stalled.to(killed)
    finish  = streaming.to(done) | stalled.to(done)
    error   = launching.to(failed) | streaming.to(failed) | stalled.to(failed)


# Create or resume:
model = OrchestratorStatePersistentModel(state_path="/path/to/run_state.json")
sm = CfARunnerSM(model=model)
# If run_state.json had sm_state="streaming", sm starts at streaming.
# If no file or sm_state is null, sm starts at idle (initial=True).
```

---

## Key Caveats to Know Before Implementing

1. **`current_state` is deprecated in v3.0.0.** Use `configuration` (returns `OrderedSet`)
   or `current_state_value` (returns the string/int value) instead.

2. **`current_state_value` setter bypasses ALL hooks.** Only use it for state restoration,
   never for driving normal machine logic (use `sm.send("event_name")` for that).

3. **Async machines require `await sm.activate_initial_state()` before first use** if no
   event has been sent yet. This is easy to forget and will cause state inspection to return
   None before the first event.

4. **`history_values` is not serializable without custom code.** If a `HistoryState()`
   pseudo-state is part of the machine, crashing and restarting will lose history memory.
   The machine will fall back to the compound state's declared `initial` child on re-entry
   via history.

5. **The model pattern is the recommended, officially documented persistence approach.**
   Maintainer Fernando Macedo closed issue #358 with this exact pattern and called it the
   canonical solution. It is not a hack — it is the intended design.

Sources:
- [Persistent domain model example](https://python-statemachine.readthedocs.io/en/latest/auto_examples/persistent_model_machine.html)
- [API reference](https://python-statemachine.readthedocs.io/en/latest/api.html)
- [Domain models docs](https://python-statemachine.readthedocs.io/en/latest/models.html)
- [Integrations (MachineMixin / Django)](https://python-statemachine.readthedocs.io/en/latest/integrations.html)
- [GitHub issue #358 — "how to save state to disk"](https://github.com/fgmacedo/python-statemachine/issues/358)
- [States docs (compound, history)](https://python-statemachine.readthedocs.io/en/latest/states.html)
- [Releases — v3.0.0 changelog](https://github.com/fgmacedo/python-statemachine/releases)
