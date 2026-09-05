"""caldip's concrete report stylesheet, from the package-neutral ``emit_css``.

This is the package-specific wiring the vendored :mod:`caldip.report._css`
deliberately omits: the single place caldip's accent is applied to the shared
generator. The vendored ``_css.py`` and ``config/report_tokens.py`` carry no
package-specific edit, so re-vendoring them from a sister repo (oceanarray,
ctdcast) is a byte-identical copy.

caldip adds a few rules the shared sheet does not provide — a container for the
interactive Plotly figure (the shared system embeds static PNGs) and a flagged
count colour — in :data:`CALDIP_LOCAL_CSS`, layered after the shared sheet and
referencing shared token variables so no value is hand-picked.
"""

from __future__ import annotations

from caldip.report._css import _JS_TOP_LINKS, emit_css

#: caldip's package accent — chosen here, locally, not in the vendored tokens.
#: Points at ``--role-aggregate-a`` (#8e44ad, purple), a defined palette token, so
#: caldip is visually distinct from the navy (``--ocean``) processing reports
#: (oceanarray, ctdcast): caldip is a calibration *diagnostic*, a different kind of
#: document. Purple is chosen because it carries no semantic status meaning (unlike
#: --ok green / --error red / --warn orange), so it is not misread as a flag.
#: Change this one line to rebrand; any CSS colour value works, but prefer a
#: palette token so it stays inside the design system.
PACKAGE_ACCENT: str = "var(--role-aggregate-a)"

#: The generated shared stylesheet, ready to concatenate into a page ``<style>``.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

#: caldip-only rules, layered after the shared sheet. The interactive figure needs
#: a sized container (the shared system uses static ``<figure><img>``); the flag
#: colour reuses the shared ``--error`` token.
CALDIP_LOCAL_CSS: str = """\
.figure-wrap {
  width: 100%; margin: 0.6rem 0 1.5rem; overflow: hidden;
  border: 1px solid var(--rule); border-radius: var(--radius-btn);
}
td.flag { color: var(--error); font-weight: 600; }
th .unit { font-weight: 400; opacity: 0.8; font-size: var(--fs-xs); }
tr.over-threshold td { background: var(--warn-bg); }
"""

__all__ = ["SHARED_CSS", "CALDIP_LOCAL_CSS", "PACKAGE_ACCENT", "_JS_TOP_LINKS"]
