"""inspector_registry (owner AG-01): the manifest registry of the batch mode.

Public API (import from the submodules to keep ``inspector-batch --help`` fast):

- ``manifest.Registry`` — document_manifest.jsonl + split_policy.json: objects, files, stages,
  sections, excluded ids enforced, citability (``is_citable``, ``page_in_range``, ``stage_accepts``);
- ``resolver.PathResolver`` — manifest row → local path, LocalFileStatus, lazy cached sha256;
- ``archives.list_archive`` / ``extract_member`` — zip/7z/rar listing with guards (never unrar);
- ``stages.resolve_stage`` — RD_ID_MIXED / UNKNOWN stage from generic signals;
- ``twins.link_loose`` / ``link_archive`` — DWG/DOCX ↔ PDF twins with confidence;
- ``duplicates.find_duplicates`` — exact and near-duplicates;
- ``inventory.Inventory`` — the per-object inventory report behind ``inspector-batch inventory``.
"""

__version__ = "0.1.0"
