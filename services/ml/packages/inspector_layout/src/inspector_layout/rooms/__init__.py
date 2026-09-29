"""Room index, tag grammar and per-room inventories of drawing sheets (96 R-15, 95 R8; owner AG-02B).

Modules:
- :mod:`.grammar` — exact room tokens («012» keeps its zero), the vent/heating tag grammar, homoglyph folding,
  flows and duct sizes, and the closed-vocabulary spotter;
- :mod:`.tokens` — page tokens in displayed points (PageTokens of AG-02A, or the text layer as a fallback);
- :mod:`.labels` — room labels on plans (number in a circle), schematics («142 Астрономии…») and
  explications, and the floor of a sheet;
- :mod:`.zones` — room regions from the wall layers (seeded watershed) or label Voronoi;
- :mod:`.tags` — tag instances and their room (leader, containment, nearest label);
- :mod:`.page` / :mod:`.fileproc` — the per-page and per-file pipeline (LayoutArtifacts fields ``rooms``,
  ``tags``, ``cad_layers``, ``revision_clouds``);
- :mod:`.inventory` — per-room multisets of tags and elements; :mod:`.index` — the cross-sheet room index and
  PD↔RD plan matching.
"""
