# CSC Max Vx Calculator
import logging


def linear_interpolate(x_array, y_array, x_input):
    """Perform 1D linear interpolation with sorted pairing.

    - x_array, y_array: iterables of same length >= 2
    - x_input: float-like

    The function sorts x_array ascending and reorders y_array accordingly,
    then finds the interval that contains x_input and returns the linear
    interpolation. If x_input is outside the x_array range, the function
    linearly extrapolates using the nearest two points.

    Raises ValueError for invalid inputs.
    """
    # Convert to lists
    xs = list(x_array)
    ys = list(y_array)

    if len(xs) != len(ys):
        raise ValueError("x_array and y_array must have the same length")
    if len(xs) < 2:
        raise ValueError("Need at least two points for interpolation")

    # Pair and sort by x
    pairs = sorted(zip(xs, ys), key=lambda p: p[0])

    # Merge duplicate x: if duplicate x have equal y -> drop duplicate and log info;
    # if duplicate x have different y -> error
    xs_sorted = []
    ys_sorted = []
    last_x = None
    last_y = None
    for xi, yi in pairs:
        if last_x is None or xi != last_x:
            xs_sorted.append(xi)
            ys_sorted.append(yi)
            last_x = xi
            last_y = yi
        else:
            # duplicate x encountered
            if yi == last_y:
                logging.info("Duplicate x=%s with identical y=%s removed during interpolation prep", xi, yi)
                # skip duplicate
                continue
            else:
                raise ValueError(f"Duplicate x value {xi} has conflicting y values: {last_y} vs {yi}")

    # fast path: exact match
    for xi, yi in zip(xs_sorted, ys_sorted):
        if x_input == xi:
            return yi

    # find interval
    if x_input < xs_sorted[0]:
        i0, i1 = 0, 1
    elif x_input > xs_sorted[-1]:
        i0, i1 = len(xs_sorted) - 2, len(xs_sorted) - 1
    else:
        # x_input in [xs_sorted[0], xs_sorted[-1]]
        # find right index such that xs_sorted[i0] < x_input < xs_sorted[i1]
        i1 = next(i for i, xv in enumerate(xs_sorted) if xv > x_input)
        i0 = i1 - 1

    x0, y0 = xs_sorted[i0], ys_sorted[i0]
    x1, y1 = xs_sorted[i1], ys_sorted[i1]

    # Avoid division by zero for duplicate x (after sorting)
    if x1 == x0:
        return float(y0)

    t = (x_input - x0) / (x1 - x0)
    return float(y0 + t * (y1 - y0))


def solve_vx_ay(R=100.0,
                 x_array=(6.0, 12.0, 30.0, 55.0),
                 y_array=(3.5, 3.0, 2.5, 2.1),
                 tol=1e-4,
                 max_iter=100):
    """Solve the system:
       vx = sqrt(ay * R)
       ay = linear_interpolate(x_array, y_array, vx)

    Returns (vx, ay) with residual |vx^2 / R - interp(vx)| < tol.
    Uses bisection on f(vx) = vx^2 / R - interp(vx).
    """
    if float(R) < 10.0:
        logging.warning("the input R value is too small, automatically adjusted to 10.0 m")
        R = 10.0

    # ensure arrays are lists
    xs = list(x_array)
    ys = list(y_array)

    # search interval for vx (m/s). Start from 0 to a reasonable upper bound.
    left = 0.0
    right = max(max(xs) * 2.0, 50.0)

    def f(vx):
        ay_interp = linear_interpolate(xs, ys, vx)
        return vx * vx / float(R) - ay_interp

    f_left = f(left)
    f_right = f(right)

    # If signs are same, try to expand right until sign change or limit
    expand_count = 0
    while f_left * f_right > 0 and expand_count < 20:
        right *= 2.0
        f_right = f(right)
        expand_count += 1

    if f_left * f_right > 0:
        # fallback to Newton-like iteration starting from mid
        vx = (left + right) / 2.0
        for _ in range(max_iter):
            ay = linear_interpolate(xs, ys, vx)
            # f = vx^2/R - ay; derivative df/dvx = 2*vx/R - ay'(vx)
            # approximate ay' by finite difference
            h = 1e-6
            ay_plus = linear_interpolate(xs, ys, vx + h)
            day_dvx = (ay_plus - ay) / h
            df = vx * vx / float(R) - ay
            ddf = 2.0 * vx / float(R) - day_dvx
            if abs(df) < tol:
                return float(vx), float(ay)

        ay = linear_interpolate(xs, ys, vx)
        return float(vx), float(ay)

    # bisection
    for _ in range(max_iter):
        mid = 0.5 * (left + right)
        f_mid = f(mid)
        if abs(f_mid) < tol:
            ay = linear_interpolate(xs, ys, mid)
            return float(mid), float(ay)
        if f_left * f_mid <= 0:
            right = mid
            f_right = f_mid
        else:
            left = mid
            f_left = f_mid

    # final estimate
    vx = 0.5 * (left + right)
    ay = linear_interpolate(xs, ys, vx)
    return float(vx), float(ay)


def interactive_solve():
    """Interactively ask user for x_array, y_array and R, then solve.

    - x_array and y_array: enter as Python list/tuple literal or comma-separated numbers.
    - R: enter a single number or a Python list/tuple of numbers.
    """
    import ast

    def parse_array(s):
        try:
            val = ast.literal_eval(s)
            if isinstance(val, (list, tuple)):
                return list(map(float, val))
        except Exception:
            pass
        # fallback: comma separated
        parts = [p.strip() for p in s.split(',') if p.strip() != '']
        return [float(p) for p in parts]

    default_x_display = '6, 12, 30, 55'
    while True:
        raw_x = input(f'Enter CSC x_array parameters (vehicle speed, m/s), default {default_x_display}: ').strip()
        if raw_x == '':
            raw_x = default_x_display
        try:
            x_array = parse_array(raw_x)
        except Exception as e:
            print('Could not parse x_array:', e)
            continue
        if len(x_array) < 2:
            print('x_array must contain at least two elements.')
            continue
        break

    default_y_display = '3.5, 3.0, 2.5, 2.1'
    while True:
        raw_y = input(f'Enter CSC y_array parameters (lateral acceleration, m/s^2), default {default_y_display}: ').strip()
        if raw_y == '':
            raw_y = default_y_display
        try:
            y_array = parse_array(raw_y)
        except Exception as e:
            print('Could not parse y_array:', e)
            continue
        if len(y_array) < 2:
            print('y_array must contain at least two elements.')
            continue
        if len(y_array) != len(x_array):
            print('y_array must have the same length as x_array.')
            continue
        break

    raw_R = input('Enter R (curve radius, m) (single number or list of numbers, default 100): ').strip()
    if raw_R == '':
        R_val = 100.0
    else:
        try:
            parsed = ast.literal_eval(raw_R)
            if isinstance(parsed, (list, tuple)):
                R_val = [float(v) for v in parsed]
            else:
                R_val = float(parsed)
        except Exception:
            # try comma separated
            parts = [p.strip() for p in raw_R.split(',') if p.strip() != '']
            if len(parts) == 1:
                R_val = float(parts[0])
            else:
                R_val = [float(p) for p in parts]

    results = []
    if not isinstance(R_val, (list, tuple)):
        R_val = [R_val]

    adjusted_R_val = []
    for R_item in R_val:
        if float(R_item) < 10.0:
            logging.warning('the input R value is too small, automatically adjusted to 10.0 m')
            adjusted_R_val.append(10.0)
        else:
            adjusted_R_val.append(float(R_item))
    R_val = adjusted_R_val

    # remove duplicates in R_val while preserving order
    seen = set()
    R_val_unique = []
    for R_item in R_val:
        if R_item not in seen:
            seen.add(R_item)
            R_val_unique.append(R_item)
    R_val = R_val_unique

    for R_item in R_val:
        vx, ay = solve_vx_ay(R=float(R_item), x_array=x_array, y_array=y_array)
        vx_kph = vx * 3.6
        print(f'R = {R_item} m -> vx_max = {vx_kph:.2f} km/h, ay_max = {ay:.2f} m/s^2')
        results.append((R_item, vx, ay))

    return results


if __name__ == "__main__":
    interactive_solve()
