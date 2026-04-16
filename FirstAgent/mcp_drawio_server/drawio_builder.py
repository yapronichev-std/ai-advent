"""
Build draw.io (mxfile) XML for UML diagrams.

All output is valid mxGraphModel XML that can be opened directly in draw.io /
diagrams.net or embedded in other tools.
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _new_graph() -> tuple[ET.Element, ET.Element]:
    """Create a fresh mxGraphModel and return (model_element, root_element)."""
    model = ET.Element("mxGraphModel", {
        "dx": "1422", "dy": "762",
        "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1",
        "connect": "1", "arrows": "1",
        "fold": "1", "page": "1",
        "pageScale": "1", "pageWidth": "1169",
        "pageHeight": "827", "math": "0", "shadow": "0",
    })
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return model, root


def _wrap_mxfile(diagram_name: str, model: ET.Element) -> ET.Element:
    mxfile = ET.Element("mxfile", {
        "host": "app.diagrams.net",
        "modified": _now_iso(),
        "agent": "MCP DrawIO Server",
        "version": "21.0.0",
        "type": "device",
    })
    diag = ET.SubElement(mxfile, "diagram", {"name": diagram_name, "id": _uid()})
    diag.append(model)
    return mxfile


def _to_xml(element: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(element, encoding="unicode")


def _add_edge(root: ET.Element, source_id: str, target_id: str, style: str, label: str = "") -> None:
    edge = ET.SubElement(root, "mxCell", {
        "id": _uid(),
        "value": label,
        "style": style,
        "edge": "1",
        "source": source_id,
        "target": target_id,
        "parent": "1",
    })
    ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})


# ── Class Diagram ─────────────────────────────────────────────────────────────

_CLASS_EDGE_STYLES: dict[str, str] = {
    "inheritance":   "endArrow=block;endFill=0;jettySize=auto;orthogonalLoop=1;",
    "realization":   "endArrow=block;endFill=0;dashed=1;jettySize=auto;orthogonalLoop=1;",
    "association":   "endArrow=open;endSize=12;jettySize=auto;orthogonalLoop=1;",
    "dependency":    "endArrow=open;endSize=12;dashed=1;jettySize=auto;orthogonalLoop=1;",
    "aggregation":   "endArrow=open;endSize=12;startArrow=ERmandOne;startFill=0;jettySize=auto;orthogonalLoop=1;",
    "composition":   "endArrow=block;endFill=1;startArrow=ERmandOne;startFill=0;jettySize=auto;orthogonalLoop=1;",
}


def build_class_diagram_xml(classes: list[dict], relations: list[dict]) -> str:
    """
    Generate draw.io XML for a UML class diagram.

    Each class is rendered as a swimlane with an attributes section and a
    methods section.  Edges are drawn for each declared relation.

    Args:
        classes: Dicts with keys: name, attributes (list), methods (list), x, y.
        relations: Dicts with keys: from, to, type.

    Returns:
        XML string (mxfile).

    Raises:
        ValueError: If a relation references an unknown class name.
    """
    model, root = _new_graph()
    id_map: dict[str, str] = {}  # class_name → mxCell id

    for cls in classes:
        name: str = cls["name"]
        attrs: list[str] = cls.get("attributes") or []
        methods: list[str] = cls.get("methods") or []
        x = float(cls.get("x") or 100)
        y = float(cls.get("y") or 100)

        header_h = 30
        attr_h = max(24, len(attrs) * 20 + 8) if attrs else 24
        method_h = max(24, len(methods) * 20 + 8) if methods else 24
        total_h = header_h + attr_h + method_h
        width = 160

        cid = _uid()
        id_map[name] = cid

        # Class swimlane container
        container = ET.SubElement(root, "mxCell", {
            "id": cid,
            "value": name,
            "style": (
                "swimlane;fontStyle=1;align=center;startSize=30;"
                "container=1;collapsible=0;"
                "fillColor=#dae8fc;strokeColor=#6c8ebf;"
            ),
            "vertex": "1",
            "parent": "1",
        })
        ET.SubElement(container, "mxGeometry", {
            "x": str(x), "y": str(y),
            "width": str(width), "height": str(total_h),
            "as": "geometry",
        })

        # Attributes section
        attr_text = "\n".join(f"- {a}" for a in attrs) if attrs else " "
        attr_cell = ET.SubElement(root, "mxCell", {
            "id": _uid(),
            "value": attr_text,
            "style": (
                "text;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=top;spacingLeft=4;overflow=hidden;rotatable=0;"
            ),
            "vertex": "1",
            "parent": cid,
        })
        ET.SubElement(attr_cell, "mxGeometry", {
            "y": str(header_h),
            "width": str(width), "height": str(attr_h),
            "as": "geometry",
        })

        # Separator line
        sep = ET.SubElement(root, "mxCell", {
            "id": _uid(),
            "value": "",
            "style": "line;strokeColor=#6c8ebf;fillColor=none;",
            "vertex": "1",
            "parent": cid,
        })
        ET.SubElement(sep, "mxGeometry", {
            "y": str(header_h + attr_h),
            "width": str(width), "height": "2",
            "as": "geometry",
        })

        # Methods section
        method_text = "\n".join(f"+ {m}" for m in methods) if methods else " "
        method_cell = ET.SubElement(root, "mxCell", {
            "id": _uid(),
            "value": method_text,
            "style": (
                "text;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=top;spacingLeft=4;overflow=hidden;rotatable=0;"
            ),
            "vertex": "1",
            "parent": cid,
        })
        ET.SubElement(method_cell, "mxGeometry", {
            "y": str(header_h + attr_h + 2),
            "width": str(width), "height": str(method_h),
            "as": "geometry",
        })

    # Relations
    for rel in relations:
        from_name = rel.get("from", "")
        to_name = rel.get("to", "")
        rel_type = (rel.get("type") or "association").lower()

        if from_name not in id_map:
            raise ValueError(f"Class '{from_name}' not found in classes list")
        if to_name not in id_map:
            raise ValueError(f"Class '{to_name}' not found in classes list")

        style = _CLASS_EDGE_STYLES.get(rel_type, _CLASS_EDGE_STYLES["association"])
        _add_edge(root, id_map[from_name], id_map[to_name], style)

    return _to_xml(_wrap_mxfile("Class Diagram", model))


# ── Component Diagram ─────────────────────────────────────────────────────────

_COMPONENT_EDGE_STYLES: dict[str, str] = {
    "dependency":   "endArrow=open;endSize=12;dashed=1;jettySize=auto;",
    "association":  "endArrow=open;endSize=12;jettySize=auto;",
    "usage":        "endArrow=open;endSize=12;dashed=1;jettySize=auto;",
    "realization":  "endArrow=block;endFill=0;dashed=1;jettySize=auto;",
}


def build_component_diagram_xml(components: list[dict], relations: list[dict]) -> str:
    """
    Generate draw.io XML for a UML component diagram.

    Args:
        components: Dicts with keys: name, x, y.
        relations: Dicts with keys: from, to, type, label (optional).

    Returns:
        XML string (mxfile).

    Raises:
        ValueError: If a relation references an unknown component name.
    """
    model, root = _new_graph()
    id_map: dict[str, str] = {}

    for comp in components:
        name: str = comp["name"]
        x = float(comp.get("x") or 100)
        y = float(comp.get("y") or 100)
        cid = _uid()
        id_map[name] = cid

        cell = ET.SubElement(root, "mxCell", {
            "id": cid,
            "value": name,
            "style": (
                "shape=component;align=left;spacingLeft=36;"
                "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
            ),
            "vertex": "1",
            "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y),
            "width": "160", "height": "60",
            "as": "geometry",
        })

    for rel in relations:
        from_name = rel.get("from", "")
        to_name = rel.get("to", "")
        rel_type = (rel.get("type") or "dependency").lower()
        label = rel.get("label") or ""

        if from_name not in id_map:
            raise ValueError(f"Component '{from_name}' not found in components list")
        if to_name not in id_map:
            raise ValueError(f"Component '{to_name}' not found in components list")

        style = _COMPONENT_EDGE_STYLES.get(rel_type, _COMPONENT_EDGE_STYLES["dependency"])
        _add_edge(root, id_map[from_name], id_map[to_name], style, label)

    return _to_xml(_wrap_mxfile("Component Diagram", model))


# ── Use Case Diagram ──────────────────────────────────────────────────────────

_USECASE_EDGE_STYLES: dict[str, str] = {
    "association":    "endArrow=open;endSize=12;jettySize=auto;",
    "include":        "endArrow=open;endSize=12;dashed=1;endLabel=\u00abinclude\u00bb;jettySize=auto;",
    "extend":         "endArrow=open;endSize=12;dashed=1;endLabel=\u00abextend\u00bb;jettySize=auto;",
    "generalization": "endArrow=block;endFill=0;jettySize=auto;",
}


def build_use_case_diagram_xml(
    actors: list[dict],
    use_cases: list[dict],
    relations: list[dict],
) -> str:
    """
    Generate draw.io XML for a UML use case diagram.

    Args:
        actors: Dicts with keys: name, x, y.
        use_cases: Dicts with keys: name, x, y.
        relations: Dicts with keys: from, to, type.

    Returns:
        XML string (mxfile).

    Raises:
        ValueError: If a relation references an unknown element name.
    """
    model, root = _new_graph()
    id_map: dict[str, str] = {}

    # Actors
    for actor in actors:
        name: str = actor["name"]
        x = float(actor.get("x") or 100)
        y = float(actor.get("y") or 100)
        aid = _uid()
        id_map[name] = aid

        cell = ET.SubElement(root, "mxCell", {
            "id": aid,
            "value": name,
            "style": (
                "shape=mxgraph.uml.actor;whiteSpace=wrap;html=1;"
                "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
            ),
            "vertex": "1",
            "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y),
            "width": "40", "height": "70",
            "as": "geometry",
        })

    # Use cases
    for uc in use_cases:
        name = uc["name"]
        x = float(uc.get("x") or 100)
        y = float(uc.get("y") or 100)
        uid_ = _uid()
        id_map[name] = uid_

        cell = ET.SubElement(root, "mxCell", {
            "id": uid_,
            "value": name,
            "style": (
                "ellipse;whiteSpace=wrap;html=1;"
                "fillColor=#dae8fc;strokeColor=#6c8ebf;"
            ),
            "vertex": "1",
            "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y),
            "width": "150", "height": "60",
            "as": "geometry",
        })

    # Relations
    for rel in relations:
        from_name = rel.get("from", "")
        to_name = rel.get("to", "")
        rel_type = (rel.get("type") or "association").lower()

        if from_name not in id_map:
            raise ValueError(f"Element '{from_name}' not found in actors or use cases")
        if to_name not in id_map:
            raise ValueError(f"Element '{to_name}' not found in actors or use cases")

        style = _USECASE_EDGE_STYLES.get(rel_type, _USECASE_EDGE_STYLES["association"])
        _add_edge(root, id_map[from_name], id_map[to_name], style)

    return _to_xml(_wrap_mxfile("Use Case Diagram", model))