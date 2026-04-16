"""Tool handler functions called by the MCP server."""

import base64
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from models import ClassDiagramInput, ComponentDiagramInput, UseCaseDiagramInput
from drawio_builder import (
    build_class_diagram_xml,
    build_component_diagram_xml,
    build_use_case_diagram_xml,
)
from layout import apply_grid_layout

logger = logging.getLogger(__name__)

# Output directory: DIAGRAMS_DIR env var, or <FirstAgent>/diagrams/ by default.
_OUTPUT_DIR = Path(
    os.environ.get("DIAGRAMS_DIR", Path(__file__).parent.parent / "diagrams")
)


def _date_suffix() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _encode(xml: str) -> str:
    return base64.b64encode(xml.encode()).decode()


def _save(xml: str, filename: str) -> str:
    """Write *xml* to _OUTPUT_DIR/<filename> and return the absolute path."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUTPUT_DIR / filename
    path.write_text(xml, encoding="utf-8")
    logger.info("Diagram saved → %s", path)
    return str(path)


def handle_generate_class_diagram(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a UML class diagram.

    Validates the input via Pydantic, applies auto-layout for elements without
    explicit coordinates, then delegates to drawio_builder.

    Args:
        arguments: Raw tool arguments dict (classes, relations).

    Returns:
        Dict with drawio_xml, filename, base64.
    """
    logger.info("generate_class_diagram invoked")
    inp = ClassDiagramInput.model_validate(arguments)

    classes = apply_grid_layout(
        [c.model_dump() for c in inp.classes],
        col_spacing=250,
        row_spacing=220,
        cols=3,
    )
    relations = [
        {"from": r.from_class, "to": r.to, "type": r.type}
        for r in inp.relations
    ]

    xml = build_class_diagram_xml(classes, relations)
    filename = f"class_diagram_{_date_suffix()}.drawio"
    saved_path = _save(xml, filename)
    return {"drawio_xml": xml, "filename": filename, "saved_path": saved_path, "base64": _encode(xml)}


def handle_generate_component_diagram(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a UML component diagram.

    Args:
        arguments: Raw tool arguments dict (components, relations).

    Returns:
        Dict with drawio_xml, filename, base64.
    """
    logger.info("generate_component_diagram invoked")
    inp = ComponentDiagramInput.model_validate(arguments)

    components = apply_grid_layout(
        [c.model_dump() for c in inp.components],
        col_spacing=220,
        row_spacing=150,
        cols=3,
    )
    relations = [
        {"from": r.from_component, "to": r.to, "type": r.type, "label": r.label}
        for r in inp.relations
    ]

    xml = build_component_diagram_xml(components, relations)
    filename = f"component_diagram_{_date_suffix()}.drawio"
    saved_path = _save(xml, filename)
    return {"drawio_xml": xml, "filename": filename, "saved_path": saved_path, "base64": _encode(xml)}


def handle_generate_use_case_diagram(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a UML use case diagram.

    Actors are laid out in a single left-hand column; use cases occupy the
    right area in a two-column grid.

    Args:
        arguments: Raw tool arguments dict (actors, use_cases, relations).

    Returns:
        Dict with drawio_xml, filename, base64.
    """
    logger.info("generate_use_case_diagram invoked")
    inp = UseCaseDiagramInput.model_validate(arguments)

    actors = apply_grid_layout(
        [a.model_dump() for a in inp.actors],
        start_x=50, start_y=120,
        col_spacing=100, row_spacing=130,
        cols=1,
    )
    use_cases = apply_grid_layout(
        [u.model_dump() for u in inp.use_cases],
        start_x=250, start_y=100,
        col_spacing=200, row_spacing=110,
        cols=2,
    )
    relations = [
        {"from": r.from_element, "to": r.to, "type": r.type}
        for r in inp.relations
    ]

    xml = build_use_case_diagram_xml(actors, use_cases, relations)
    filename = f"use_case_diagram_{_date_suffix()}.drawio"
    saved_path = _save(xml, filename)
    return {"drawio_xml": xml, "filename": filename, "saved_path": saved_path, "base64": _encode(xml)}