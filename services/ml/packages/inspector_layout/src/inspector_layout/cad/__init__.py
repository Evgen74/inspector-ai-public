"""CAD layer (OCG) toolkit for drawing sheets (95 R2/R4, 97 §2.13 F6; owner AG-02B).

- :mod:`.geometry` — vector paths of a page in displayed points, flattened per layer;
- :mod:`.layers` — document layers, their classes (walls, ducts, text, leaders, revisions …), isolated renders
  and per-layer token attribution;
- :mod:`.clouds` — revision clouds from «Изм.» layers and from cloud-shaped arc chains;
- :mod:`.leaders` — leader lines (выноски): from a label to the point it annotates.
"""
