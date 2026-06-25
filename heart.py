#!/usr/bin/env python3
"""Mathematical heart-graph simulator for the terminal.

Renders the implicit curve

        x^2 - a*|x|*y + b*y^2 - r <= 0

with Unicode half-blocks (sub-pixel vertical resolution) in a Cartesian
plane centred on the terminal.  Two modes are available:

  * build-up mode  : animate b: 0->1 (vertical band -> disk), then a: 0->1
                     (disk -> heart).
  * parameter mode : use the arrow keys to grow/shrink r in real time.

Pure standard library only (curses + math).
"""

import argparse
import math
import sys

# --------------------------------------------------------------------------
# Constants (tuned in a prior design session)
# --------------------------------------------------------------------------
R_MIN = 1
R_MAX = 100
R_DEFAULT = 30
R_STEP = 2
OVERFILL = 1.55

# The curve x^2 - |x|y + y^2 = r reaches its maximum vertical extent at
# |y| = 2*sqrt(r/3) = (2/sqrt(3)) * sqrt(r).  Keep that factor handy.
EXTENT_FACTOR = 2.0 / math.sqrt(3.0)  # ~= 1.1547

# Dark-red -> pink gradient (256-colour xterm palette indices).
PALETTE = [52, 88, 124, 160, 196, 197, 199, 205, 218]

# Half-block glyphs: upper, lower, full.
UPPER, LOWER, FULL = "▀", "▄", "█"

# Build-up timing.
BUILD_SECONDS_PER_PHASE = 1.2


# --------------------------------------------------------------------------
# Geometry / scaling
# --------------------------------------------------------------------------
def compute_scale(graph_rows):
    """Sub-pixels (half-block rows) per math unit.

    Fixed so that at r = R_MAX the heart overfills the graph area by
    OVERFILL.  Because half-blocks are roughly square, the same scale is
    used for the horizontal (per-cell) axis.
    """
    if graph_rows <= 0:
        return 1.0
    return OVERFILL * graph_rows / (EXTENT_FACTOR * math.sqrt(R_MAX))


def render_frame(cols, rows, a, b, r, scale):
    """Compute the glyph grid for one frame.

    Returns a list (length ``rows``) of lists (length ``cols``) of
    ``(char, depth)`` tuples, where ``depth`` in [0, 1] is the normalised
    interior depth (0 at the edge, 1 deepest) and is -1.0 for empty cells.

    The hot inner loop only does local-variable lookups and multiplies; all
    per-column and per-row terms are pre-computed.
    """
    cx = (cols - 1) / 2.0

    # Per-column terms: x^2 and |x|.
    x2 = [0.0] * cols
    ax = [0.0] * cols
    inv = 1.0 / scale
    for c in range(cols):
        xc = (c - cx) * inv
        x2[c] = xc * xc
        ax[c] = xc if xc >= 0.0 else -xc

    # Per-sub-pixel terms: y and y^2.  There are 2*rows sub-pixels; the
    # vertical centre sits between sub-pixel indices, hence the -0.5.
    n_sub = 2 * rows
    ys = [0.0] * n_sub
    y2 = [0.0] * n_sub
    cyy = rows - 0.5
    for i in range(n_sub):
        yi = (cyy - i) * inv
        ys[i] = yi
        y2[i] = yi * yi

    inv_r = 1.0 / r if r else 1.0
    grid = []
    for j in range(rows):
        it = 2 * j
        ib = it + 1
        ayt = a * ys[it]
        byt2 = b * y2[it]
        ayb = a * ys[ib]
        byb2 = b * y2[ib]
        row = []
        append = row.append
        for c in range(cols):
            x2c = x2[c]
            axc = ax[c]
            vt = x2c - ayt * axc + byt2
            vb = x2c - ayb * axc + byb2
            in_t = vt <= r
            in_b = vb <= r
            if in_t and in_b:
                ch = FULL
                v = vt if vt < vb else vb
            elif in_t:
                ch = UPPER
                v = vt
            elif in_b:
                ch = LOWER
                v = vb
            else:
                append((" ", -1.0))
                continue
            append((ch, (r - v) * inv_r))
        grid.append(row)
    return grid


# --------------------------------------------------------------------------
# ASCII (single frame to stdout, no curses)
# --------------------------------------------------------------------------
def run_ascii(cols, rows, r):
    scale = compute_scale(rows)
    grid = render_frame(cols, rows, 1.0, 1.0, r, scale)
    out = "\n".join("".join(ch for ch, _ in row) for row in grid)
    sys.stdout.write(out + "\n")


# --------------------------------------------------------------------------
# Interactive curses app
# --------------------------------------------------------------------------
def run_curses(stdscr, r0, do_build, fps):
    import curses

    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(max(1, int(1000 / fps)))

    # Colour setup.
    use_color = curses.has_colors()
    color256 = False
    if use_color:
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            use_color = False
    if use_color and curses.COLORS >= 256:
        color256 = True
        for i, col in enumerate(PALETTE):
            curses.init_pair(i + 1, col, -1)
    elif use_color:
        curses.init_pair(1, curses.COLOR_RED, -1)

    n_pal = len(PALETTE)

    def attr_for(depth):
        if color256:
            idx = int(depth * n_pal)
            if idx >= n_pal:
                idx = n_pal - 1
            elif idx < 0:
                idx = 0
            return curses.color_pair(idx + 1)
        if use_color:
            return curses.color_pair(1) | curses.A_BOLD
        return curses.A_BOLD

    # State.
    r = float(r0)
    building = do_build
    t = 0.0  # build-up progress, 0 -> 2
    build_step = 1.0 / (fps * BUILD_SECONDS_PER_PHASE)

    while True:
        try:
            maxy, maxx = stdscr.getmaxyx()
        except curses.error:
            maxy, maxx = 24, 80
        graph_rows = max(1, maxy - 1)  # reserve last line for the status bar
        cols = max(1, maxx)
        scale = compute_scale(graph_rows)

        if building:
            t += build_step
            if t >= 2.0:
                t = 2.0
                building = False
            b = t if t < 1.0 else 1.0
            a = 0.0 if t < 1.0 else (t - 1.0 if t < 2.0 else 1.0)
        else:
            a = b = 1.0

        grid = render_frame(cols, graph_rows, a, b, r, scale)

        stdscr.erase()
        for j, row in enumerate(grid):
            x = 0
            n = len(row)
            while x < n:
                ch, depth = row[x]
                if ch == " ":
                    x += 1
                    continue
                attr = attr_for(depth)
                seg = [ch]
                k = x + 1
                while k < n:
                    ch2, d2 = row[k]
                    if ch2 == " " or attr_for(d2) != attr:
                        break
                    seg.append(ch2)
                    k += 1
                try:
                    stdscr.addstr(j, x, "".join(seg), attr)
                except curses.error:
                    pass
                x = k

        # Status bar.
        pct = (r - R_MIN) / (R_MAX - R_MIN) * 100.0 if R_MAX > R_MIN else 0.0
        status = " r=%3d (%3.0f%%)  ←/→ size · b build · r reset · q quit" % (
            int(round(r)),
            pct,
        )
        if building:
            status += "  [BUILDING]"
        elif r >= R_MAX:
            status += "  [FLOODED]"
        status = status[: max(0, maxx - 1)].ljust(max(0, maxx - 1))
        try:
            stdscr.addstr(maxy - 1, 0, status, curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch in (ord("q"), ord("Q")):
            break
        elif ch == curses.KEY_LEFT:
            r = max(R_MIN, r - R_STEP)
        elif ch == curses.KEY_RIGHT:
            r = min(R_MAX, r + R_STEP)
        elif ch in (ord("b"), ord("B")):
            building = True
            t = 0.0
        elif ch in (ord("r"), ord("R")):
            r = float(R_DEFAULT)
            building = False
            t = 2.0


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Mathematical heart-graph simulator for the terminal."
    )
    parser.add_argument(
        "--r", type=int, default=R_DEFAULT,
        help="initial size parameter r (%d..%d, default %d)" % (R_MIN, R_MAX, R_DEFAULT),
    )
    parser.add_argument(
        "--no-build", action="store_true",
        help="skip the build-up animation; show the heart immediately",
    )
    parser.add_argument(
        "--fps", type=int, default=30, help="frames per second (default 30)"
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="render a single frame to stdout (no curses); use with --cols/--rows",
    )
    parser.add_argument("--cols", type=int, default=80, help="columns for --ascii (default 80)")
    parser.add_argument("--rows", type=int, default=40, help="rows for --ascii (default 40)")
    args = parser.parse_args(argv)

    r = max(R_MIN, min(R_MAX, args.r))
    fps = max(1, args.fps)

    if args.ascii:
        run_ascii(max(1, args.cols), max(1, args.rows), r)
        return 0

    import curses

    try:
        curses.wrapper(run_curses, r, not args.no_build, fps)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
