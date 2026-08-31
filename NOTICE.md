# NOTICE

This repository is a combination of independently licensed components.
Do not relicense files that already carry their own license.

## Data fabric (repository root, excluding `mirofish/` and `eve/`)

MIT License. See `LICENSE`.

Includes the EVE-MIRO data fabric, world state, API, dashboard, adapters,
tests, and compose wiring.

## `mirofish/`

GNU Affero General Public License v3.0. See `mirofish/LICENSE`.
Origin: see `mirofish/ORIGIN.txt`.

A combined distribution that includes `mirofish/` is subject to AGPL-3.0
for that component. MiroFish files stay AGPL-3.0.

## `eve/`

MIT License. See `eve/LICENSE`.
Origin: see `eve/ORIGIN.txt`.

EVE files stay MIT under their own copyright notice.

## Runtime boundary

The intended process boundary between the MIT data fabric and the AGPL-3.0
MiroFish engine is HTTP/IPC: the fabric talks to a MiroFish process. The
combined in-tree copy in this repository talks to that process (fail closed:
`EngineNotConfigured` if the process is down). Python 3.12 is the intended combined runtime because
upstream MiroFish targets <3.13; fabric tests may still run on 3.13. The
fabric `requires-python` is not pinned below 3.13 so local 3.13 venvs keep
working.
