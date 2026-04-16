"""Pydantic models for draw.io UML diagram inputs."""

from typing import Optional
from pydantic import BaseModel, Field
from pydantic import ConfigDict


# ── Class Diagram ─────────────────────────────────────────────────────────────

class ClassDef(BaseModel):
    """Definition of a UML class."""

    name: str
    attributes: list[str] = []
    methods: list[str] = []
    inherits: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


class Relation(BaseModel):
    """A relation between two classes."""

    model_config = ConfigDict(populate_by_name=True)

    from_class: str = Field(alias="from")
    to: str
    type: str  # inheritance | association | dependency | realization | aggregation | composition


class ClassDiagramInput(BaseModel):
    """Input schema for generate_class_diagram."""

    classes: list[ClassDef]
    relations: list[Relation] = []


# ── Component Diagram ─────────────────────────────────────────────────────────

class ComponentDef(BaseModel):
    """Definition of a UML component."""

    name: str
    x: Optional[float] = None
    y: Optional[float] = None


class ComponentRelation(BaseModel):
    """A relation between two components."""

    model_config = ConfigDict(populate_by_name=True)

    from_component: str = Field(alias="from")
    to: str
    type: str = "dependency"  # dependency | association | usage | realization
    label: Optional[str] = None


class ComponentDiagramInput(BaseModel):
    """Input schema for generate_component_diagram."""

    components: list[ComponentDef]
    relations: list[ComponentRelation] = []


# ── Use Case Diagram ──────────────────────────────────────────────────────────

class ActorDef(BaseModel):
    """Definition of a use-case actor."""

    name: str
    x: Optional[float] = None
    y: Optional[float] = None


class UseCaseDef(BaseModel):
    """Definition of a use case."""

    name: str
    x: Optional[float] = None
    y: Optional[float] = None


class UseCaseRelation(BaseModel):
    """A relation between actors and use cases."""

    model_config = ConfigDict(populate_by_name=True)

    from_element: str = Field(alias="from")
    to: str
    type: str = "association"  # association | include | extend | generalization


class UseCaseDiagramInput(BaseModel):
    """Input schema for generate_use_case_diagram."""

    actors: list[ActorDef]
    use_cases: list[UseCaseDef]
    relations: list[UseCaseRelation] = []