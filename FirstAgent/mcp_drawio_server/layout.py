"""Simple auto-layout for diagram elements that lack explicit coordinates."""


def apply_grid_layout(
    elements: list[dict],
    start_x: float = 100,
    start_y: float = 100,
    col_spacing: float = 200,
    row_spacing: float = 150,
    cols: int = 3,
) -> list[dict]:
    """
    Assign x, y coordinates in a grid layout to elements that have no coordinates.

    Elements that already have both x and y are left unchanged.

    Args:
        elements: List of element dicts with optional 'x' and 'y' keys.
        start_x: X coordinate of the first grid cell.
        start_y: Y coordinate of the first grid cell.
        col_spacing: Horizontal distance between element origins.
        row_spacing: Vertical distance between element origins.
        cols: Number of columns before wrapping to the next row.

    Returns:
        New list of element dicts with x and y guaranteed to be present.
    """
    col = 0
    row = 0
    result: list[dict] = []

    for elem in elements:
        elem = dict(elem)
        if elem.get("x") is None or elem.get("y") is None:
            elem["x"] = start_x + col * col_spacing
            elem["y"] = start_y + row * row_spacing
            col += 1
            if col >= cols:
                col = 0
                row += 1
        result.append(elem)

    return result