def parse_hitobjects(osu_path):
    objects = []

    with open(osu_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the [HitObjects] section
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[HitObjects]":
            start = i + 1
            break

    if start is None:
        raise ValueError("No [HitObjects] section found in .osu file")

    for line in lines[start:]:
        line = line.strip()

        # Stop if we hit the next section
        if line.startswith("[") and line.endswith("]"):
            break

        if not line:
            continue

        parts = line.split(",")

        x = int(parts[0])
        y = int(parts[1])
        time = int(parts[2])
        type_flag = int(parts[3])

        # Circle
        if type_flag & 1:
            objects.append({
                "type": "circle",
                "x": x,
                "y": y,
                "time": time
            })

        # Slider
        elif type_flag & 2:
            curve_data = parts[5].split("|")
            curve_type = curve_data[0]

            curve_points = []
            for cp in curve_data[1:]:
                px, py = cp.split(":")
                curve_points.append((int(px), int(py)))

            repeat = int(parts[6])
            pixel_length = float(parts[7])

            objects.append({
                "type": "slider",
                "x": x,
                "y": y,
                "time": time,
                "curve_type": curve_type,
                "curve_points": curve_points,
                "repeat": repeat,
                "pixel_length": pixel_length
            })

        # Spinner
        elif type_flag & 8:
            end_time = int(parts[5])
            objects.append({
                "type": "spinner",
                "time": time,
                "end_time": end_time
            })

    return objects
def parse_approach_rate(osu_path: str) -> float:
    ar = 5.0  # default if not found
    try:
        with open(osu_path, 'r', encoding='utf-8') as f:
            in_difficulty = False
            for line in f:
                line = line.strip()
                if line == '[Difficulty]':
                    in_difficulty = True
                    continue
                if in_difficulty:
                    if line.startswith('['):
                        break  # moved past [Difficulty] section
                    if line.startswith('ApproachRate:'):
                        ar = float(line.split(':')[1].strip())
                        break
    except Exception:
        import traceback
        traceback.print_exc()
    return ar


def ar_to_preempt_ms(ar: float) -> float:
    """Convert AR value to approach time in milliseconds."""
    if ar < 5:
        return 1200 + 600 * (5 - ar) / 5
    elif ar == 5:
        return 1200.0
    else:
        return 1200 - 750 * (ar - 5) / 5