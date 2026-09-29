"""inspector_compare (AG-04): comparators, atomic split, anchor pages, the 132-row precedence, the submission
exporter (full, strict, sidecar) and the Приложение 2 protocol (JSON, DOCX, PDF).

Entry points:

- ``inspector_compare.engine.compare_object``: run the comparators on one object → finding groups + findings;
- ``inspector_compare.export.submission.build_submission``: findings → organizer submission (extended, strict);
- ``inspector_compare.protocol.builder.build_protocol``: findings → canonical protocol JSON (contract ``protocol``);
- ``inspector_compare.batch``: the ``inspector-batch compare`` / ``export`` commands.
"""

from inspector_compare.version import COMPARE_VERSION

__version__ = COMPARE_VERSION

__all__ = ["COMPARE_VERSION", "__version__"]
