# Bottle stop detection

Bottle stops are periods during a CTD cast when the rosette is held stationary at a fixed depth (or rather, fixed wire-out), allowing instruments to equilibrate before firing a bottle (usually after about 30 seconds).
caldip automatically identifies these periods from the CTD pressure record using the algorithm described here.  The period of the bottle stop is normally chosen to be in relatively well-mixed (small changes in temperature and salinity in the vertical) so that even if the ship is heaving up and down a bit, the property changes are small.  The period in the middle of the bottle stop (after initial equilibration, before the rosette starts moving up again) is used as the intercomparison period between the standard CTD on the rosette and the values from the mooring instruments which are attached to the rosette.

The implementation is in `caldip/core.py:find_bottle_stops()`.

---

## Overview

The algorithm works in five stages:

1. Define the search region (after maximum depth - since bottle stops are normally done on the upcast)
2. Scan for periods with low-rates of heave (slower upward motion) using a 60-second forward window
3. Extend each candidate period to its natural end using sample-to-sample rates
4. Using this initially defined period, determine the median pressure.  Refine the boundaries of the bottle stop period to the time period where the pressure is near the median pressure (±2 dbar)
5. Merge nearby stops (in case a longer bottle stop gets separated into two by this algorithm), then discard short bottle stops.

---

## Stage 1 — Search region

The algorithm only looks for bottle stops once the CTD is near its maximum depth.
This avoids false detections from slow lowering or pauses in the upper water column.

1. Find the index of maximum pressure in the whole record.
2. Set a depth threshold: `max_pressure − 10 dbar`.
3. Find the **first** index where pressure ≥ this threshold (which occurs on the **descent**).
4. Bottle stop detection begins from that index and continues to the end of the record.

Because the search starts on the descent, stops detected near maximum depth are included, as well as all stops on the ascent.

---

## Stage 2 — Candidate detection (60-second window)

For each index `i` in the search region, the algorithm looks 60 seconds ahead to index `future_idx` and computes:

```
rate = |pressure[future_idx] − pressure[i]| / time_diff_minutes   (dbar/min)
```

If `rate < threshold_dbar_per_min` (default **10 dbar/min**), the CTD is considered stationary and a candidate bottle stop begins at `i`.

---

## Stage 3 — Extending the candidate

Once a candidate begins, the end is found by stepping forward one sample at a time from `future_idx`.
At each step, the **instantaneous** rate between consecutive samples is computed:

```
rate = |pressure[k+1] − pressure[k]| / time_diff_minutes
```

Extension continues until this sample-to-sample rate ≥ `threshold_dbar_per_min`, marking the end of the stable period.

The candidate is kept only if its duration is **≥ 30 seconds** (a loose pre-filter; the final minimum is 3 minutes).

After extension, the main loop jumps to the end of this candidate before scanning for the next one.

---

## Stage 4 — Boundary refinement (±2 dbar around median)

The raw candidate boundaries may include a few samples where the CTD was still settling.
To produce clean stop boundaries, the algorithm:

1. Computes the **median pressure** over the raw candidate (start to end inclusive).
2. **Refined start**: scans forward from the raw start and takes the **first** sample within 2 dbar of the median.
3. **Refined end**: scans backward from the raw end and takes the **last** sample within 2 dbar of the median.

The refined duration is recalculated from these tightened boundaries.
The pressure reported for the stop is the **median** over the raw (pre-refinement) window.

---

## Stage 5 — Merging and final filter

**Merging:** After all candidates are collected, any two consecutive stops whose indices are within **10 samples** of each other are merged into one.
The merged stop spans from the start of the first to the end of the second; its duration is recalculated accordingly; and its pressure is recalculated as the **mean** (not median) over all samples in the merged range.

**Final filter:** Stops whose (possibly merged) duration is **< `min_duration_seconds`** (default **180 s / 3 min**) are discarded.

---

## Statistics comparison window

The statistics reported in the CSV outputs are **not** computed over the full bottle stop.
For each stop, a comparison window of exactly **2 minutes** is used, ending **30 seconds before the stop end**:

```
comp_end   = stop_end_time − 30 s
comp_start = comp_end − 2 min
```

This avoids data at the very end of the stop (when the CTD may have started moving) and gives a stable, comparable window for all instruments.

---

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold_dbar_per_min` | 10.0 | Maximum pressure rate for a stable period (dbar/min) |
| `min_duration_seconds` | 180.0 | Minimum stop duration after merging (seconds) |

Both can be overridden on the command line for either subcommand:

```bash
caldip plot  castM4/ --threshold 8.0 --min-duration 240
caldip stats castM4/ --threshold 8.0 --min-duration 240
```

> **Important:** If you change these values, use the same values for both `caldip plot` and `caldip stats`. Different thresholds will produce different bottle stop lists, so the stops shown in the plot will not match those used to compute the statistics.

Statistics are computed over the 2-minute comparison window (within the full bottle stop period) described above, regardless of threshold settings.
