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
    except (OSError, ValueError) as exc:  # noqa: BLE001 - surfaced on the page
        return {"filename": nc_path.name, "error": str(exc)}
    with ds:
        return {
            "filename": nc_path.name,
            "filesize": _human_size(nc_path.stat().st_size),
            "dims": dict(ds.sizes),
            "coords": [_var_meta(n, ds[n]) for n in ds.coords],
            "data_vars": [_var_meta(n, ds[n]) for n in ds.data_vars],
            "global_attrs": {str(k): str(v) for k, v in ds.attrs.items()},
        }


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
    if ctd_attrs:
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
