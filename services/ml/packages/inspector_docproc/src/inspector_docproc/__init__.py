"""inspector_docproc package.

ONNX Runtime telemetry is switched off here, before any module of this package imports ``onnxruntime``.
ORT ≥ 1.2x on macOS/Linux starts the Microsoft 1DS telemetry client (``PosixTelemetry``) when the module is
imported: two to six extra native threads and an HTTPS upload about 8 s later (measured: an ESTABLISHED
TCP connection to port 443 from every process that creates a session). Two consequences:

- product code must make no network calls (CLAUDE.md rule 6), and this one leaves the machine;
- it is the cause of the exit-134 abort seen at M0: at ``exit()`` the static ``PosixEnv`` destructor tears the
  telemetry log manager down on the main thread while its worker thread still dispatches a debug event and
  locks a ``std::recursive_mutex`` that is already destroyed («recursive_mutex lock failed: Invalid argument»,
  ``Microsoft::Applications::Events::DebugEventSource::DispatchEvent``; macOS crash reports of
  2026-09-27/28).

``ORT_DISABLE_TELEMETRY=1`` is read once, when ``onnxruntime`` is first imported; set later it has no effect
(and ``onnxruntime.disable_telemetry_events()`` stops neither the threads nor the upload). Spawned worker and
detection-server processes inherit the variable. ``ORT_TELEMETRY_PREIMPORTED`` records whether the current
process imported ``onnxruntime`` before this package could disable it (then only the process that imported it
first can fix it: set the variable in its environment or at its entry point).
"""

import os as _os
import sys as _sys

__version__ = "0.1.0"

ORT_TELEMETRY_ENV = "ORT_DISABLE_TELEMETRY"
ORT_TELEMETRY_PREIMPORTED: bool = "onnxruntime" in _sys.modules and _os.environ.get(ORT_TELEMETRY_ENV) != "1"
_os.environ.setdefault(ORT_TELEMETRY_ENV, "1")
