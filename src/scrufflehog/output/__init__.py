from .text import render_text
from .json_out import render_json
from .sarif import render_sarif

FORMATTERS = {"text": render_text, "json": render_json, "sarif": render_sarif}

__all__ = ["FORMATTERS", "render_text", "render_json", "render_sarif"]
