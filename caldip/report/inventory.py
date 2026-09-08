"""Build a per-file netCDF *inventory* page: dimensions, variables, attributes.

A viewable "what was generated" view of a ``{cast}_caldip.nc`` file — the
counterpart to ``ncdump -h``, styled with the shared report design system. The
inventory is read as plain data by :func:`read_nc_meta` and rendered by
:func:`build_inventory_html`; :func:`write_inventory` writes the HTML file. Used
by the ``caldip inspect`` command and linkable from the per-cruise report.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import xarray as xr

from caldip.report._html import masthead, page


def _human_size(n_bytes: int) -> str:
    """Return a human-readable file size (e.g. ``"6.7 KB"``)."""
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _var_meta(name: str, da: xr.DataArray) -> dict[str, str]:
    """Return the inventory row (name, dtype, dims, shape, units, notes)."""
    attrs = da.attrs
    if "flag_values" in attrs:
        notes = f"flags: {attrs.get('flag_meanings', '')}"
        if "flagging_threshold" in attrs:
            notes += f" (threshold {attrs['flagging_threshold']})"
    elif "comment" in attrs:
        notes = str(attrs["comment"])
    else:
        notes = str(attrs.get("long_name", ""))
    return {
        "name": name,
        "dtype": str(da.dtype),
        "dims": " × ".join(map(str, da.dims)) or "scalar",
        "shape": " × ".join(str(s) for s in da.shape) or "scalar",
        "units": str(attrs.get("units", "")),
        "notes": notes,
    }


# Reference-finality facts shown as an "as recorded / now" pair on the inventory.
# The value is whether the CTD reference has *finished*, not whether output is stale
# (offsets are measurements, not a cache). The two gates are ``data_mode == "D"``
# and ``preferred_pair`` declared. ``preferred_pair`` is a planned ctdcast attribute;
# until it ships, both sides read ``undeclared``.
_REFERENCE_FIELDS = (
    "data_mode",
    "preferred_pair",
    "ctd_stage",
    "source_tracking_id",
    "ctd_temp_sensor_serial",
    "ctd_temp_sensor_caldate",
    "ctd_cond_sensor_serial",
    "ctd_cond_sensor_caldate",
    "ctd_conductivity_slope",
    "ctd_cond_slope_adjusted",
    "ctd_temp_processing_level",
    "ctd_cond_processing_level",
    "ctd_press_processing_level",
)


def _reference_now(ctd_path: str, ctd_sensor: str) -> dict[str, str] | None:
    """Read the recorded ctdcast reference file's *current* provenance.

    Reuses :func:`caldip.readers.read_ctdcast_reference` so the compared fields are
    exactly the ones written, and returns ``None`` when the reference is a ``.cnv``,
    is missing/unreadable, or is not a ctdcast file (nothing to compare against).
    """
    path = Path(ctd_path)
    if ctd_path in ("", "UNK") or not path.exists():
        return None
    try:
        from caldip.readers import _is_ctdcast_nc, read_ctdcast_reference

        try:
            sensor = int(ctd_sensor)
        except (TypeError, ValueError):
            sensor = 1
        with xr.open_dataset(path, engine="netcdf4") as ds:
            if not _is_ctdcast_nc(ds):
                return None
            _, provenance = read_ctdcast_reference(ds, sensor)
            now = {k: str(v) for k, v in provenance.items()}
            now["preferred_pair"] = str(ds.attrs.get("preferred_pair", "undeclared"))
        return now
    except Exception:  # noqa: BLE001 - the page degrades to recorded-only on any read error
        return None


def _reference_state(nc_attrs: dict[str, str]) -> dict[str, Any] | None:
    """Build the *as recorded / now* comparison for the CTD-reference block.

    Returns ``None`` when the output has no ctdcast reference (e.g. the ``.cnv``
    path), otherwise a dict with the reference file path, the per-field rows
    (recorded, now, changed), whether the current reference was reachable, and the
    two finality gates read from the current file.
    """
    if str(nc_attrs.get("source_tracking_id", "UNK")) == "UNK":
        return None  # .cnv path or no ctdcast reference — nothing to compare
    now = _reference_now(
        str(nc_attrs.get("ctd_path", "")), str(nc_attrs.get("ctd_sensor_used", "1"))
    )
    rows = []
    for field in _REFERENCE_FIELDS:
        recorded = str(nc_attrs.get(field, "—"))
        current = now.get(field, "—") if now else ""
        rows.append(
            {
                "field": field,
                "recorded": recorded,
                "now": current,
                # A field not recorded at run time ("—", e.g. preferred_pair before
                # it is added to the output) is not a *change*, only a not-yet-recorded.
                "changed": bool(now) and recorded != "—" and recorded != current,
            }
        )
    finished = bool(now) and now.get("data_mode") == "D"
    pair_declared = bool(now) and now.get("preferred_pair", "undeclared") not in (
        "undeclared",
        "UNK",
        "—",
    )
    return {
        "ctd_path": str(nc_attrs.get("ctd_path", "—")),
        "rows": rows,
        "now_available": bool(now),
        "data_mode_final": finished,
        "preferred_pair_declared": pair_declared,
    }


def read_nc_meta(nc_path: Path) -> dict[str, Any]:
    """Read a netCDF file into a plain-data inventory.

    Parameters
    ----------
    nc_path : pathlib.Path
        The netCDF file to inventory.

    Returns
    -------
    dict
        ``filename``, ``filesize`` (human-readable), ``dims``, ``coords`` and
        ``data_vars`` (each a :func:`_var_meta` row), and ``global_attrs`` in the
        file's own order. On a read error, ``{"filename", "error"}`` so the page
        can report it rather than fail.
    """
    nc_path = Path(nc_path)
    try:
        ds = xr.open_dataset(nc_path, engine="netcdf4")
    except (OSError, ValueError) as exc:
        return {"filename": nc_path.name, "error": str(exc)}
    with ds:
        global_attrs = {str(k): str(v) for k, v in ds.attrs.items()}
        meta = {
            "filename": nc_path.name,
            "filesize": _human_size(nc_path.stat().st_size),
            "dims": dict(ds.sizes),
            "coords": [_var_meta(n, ds[n]) for n in ds.coords],
            "data_vars": [_var_meta(n, ds[n]) for n in ds.data_vars],
            "global_attrs": global_attrs,
        }
    meta["reference_state"] = _reference_state(global_attrs)
    return meta


def _dims_table(dims: dict[str, int]) -> str:
    """Render the dimension sizes as an HTML table."""
    if not dims:
        return "<p>(no dimensions)</p>"
    body = "\n".join(
        f"<tr><td class='mono'>{escape(k)}</td><td class='num'>{v}</td></tr>"
        for k, v in dims.items()
    )
    head = "<tr><th>Dimension</th><th class='num'>Size</th></tr>"
    return f"<table>\n{head}\n{body}\n</table>"


def _var_table(rows: list[dict[str, str]]) -> str:
    """Render variable/coordinate inventory rows as an HTML table."""
    head = (
        "<tr><th>Name</th><th>Type</th><th>Dims</th><th>Shape</th>"
        "<th>Units</th><th>Notes</th></tr>"
    )
    body = "\n".join(
        "<tr>"
        f"<td class='mono'>{escape(r['name'])}</td>"
        f"<td class='mono'>{escape(r['dtype'])}</td>"
        f"<td class='mono'>{escape(r['dims'])}</td>"
        f"<td class='mono num'>{escape(r['shape'])}</td>"
        f"<td>{escape(r['units'])}</td>"
        f"<td>{escape(r['notes'])}</td>"
        "</tr>"
        for r in rows
    )
    return f"<table>\n{head}\n{body}\n</table>"


def _attr_table(attrs: dict[str, str]) -> str:
    """Render global attributes (name, value) as an HTML table."""
    body = "\n".join(
        f"<tr><td class='mono'>{escape(k)}</td><td>{escape(v)}</td></tr>"
        for k, v in attrs.items()
    )
    return f"<table>\n<tr><th>Attribute</th><th>Value</th></tr>\n{body}\n</table>"


def _reference_table(state: dict[str, Any]) -> str:
    """Render the CTD-reference *as recorded / now* comparison as HTML."""
    path_line = (
        f"<p>Reference file: <span class='mono'>{escape(state['ctd_path'])}</span></p>"
    )
    if not state["now_available"]:
        note = (
            "<p class='warn'>The recorded reference is not reachable from here, so "
            "only the values recorded at run time are shown.</p>"
        )
        head = "<tr><th>Attribute</th><th>As recorded</th></tr>"
        body = "\n".join(
            f"<tr><td class='mono'>{escape(r['field'])}</td>"
            f"<td>{escape(r['recorded'])}</td></tr>"
            for r in state["rows"]
        )
        return path_line + note + f"<table>\n{head}\n{body}\n</table>"

    def _gate(ok: bool, label: str) -> str:
        return f"{label} {'✓' if ok else '✗'}"

    finality = (
        "<p>Reference finished: "
        f"{_gate(state['data_mode_final'], 'data_mode = D')} · "
        f"{_gate(state['preferred_pair_declared'], 'preferred_pair declared')}</p>"
    )
    head = "<tr><th>Attribute</th><th>As recorded</th><th>Now</th></tr>"
    row_html = []
    for r in state["rows"]:
        tr = "<tr class='over-threshold'>" if r["changed"] else "<tr>"
        row_html.append(
            f"{tr}<td class='mono'>{escape(r['field'])}</td>"
            f"<td>{escape(r['recorded'])}</td>"
            f"<td>{escape(r['now'])}</td></tr>"
        )
    body = "\n".join(row_html)
    return path_line + finality + f"<table>\n{head}\n{body}\n</table>"


def build_inventory_html(nc_path: Path) -> str:
    """Build the netCDF inventory HTML for a file.

    Parameters
    ----------
    nc_path : pathlib.Path
        The netCDF file to inventory.

    Returns
    -------
    str
        A complete self-contained HTML document.
    """
    meta = read_nc_meta(nc_path)
    if "error" in meta:
        body = (
            masthead(
                meta["filename"], type_label="netCDF inventory", sub="could not be read"
            )
            + f"<p class='warn'>{escape(meta['error'])}</p>"
        )
        return page(f"{meta['filename']} — inventory", body)

    dims = " · ".join(f"{k} = {v}" for k, v in meta["dims"].items())
    head = masthead(
        meta["filename"],
        type_label="netCDF inventory",
        sub=f"{dims} · {meta['filesize']}",
    )
    # CTD-reference attributes are grouped apart from file/provenance attributes.
    ctd_attrs = {k: v for k, v in meta["global_attrs"].items() if k.startswith("ctd_")}
    file_attrs = {
        k: v for k, v in meta["global_attrs"].items() if not k.startswith("ctd_")
    }
    parts = [
        head,
        "<h2>Dimensions</h2>",
        _dims_table(meta["dims"]),
        "<h2>Coordinates</h2>",
        _var_table(meta["coords"]),
        "<h2>Variables</h2>",
        _var_table(meta["data_vars"]),
        "<h2>Global attributes</h2>",
        _attr_table(file_attrs),
    ]
    if meta.get("reference_state"):
        parts.append("<h3>CTD reference — as recorded / now</h3>")
        parts.append(_reference_table(meta["reference_state"]))
        if ctd_attrs:
            parts.append("<h3>CTD reference — all recorded attributes</h3>")
            parts.append(_attr_table(ctd_attrs))
    elif ctd_attrs:
        parts.append("<h3>CTD reference</h3>")
        parts.append(_attr_table(ctd_attrs))
    return page(f"{meta['filename']} — inventory", "\n".join(parts))


def write_inventory(nc_path: Path, out_path: Path) -> Path:
    """Write the netCDF inventory HTML for ``nc_path`` to ``out_path``.

    Parameters
    ----------
    nc_path : pathlib.Path
        The netCDF file to inventory.
    out_path : pathlib.Path
        Destination HTML path; parent directories are created.

    Returns
    -------
    pathlib.Path
        The written ``out_path``.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_inventory_html(nc_path), encoding="utf-8")
    return out_path
