import logging

# See docs for usage and input format: linear_interpolate_2d.md
# Physical meanings used throughout this module:
# - x: time gap, seconds (float)
# - y: ego vehicle speed, meters per second (m/s)
# - z: desired following distance, meters (m)

def linear_interpolate(y_array, z_array, y_input):
    """Perform 1D linear interpolation with sorted pairing.

        - y_array, z_array: iterables of same length >= 2 (when provided via the
            interactive CLI they may be entered as comma- or space-separated numbers)
        - y_input: float-like

        The function sorts `y_array` ascending and reorders `z_array` accordingly,
    then finds the interval that contains `y_input` and returns the linear
    interpolation. If `y_input` is outside the `y_array` range, the function
    linearly extrapolates using the nearest two points.

    Raises ValueError for invalid inputs.
    """
    # Convert to lists
    ys = list(y_array)
    zs = list(z_array)

    if len(ys) != len(zs):
        raise ValueError("y_array and z_array must have the same length")
    if len(ys) < 2:
        raise ValueError("Need at least two points for interpolation")

    # Pair and sort by y
    pairs = sorted(zip(ys, zs), key=lambda p: p[0])

    # Merge duplicate y: if duplicate y have equal z -> drop duplicate and log info;
    # if duplicate y have different z -> error
    ys_sorted = []
    zs_sorted = []
    last_y = None
    last_z = None
    for yi, zi in pairs:
        if last_y is None or yi != last_y:
            ys_sorted.append(yi)
            zs_sorted.append(zi)
            last_y = yi
            last_z = zi
        else:
            # duplicate y encountered
            if zi == last_z:
                logging.info("Duplicate y=%s with identical z=%s removed during interpolation prep", yi, zi)
                # skip duplicate
                continue
            else:
                raise ValueError(f"Duplicate y value {yi} has conflicting z values: {last_z} vs {zi}")

    # fast path: exact match
    for yi, zi in zip(ys_sorted, zs_sorted):
        if y_input == yi:
            return zi

    # find interval
    if y_input < ys_sorted[0]:
        i0, i1 = 0, 1
    elif y_input > ys_sorted[-1]:
        i0, i1 = len(ys_sorted) - 2, len(ys_sorted) - 1
    else:
        # y_input in [ys_sorted[0], ys_sorted[-1]]
        # find right index such that ys_sorted[i0] < y_input < ys_sorted[i1]
        i1 = next(i for i, yv in enumerate(ys_sorted) if yv > y_input)
        i0 = i1 - 1

    y0, z0 = ys_sorted[i0], zs_sorted[i0]
    y1, z1 = ys_sorted[i1], zs_sorted[i1]

    # Avoid division by zero for duplicate y (after sorting)
    if y1 == y0:
        return float(z0)

    t = (y_input - y0) / (y1 - y0)
    return float(z0 + t * (z1 - z0))


def linear_interpolate_2d(x_array, y_array, z_array, x_input, y_input):
    """2D interpolation over a regular grid.

        - x_array: iterable of length nx (if nx == 1, function falls back to 1D over y)
            Physical meaning: `x` represents time gap in seconds.
        - y_array: iterable of length ny
            Physical meaning: `y` represents ego vehicle speed in m/s.
        - z_array: either a flat iterable of length nx*ny or an iterable of nx iterables each length ny
            Physical meaning: `z` represents desired following distance in meters for each (x,y) grid node.
        - x_input, y_input: query point (x_input ignored if nx == 1)

    If `len(x_array) == 1` the function degrades to 1D interpolation over y
    using `linear_interpolate(y_array, z_array_for_single_x, y_input)` and
    logs an informational message that `x_input` is ignored.
    """
    xs = list(x_array)
    ys = list(y_array)

    nx = len(xs)
    ny = len(ys)

    if nx == 0 or ny == 0:
        raise ValueError("x_array and y_array must be non-empty")
    if ny < 2:
        raise ValueError("y_array must have at least two elements")

    # Normalize z_array to a 2D list of shape (nx, ny)
    zs2d = None
    zlist = list(z_array)
    # if z_array is provided as nested iterables (rows for each x)
    if len(zlist) == nx and all(hasattr(row, '__iter__') for row in zlist):
        # convert each row to list and check lengths
        zs2d = [list(row) for row in zlist]
        if any(len(row) != ny for row in zs2d):
            raise ValueError('z_array rows must each have length equal to len(y_array)')
    else:
        # expect flat list of length nx*ny
        if len(zlist) != nx * ny:
            raise ValueError('z_array length must be nx*ny when provided as flat list')
        zs2d = [zlist[i * ny:(i + 1) * ny] for i in range(nx)]

    # --- Sorting and deduplication ---
    # Sort by y first: create permutation for y, reorder columns of zs2d accordingly
    # Build list of (y, original_col_index)
    y_idx = sorted(enumerate(ys), key=lambda p: p[1])  # (orig_idx, yval) sorted by yval
    y_order = [idx for idx, _ in y_idx]
    ys_sorted_by = [val for _, val in y_idx]
    # reorder columns in zs2d according to y_order
    zs2d_recol = []
    for row in zs2d:
        zs2d_recol.append([row[j] for j in y_order])

    # deduplicate y: if duplicate y values exist, check column-wise equality across rows
    new_ys = []
    col_map = []  # map from new column index to old column indices merged
    i = 0
    while i < len(ys_sorted_by):
        j = i + 1
        merged_idxs = [i]
        while j < len(ys_sorted_by) and ys_sorted_by[j] == ys_sorted_by[i]:
            merged_idxs.append(j)
            j += 1
        if len(merged_idxs) == 1:
            new_ys.append(ys_sorted_by[i])
            col_map.append([merged_idxs[0]])
        else:
            # check that for every row in zs2d_recol, all entries in these columns are equal
            for r in range(len(zs2d_recol)):
                vals = [zs2d_recol[r][k] for k in merged_idxs]
                if any(val != vals[0] for val in vals):
                    raise ValueError('Duplicate y with conflicting z column values')
            # keep single column
            new_ys.append(ys_sorted_by[i])
            col_map.append(merged_idxs)
        i = j

    # construct zs2d with deduped columns
    zs2d_dedup_cols = []
    for r in range(len(zs2d_recol)):
        new_row = [zs2d_recol[r][idxs[0]] for idxs in col_map]
        zs2d_dedup_cols.append(new_row)

    # update ys and ny
    ys = new_ys
    ny = len(ys)

    # Now sort by x and deduplicate x similarly (rows of zs2d_dedup_cols)
    x_idx = sorted(enumerate(xs), key=lambda p: p[1])
    x_order = [idx for idx, _ in x_idx]
    xs_sorted_by = [val for _, val in x_idx]
    zs2d_reordered = [zs2d_dedup_cols[i] for i in x_order]

    # deduplicate x: merge rows with equal x if their row values are identical across columns
    new_xs = []
    row_map = []  # maps new row index to original row indices merged
    i = 0
    while i < len(xs_sorted_by):
        j = i + 1
        merged_rows = [i]
        while j < len(xs_sorted_by) and xs_sorted_by[j] == xs_sorted_by[i]:
            merged_rows.append(j)
            j += 1
        if len(merged_rows) == 1:
            new_xs.append(xs_sorted_by[i])
            row_map.append([merged_rows[0]])
        else:
            # check that rows are identical across columns
            for c in range(ny):
                vals = [zs2d_reordered[r][c] for r in merged_rows]
                if any(v != vals[0] for v in vals):
                    raise ValueError('Duplicate x with conflicting z row values')
            new_xs.append(xs_sorted_by[i])
            row_map.append(merged_rows)
        i = j

    # construct final zs2d after x dedup
    zs2d_final = []
    for r_idxs in row_map:
        # take row values from first original in group
        zs2d_final.append(zs2d_reordered[r_idxs[0]])

    xs = new_xs
    nx = len(xs)

    # if after dedup x has length 1 -> fall back to 1D
    if nx == 1:
        logging.info('After deduplication x_array reduced to single value; x_input will be ignored and 1D interpolation over y is used')
        return linear_interpolate(ys, zs2d_final[0], y_input)

    # replace zs2d with final
    zs2d = zs2d_final

    # Degenerate case: single x value -> use 1D along y
    if nx == 1:
        logging.info('x_array has a single value; x_input will be ignored and 1D interpolation over y is used')
        # zs2d[0] corresponds to the single x row
        return linear_interpolate(ys, zs2d[0], y_input)

    # Otherwise perform bilinear interpolation on grid defined by xs, ys
    # find x indices
    if x_input < xs[0]:
        ix0, ix1 = 0, 1
    elif x_input > xs[-1]:
        ix0, ix1 = nx - 2, nx - 1
    else:
        ix1 = next(i for i, xv in enumerate(xs) if xv > x_input)
        ix0 = ix1 - 1

    # find y indices (reuse logic from 1D)
    if y_input < ys[0]:
        iy0, iy1 = 0, 1
    elif y_input > ys[-1]:
        iy0, iy1 = ny - 2, ny - 1
    else:
        iy1 = next(i for i, yv in enumerate(ys) if yv > y_input)
        iy0 = iy1 - 1

    # Quick-return: if x_input and y_input exactly match grid node, return stored value
    # (use integer equality on floats as the code currently does elsewhere)
    if xs[ix0] == x_input and ys[iy0] == y_input:
        return float(zs2d[ix0][iy0])
    if xs[ix1] == x_input and ys[iy0] == y_input:
        return float(zs2d[ix1][iy0])
    if xs[ix0] == x_input and ys[iy1] == y_input:
        return float(zs2d[ix0][iy1])
    if xs[ix1] == x_input and ys[iy1] == y_input:
        return float(zs2d[ix1][iy1])

    x0, x1 = xs[ix0], xs[ix1]
    y0, y1 = ys[iy0], ys[iy1]

    z00 = float(zs2d[ix0][iy0])
    z01 = float(zs2d[ix0][iy1])
    z10 = float(zs2d[ix1][iy0])
    z11 = float(zs2d[ix1][iy1])

    # interpolate in x then y (bilinear)
    if x1 == x0:
        # fallback to interpolation along y at ix0
        z0 = linear_interpolate(ys, zs2d[ix0], y_input)
        z1 = linear_interpolate(ys, zs2d[ix1], y_input)
        return float(0.5 * (z0 + z1))

    tx = (x_input - x0) / (x1 - x0)

    # interpolate z along y at x0 and x1
    if y1 == y0:
        z_x0 = z00
        z_x1 = z10
    else:
        ty0 = (y_input - y0) / (y1 - y0)
        z_x0 = z00 + ty0 * (z01 - z00)
        z_x1 = z10 + ty0 * (z11 - z10)

    return float(z_x0 + tx * (z_x1 - z_x0))


def _parse_array_input(s, default):
    if s is None or s.strip() == "":
        return default
    try:
        # allow comma or whitespace separated values
        # normalize commas to spaces, then split on any whitespace
        normalized = s.replace(',', ' ')
        return [float(x) for x in normalized.split()]
    except Exception:
        raise ValueError('Invalid numeric list format; use comma- or space-separated numbers')


def _parse_matrix_input(s, default_rows, expect_rows=None, expect_cols=None):
    """Parse z_array input; supports:
    - semicolon-separated rows, where each row is comma- or space-separated numbers
    - flat list that will be validated by the caller

    Returns a list of rows (list of lists of float) if semicolon syntax used,
    otherwise returns None to indicate caller should handle flat list parsing.
    """
    if s is None or s.strip() == "":
        return None
    try:
        # detect semicolon row separator
        if ';' in s:
            rows = [r.strip() for r in s.split(';') if r.strip() != '']
            parsed = []
            for r in rows:
                # reuse array parser for each row
                parsed_row = _parse_array_input(r, None)
                if parsed_row is None:
                    raise ValueError('Empty row in matrix input')
                parsed.append(parsed_row)
            # optional shape checks
            if expect_rows is not None and len(parsed) != expect_rows:
                raise ValueError(f'Expected {expect_rows} rows but got {len(parsed)}')
            if expect_cols is not None and any(len(row) != expect_cols for row in parsed):
                raise ValueError('All rows must have the same number of columns as y_array length')
            return parsed
        else:
            return None
    except ValueError:
        raise
    except Exception:
        raise ValueError('Invalid matrix format; rows separated by semicolons, values comma- or space-separated')


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # sensible defaults for quick testing; user can just press enter to use these
    default_x = [1.0, 3.6]
    default_y = [0.0, 4.0, 11.11, 22.22, 33.33, 44.44]
    default_z = [5.5, 11.0, 19.5, 25.5, 35.0, 70.0, 6.0, 18.0, 53.0, 82.0, 126.0, 140.0] # 2 x_values * 6 y_values.
    default_x_input = 2.0
    default_y_input = 20.0

    try:
        sx = input(f"Enter x_array as comma- or space-separated numbers [default: {default_x}]: ")
        x_array = _parse_array_input(sx, default_x)

        sy = input(f"Enter y_array as comma- or space-separated numbers [default: {default_y}]: ")
        y_array = _parse_array_input(sy, default_y)

        sz = input(f"Enter z_array as flat list or semicolon-separated rows (rows use comma- or space-separated numbers) [default: {default_z}]: ")
        # support semicolon-separated rows for manual matrix input
        parsed_matrix = _parse_matrix_input(sz, None, expect_cols=len(y_array))
        if parsed_matrix is not None:
            # keep nested rows as-is for 2D call
            z_array = parsed_matrix
        else:
            z_array = _parse_array_input(sz, default_z)

        sxin = input(f"Enter x_input (number) [default: {default_x_input}]: ")
        if sxin is None or sxin.strip() == "":
            x_input = default_x_input
        else:
            x_input = float(sxin.strip())

        # Ask user for unit of y_input before reading the numeric value.
        # Default (enter) is km/h, which we convert to m/s internally.
        su = input("Choose unit for y_input: 1. km/h  2. m/s  [default: 1]: ")
        if su is None or su.strip() == "":
            unit_is_kmh = True
        else:
            sval = su.strip().lower()
            if sval.startswith('2') or 'm/s' in sval:
                unit_is_kmh = False
            else:
                unit_is_kmh = True

        syin = input(f"Enter y_input (number) [default: {default_y_input}]: ")
        if syin is None or syin.strip() == "":
            y_input = default_y_input
        else:
            y_input = float(syin.strip())
        # convert if user provided value in km/h (default choice)
        if unit_is_kmh:
            y_input = y_input / 3.6

        # Call 2D interpolator. If user provided semicolon-separated rows for z_array,
        # `z_array` is already a list-of-rows; otherwise it's a flat list which is accepted too.
        result = linear_interpolate_2d(x_array, y_array, z_array, x_input, y_input)
        # final output: format result to two decimal places
        print(f"linear_interpolate_2d result = {result:.2f}")
    except Exception as e:
        print(f"Error: {e}")
