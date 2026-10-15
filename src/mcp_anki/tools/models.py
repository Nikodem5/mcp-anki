from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..anki import anki_request, logged_tool
from ..server import mcp


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_list_models() -> dict[str, Any]:
    """List the names of all note types (models) in the collection, e.g. Basic, Cloze.

    Use these exact names as the `model` argument of the note-writing tools.
    """
    names = anki_request("modelNames")
    return {"count": len(names), "models": names}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_get_model_fields(
    model: Annotated[
        str, Field(description="Exact note type name, as returned by anki_list_models.")
    ],
) -> dict[str, Any]:
    """Return a note type's field names in order, with each field's description.

    Call this before writing to a note type you haven't used yet: the keys of the `fields`
    argument on anki_add_card / anki_update_card / anki_add_cards must be among these names.
    """
    names = anki_request("modelFieldNames", modelName=model)
    # modelFieldDescriptions returns a list parallel to modelFieldNames; an empty string
    # means the field has no description.
    descriptions = anki_request("modelFieldDescriptions", modelName=model)
    return {
        "model": model,
        "fields": [
            {"name": name, "description": descriptions[i] if i < len(descriptions) else ""}
            for i, name in enumerate(names)
        ],
    }
