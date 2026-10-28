from __future__ import annotations
import ast
import hashlib
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from .paths import safe_source


class Anchor(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    path: str
    literal: str | None = Field(default=None, max_length=12000)
    occurrence: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    listing: str | None = None
    key_lines: list[int] = Field(default_factory=list)
    look_for: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def selector(self):
        if sum([self.literal is not None, self.symbol is not None, self.start_line is not None]) != 1:
            raise ValueError("Anchor needs exactly one of literal, symbol or start_line")
        return self


def resolve_anchor(root: Path, value: Anchor | dict) -> dict:
    anchor = value if isinstance(value, Anchor) else Anchor.model_validate(value)
    path = safe_source(root, anchor.path)
    text = path.read_text()
    lines = text.splitlines()
    if anchor.literal is not None:
        if not anchor.literal:
            raise ValueError("An empty literal is not an anchor")
        offsets, cursor = [], 0
        while (at := text.find(anchor.literal, cursor)) >= 0:
            offsets.append(at)
            cursor = at + 1
        if not offsets:
            raise ValueError(f"Anchor {anchor.id}: literal does not occur in {anchor.path}")
        if anchor.occurrence is None and len(offsets) != 1:
            raise ValueError(f"Anchor {anchor.id}: literal occurs {len(offsets)} times; specify occurrence")
        index = (anchor.occurrence or 1) - 1
        if index >= len(offsets):
            raise ValueError(f"Anchor {anchor.id}: occurrence does not exist")
        at = offsets[index]
        start = text.count("\n", 0, at) + 1
        end = start + anchor.literal.count("\n")
    elif anchor.symbol:
        matches = []
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                raise ValueError("Cannot resolve a symbol in invalid Python; use a literal or lines") from exc

            def walk(nodes, prefix=""):
                for node in nodes:
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = prefix + node.name
                        if name == anchor.symbol:
                            matches.append((node.lineno, node.end_lineno or node.lineno))
                        walk(node.body, name + ".")

            walk(tree.body)
        else:
            import re

            leaf = anchor.symbol.split(".")[-1]
            matches = [
                (i + 1, i + 1)
                for i, line in enumerate(lines)
                if re.search(r"\b(?:class|function|def|fn|func|interface)\s+" + re.escape(leaf) + r"\b", line)
            ]
        if len(matches) != 1:
            raise ValueError(f"Anchor {anchor.id}: symbol is missing or ambiguous; use a literal")
        start, end = matches[0]
    else:
        start, end = anchor.start_line, anchor.end_line or anchor.start_line
    if start is None or end is None or start > end or end > len(lines):
        raise ValueError(f"Anchor {anchor.id}: invalid line range")
    if end - start > 200:
        raise ValueError("Anchor spans more than 200 lines; choose a smaller range")
    if anchor.listing is not None:
        expected = anchor.listing.splitlines()
        actual = lines[start - 1 : end]
        if expected != actual:
            raise ValueError(f"Anchor {anchor.id}: code listing does not match source line by line")
    if any(n < start or n > end for n in anchor.key_lines):
        raise ValueError("Key lines must lie inside the highlighted range")
    excerpt_start, excerpt_end = max(1, start - 5), min(len(lines), end + 5)
    excerpt = "\n".join(lines[excerpt_start - 1 : excerpt_end])
    if any(not word or word not in excerpt for word in anchor.look_for):
        raise ValueError("Look-for identifiers must occur in the code excerpt")
    return {
        **anchor.model_dump(),
        "start_line": start,
        "end_line": end,
        "fingerprint": hashlib.sha256("\n".join(lines[start - 1 : end]).encode()).hexdigest(),
        "lines": [
            {"number": n, "text": lines[n - 1], "highlight": start <= n <= end, "key": n in anchor.key_lines}
            for n in range(excerpt_start, excerpt_end + 1)
        ],
    }
