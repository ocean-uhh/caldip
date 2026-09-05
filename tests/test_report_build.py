"""End-to-end tests for caldip.report.build_report on real caldip CSVs.

The CSV inputs are real caldip output committed under
``tests/test_fixtures/report`` (castM7: one flagged RBRsolo; castM5: sixteen
in-tolerance RBRsolos, with the varying ``ctd_sensor_used`` column). The figure
for castM7 is produced by Plotly at test time; castM5 is left without a saved plot
to exercise the graceful fallback.
"""

import shutil
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

from caldip.report import build_report

_FIXTURE = Path(__file__).parent / "test_fixtures" / "report"


@pytest.fixture
def results_dir(tmp_path):
    """A results directory with real CSVs and one genuine plot for castM7."""
    src = tmp_path / "cal_dip"
    src.mkdir()
    for csv in _FIXTURE.glob("*.csv"):
        shutil.copy(csv, src / csv.name)
    fig = go.Figure(go.Scatter(x=[0, 1], y=[3.7, 3.77], name="castM7"))
    fig.write_html(src / "castM7_plot.html")
    return src


def test_build_writes_index_and_cast_pages(results_dir, tmp_path):
    """build_report writes an index plus one page per discovered cast."""
    out = tmp_path / "report"
    index = build_report(results_dir, out, cruise_name="msm142_2026")
    assert index == out / "index.html"
    assert index.exists()
    assert (out / "casts" / "castM7.html").exists()
    assert (out / "casts" / "castM5.html").exists()


def test_bundle_written_once_and_referenced(results_dir, tmp_path):
    """The plotly bundle is a single sibling file, referenced by the cast page."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    assert (out / "plotly.min.js").exists()
    page = (out / "casts" / "castM7.html").read_text(encoding="utf-8")
    assert "src='../plotly.min.js'" in page
    assert "plotly-graph-div" in page
    # The bundle is not inlined into the page.
    assert "plotly.js v" not in page


def test_flag_count_is_instrument_level(results_dir, tmp_path):
    """castM7 shows one flagged instrument; castM5 shows none."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    index = (out / "index.html").read_text(encoding="utf-8")
    # castM7: 1 instrument, 1 flagged (flag class, right-aligned).
    assert "castM7" in index
    assert "<td class='num flag'>1</td>" in index
    # castM5: 16 instruments, 0 flagged (num class, header and data aligned).
    assert "<td class='num'>16</td>" in index
    assert "<td class='num'>0</td>" in index


def test_missing_plot_falls_back_gracefully(results_dir, tmp_path):
    """castM5 has no saved plot, so its page shows a note, not a broken figure."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    page = (out / "casts" / "castM5.html").read_text(encoding="utf-8")
    assert "No saved plot found" in page
    assert "src='../plotly.min.js'" not in page


def test_summary_and_detail_tables_present(results_dir, tmp_path):
    """Each cast page renders both the summary and per-stop detail tables."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    page = (out / "casts" / "castM7.html").read_text(encoding="utf-8")
    # The summary is labelled deepest-stop so it is not misread as a cast average.
    assert "Summary (deepest stop only)" in page
    assert "Per-stop detail" in page
    assert "101657" in page  # the castM7 serial


def test_uninferable_cruise_warns_and_labels_unk(tmp_path):
    """A results dir that is not a cal_dip/ folder yields cruise UNK with a warning."""
    src = tmp_path / "outputs"
    src.mkdir()
    for csv in _FIXTURE.glob("*.csv"):
        shutil.copy(csv, src / csv.name)
    out = tmp_path / "report"
    with pytest.warns(UserWarning, match="UNK"):
        build_report(src, out)  # no cruise_name, not a cal_dip dir
    assert "UNK" in (out / "index.html").read_text(encoding="utf-8")


def test_cruise_inferred_from_cal_dip_parent(tmp_path):
    """A cal_dip/ directory infers the cruise from its parent without warning."""
    cruise = tmp_path / "msm142_2026"
    src = cruise / "cal_dip"
    src.mkdir(parents=True)
    for csv in _FIXTURE.glob("*.csv"):
        shutil.copy(csv, src / csv.name)
    out = tmp_path / "report"
    build_report(src, out)  # no cruise_name; inferable from parent
    assert "msm142_2026" in (out / "index.html").read_text(encoding="utf-8")


def test_detail_row_shaded_when_flagged(results_dir, tmp_path):
    """A per-stop row caldip flagged as out of tolerance is shaded amber."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    # castM7's one row is "T reads high by 0.012" -> over threshold.
    page = (out / "casts" / "castM7.html").read_text(encoding="utf-8")
    assert "tr class='over-threshold'" in page


def test_bottle_stops_table_lifts_repeated_columns(results_dir, tmp_path):
    """Stop metadata is a separate table and removed from the per-stop detail."""
    out = tmp_path / "report"
    build_report(results_dir, out, cruise_name="msm142_2026")
    page = (out / "casts" / "castM5.html").read_text(encoding="utf-8")
    assert "<h2>Bottle stops</h2>" in page
    # The stop columns live in the bottle-stops table, not the per-stop detail.
    detail_section = page.split("<h2>Per-stop detail</h2>")[1]
    assert "<th>date</th>" not in detail_section
    assert "t<sub>start</sub>" not in detail_section
    assert "t<sub>end</sub>" not in detail_section


def _with_cruise(src_dir, dst_dir, cruise_by_cast):
    """Copy fixture CSVs into dst_dir, injecting a per-cast ``cruise`` column."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    for csv in _FIXTURE.glob("*.csv"):
        cast = csv.name.split("_")[0]
        frame = pd.read_csv(csv, dtype=str, keep_default_na=False)
        frame["cruise"] = cruise_by_cast[cast]
        frame.to_csv(dst_dir / csv.name, index=False)


def test_cruise_recovered_from_csv_column(tmp_path):
    """A uniform cruise recorded in the CSVs is used as the masthead, no warning."""
    src = tmp_path / "outputs"
    _with_cruise(_FIXTURE, src, {"castM7": "msm142_2026", "castM5": "msm142_2026"})
    out = tmp_path / "report"
    build_report(src, out)  # no --cruise; recovered from the CSVs
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "msm142_2026" in index
    # single cruise -> no redundant Cruise column
    assert "<th>Cruise</th>" not in index


def test_mixed_cruises_get_a_column(tmp_path):
    """Casts spanning cruises get a Cruise column and a 'multiple cruises' label."""
    src = tmp_path / "outputs"
    _with_cruise(_FIXTURE, src, {"castM7": "odb_2026", "castM5": "msm142_2026"})
    out = tmp_path / "report"
    build_report(src, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "<th>Cruise</th>" in index
    assert "odb_2026" in index and "msm142_2026" in index
    assert "multiple cruises" in index


def test_empty_results_dir_raises(tmp_path):
    """A directory with no detailed CSVs raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        build_report(tmp_path, tmp_path / "out")
