# py-der-61850

Python library for modelling, monitoring and controlling distributed energy resources (DER)
with an information model based on IEC 61850-7-420, extended for the domain of Renewable
Energy Communities (REC/CER).

It provides the domain model shared by a cloud controller and the edge devices close to each
point of delivery (POD): logical nodes, data objects, dynamic reflection, protocol clients,
the runtime image process and the REC/BESS optimization logic.

Developed by [ENYR](https://www.enyr.eu) and used in production on a pilot energy community,
with prosumers and consumers equipped with PV and batteries of different brands.

## Features

- **IEC 61850-like information model**: logical nodes (`DPCC`, `DSTO`, `DGEN`, `DLOD`,
  `MMXN`, `MMTN`, ...), data objects and data attributes with value, quality and timestamp
  (`mxVal`, `q`, `t`).
- **Domain extensions for energy communities** (`enyr_61850_2025a`): community controller
  `DPMC_ERAB`, forecasters `FFRC` for day-ahead prices, load and generation, contract nodes
  `DCSC`/`DPRC`.
- **Reflection**: logical nodes are instantiated dynamically from a user configuration and
  wired to real data through the image process.
- **Protocol clients**: Modbus, MQTT, InfluxDB, FTP and vendor cloud APIs, behind a common
  device client interface.
- **Optimization**: Pyomo models solved with CBC for self-consumption (SC), energy arbitrage
  (EA) and collective self-consumption across multiple batteries (CSC).

## Requirements

- Python >= 3.11
- [CBC](https://github.com/coin-or/Cbc) solver, only for the optimization logical nodes
  (found on `PATH` or via `CBC_EXECUTABLE`)

## Installation

From source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/enyr-srl/py-der-61850.git
cd py-der-61850
uv sync
```

Or with pip:

```bash
pip install git+https://github.com/enyr-srl/py-der-61850.git
```

## Usage

A user (POD) is described by a configuration validated by the `User` schema: devices, logical
nodes, data objects and their protocol mappings. The typical flow is:

```python
from py_der_61850.models.config_visitor import ConfigVisitor
from py_der_61850.models.image_process import ImageProcess
from py_der_61850.models.protocols.protocol_client_registry import ProtocolClientRegistry
from py_der_61850.models.user_schema import User
from py_der_61850.reflection.iec_61850_reflection_strategy import IEC61850ReflectionStrategy
from py_der_61850.reflection.reflection_service import ReflectionService
from py_der_61850.services.user_service import UserService

user = User(**user_config)  # dict loaded from your configuration store
registry = ProtocolClientRegistry()  # register the protocol clients your devices need

user_service = UserService(user=user, protocol_client_registry=registry)
image_process = ImageProcess(data_attributes=user_service.get_data_attributes())

strategy = IEC61850ReflectionStrategy(
    "py_der_61850.enyr_61850_2025a.logical_node",
    user_service,
    ConfigVisitor(user_config=user_config),
)
reflection = ReflectionService(strategy)

reflection.set_values(values)  # measurements read from the devices
reflection.call()  # run the logical nodes (forecasts, control, optimization)
setpoint = reflection.get_value("<user_id>_<device_id>_<ln_id>.<do_id>.<da_id>")
```

Data attribute ids follow the pattern `{user_id}_{device_id}_{ln_id}.{do_id}.{da_id}`.

## Key conventions

- Every data object carries value, quality and timestamp; they travel together from cloud to
  edge and must stay consistent with the commanded value.
- The cloud controller marks its battery setpoint `WSpt2` as `good`, `questionable` or
  `invalid`. The edge logic (`DPMC_2025a`) applies it only when the quality is `good`,
  otherwise it falls back to the local rule-based setpoint `WSpt1`.
- If the solver returns no usable solution, cloud setpoints are marked `invalid`; if the
  solution is too close to the rule-based control, `WSpt2` is marked `questionable`.

## Project structure

| Path | Content |
|---|---|
| `models/` | `User` schema, image process, protocol mappings |
| `services/` | image process construction from the user configuration |
| `reflection/` | IEC 61850-like reflection of logical nodes |
| `clients/` | protocol and vendor clients |
| `enyr_61850_2025a/` | logical nodes, data objects and enumerations, including the extensions |
| `tests/` | test suite |

## Development

```bash
uv sync
uv run pytest src/py_der_61850/tests
uv run pre-commit run --all-files
uv build
```

Applications importing the library in editable mode must be restarted after changes.

## Contributing

Issues and merge requests are welcome. By submitting a contribution you agree that it is
licensed under the same terms as the project.

## License

Copyright (C) ENYR S.r.l.

This program is free software: you can redistribute it and/or modify it under the terms of
the GNU Affero General Public License, version 3 only, as published by the Free Software
Foundation. See [LICENSE](LICENSE) for the full text.

Using this library in a network service (for example a cloud platform) counts as making it
available to its users: modified versions must be offered in source form under the same
license. For commercial licensing under different terms, contact ENYR.
