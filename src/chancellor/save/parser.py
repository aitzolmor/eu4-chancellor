"""Parse Clausewitz-format text (the syntax used by Paradox save and data files).

Grammar handled:

* ``key=value`` and ``key={ ... }`` pairs; also ``key{ ... }`` without ``=``, which EU4
  writes for ``map_area_data``.
* Comparison operators (``<``, ``>``, ``<=``, ``>=``, ``!=``, ``?=``) are accepted in place
  of ``=`` and treated as assignment; the operator itself is not kept.
* Bare-value lists such as ``{ 1 2 3 }`` and lists of blocks such as ``{ {a=1} {a=2} }``.
* Repeated keys: every occurrence is kept, collected into a :class:`Repeated` list.
* Quoted strings (with backslash-escaped quotes) and ``#`` comments.

Indentation is ignored: EU4 does not indent saves consistently, so only braces count.

Scalar conversion: unquoted integers become ``int``, unquoted decimals with a single dot
become ``float``, ``yes``/``no`` become ``bool``. Everything else, including dates such as
``1444.11.11`` and all quoted values, stays ``str``.
"""

from __future__ import annotations

import re
from typing import Any

ClausewitzValue = str | int | float | bool | list[Any] | dict[str, Any]


class Repeated(list):  # type: ignore[type-arg]
    """Values of a key that appeared more than once in the same block.

    A distinct type so that a repeated key can be told apart from a key whose single
    value is a list.
    """


# One token per match. Groups: 1 quoted string body, 2 brace or operator, 3 bare word,
# 4 comment. An empty quoted string matches with every group empty.
_TOKEN = re.compile(
    r'"((?:[^"\\]|\\.)*)"'
    r"|([{}]|[<>!?]=?|=)"
    r'|([^\s{}=<>!?#"]+)'
    r"|(#[^\n]*)"
)
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d*\.\d+")


def parse(text: str) -> dict[str, Any]:
    """Parse a Clausewitz document into nested Python structures.

    Blocks containing only bare values become lists; blocks containing ``key=value``
    pairs become dicts. In a mixed block, bare values are stored under the ``""`` key.
    An empty block ``{}`` becomes an empty dict. Unbalanced closing braces are ignored
    and unclosed blocks are closed at the end of input, mirroring the game's leniency.

    Args:
        text: Document text, without the ``EU4txt`` magic header.

    Returns:
        A mapping of top-level keys to parsed values.
    """
    tokens = _TOKEN.findall(text)
    count = len(tokens)

    # Each frame: (key in parent or None for a bare block, list of (key | None, value)).
    stack: list[tuple[str | None, list[tuple[str | None, Any]]]] = []
    items: list[tuple[str | None, Any]] = []
    i = 0
    while i < count:
        quoted, punct, bare, comment = tokens[i]
        i += 1
        if comment:
            continue

        if punct == "{":
            stack.append((None, items))
            items = []
            continue
        if punct == "}":
            if not stack:
                continue  # stray closing brace
            key, parent = stack.pop()
            parent.append((key, _finish(items)))
            items = parent
            continue
        if punct:
            continue  # operator without a key: malformed, skip

        # A scalar token: either a key (followed by an operator or a brace) or a value.
        word = bare if bare else _unescape(quoted)
        next_punct = _next_punct(tokens, i, count)
        if next_punct and next_punct != "}":
            if next_punct == "{":
                if not bare:
                    items.append((None, word))
                    continue
                i = _skip_comments(tokens, i, count) + 1  # key{ ... } form
            else:
                i = _skip_comments(tokens, i, count) + 1  # consume operator
                i = _skip_comments(tokens, i, count)
                if i >= count:
                    items.append((word, ""))
                    break
                v_quoted, v_punct, v_bare, _ = tokens[i]
                i += 1
                if v_punct != "{":
                    if v_punct:  # e.g. "key=}" — treat as empty value, re-read the brace
                        i -= 1
                        items.append((word, ""))
                        continue
                    value = _convert(v_bare) if v_bare else _unescape(v_quoted)
                    items.append((word, value))
                    continue
            stack.append((word, items))
            items = []
            continue

        items.append((None, _convert(bare) if bare else word))

    while stack:  # close unterminated blocks
        key, parent = stack.pop()
        parent.append((key, _finish(items)))
        items = parent

    result = _finish(items)
    return result if isinstance(result, dict) else {"": result}


class LazyBlock:
    """An unparsed ``{ ... }`` block, parsed only when asked.

    A full EU4 gamestate holds over ten million tokens, which takes many seconds to parse
    in Python. Lazy blocks let callers parse just the parts they need.

    Attributes:
        text: The source document (shared, not copied).
        start: Index just after the opening brace.
        end: Index of the matching closing brace.
        children: Spans of the block's own first-level blocks, when already known from
            the scan that found this block; saves rescanning it in :meth:`lazy`.
    """

    __slots__ = ("children", "end", "start", "text")

    def __init__(
        self,
        text: str,
        start: int,
        end: int,
        children: list[tuple[int, int]] | None = None,
    ) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.children = children

    @property
    def raw(self) -> str:
        """The block's inner text, without the surrounding braces."""
        return self.text[self.start : self.end]

    def parse(self) -> dict[str, Any] | list[Any]:
        """Fully parse the block."""
        result = parse(self.raw)
        if set(result) == {""} and isinstance(result[""], list):
            return result[""]
        return result

    def lazy(self) -> dict[str, Any] | list[Any]:
        """Parse one level of the block, leaving nested blocks as :class:`LazyBlock`."""
        result = _parse_lazy(self.text, self.start, self.end, self.children)
        if set(result) == {""} and isinstance(result[""], list):
            return result[""]
        return result

    def __repr__(self) -> str:
        return f"LazyBlock({self.end - self.start} chars)"


def parse_lazy(text: str) -> dict[str, Any]:
    """Parse only the top level of a document; nested blocks become :class:`LazyBlock`.

    Args:
        text: Document text, without the ``EU4txt`` magic header.

    Returns:
        A mapping of top-level keys to scalars or lazy blocks.
    """
    return _parse_lazy(text, 0, len(text))


def get_all(block: dict[str, Any], key: str) -> list[Any]:
    """Return every value of ``key`` in ``block`` as a list, whether repeated or not.

    Args:
        block: A parsed block.
        key: Key to look up.

    Returns:
        An empty list if the key is absent, the :class:`Repeated` values if it appeared
        several times, or a one-element list otherwise.
    """
    if key not in block:
        return []
    value = block[key]
    return list(value) if isinstance(value, Repeated) else [value]


_BRACE_OR_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|#[^\n]*|[{}]')
_LAZY_MARKER = "\x00lazy"


def _parse_lazy(
    text: str, start: int, end: int, known: list[tuple[int, int]] | None = None
) -> dict[str, Any]:
    """Parse ``text[start:end]`` one level deep.

    Each first-level ``{ ... }`` is replaced by ``{<marker>}`` in a small skeleton
    document, which is parsed normally; markers are then swapped for lazy blocks. The
    same scan also records each block's own first-level spans, so opening a block later
    (e.g. ``countries``, 70% of a save) does not scan its text again.
    """
    if known is not None:
        spans = [(s, e, None) for s, e in known]
    else:
        spans = _scan_two_levels(text, start, end)

    pieces: list[str] = []
    cursor = start
    for index, (block_start, block_end, _) in enumerate(spans):
        pieces.append(text[cursor:block_start])
        pieces.append(f"{_LAZY_MARKER}{index}}}")
        cursor = block_end + 1
    if cursor <= end:
        pieces.append(text[cursor:end])

    blocks = [LazyBlock(text, s, e, children) for s, e, children in spans]

    def resolve(value: Any) -> Any:
        if (
            isinstance(value, list)
            and len(value) == 1
            and isinstance(value[0], str)
            and value[0].startswith(_LAZY_MARKER)
        ):
            return blocks[int(value[0][len(_LAZY_MARKER) :])]
        if isinstance(value, Repeated):
            return Repeated(resolve(v) for v in value)
        return value

    skeleton = parse("".join(pieces))
    for key, value in skeleton.items():
        if key == "" and isinstance(value, list) and not isinstance(value, Repeated):
            skeleton[key] = [resolve(v) for v in value]
        else:
            skeleton[key] = resolve(value)
    return skeleton


def _finish(items: list[tuple[str | None, Any]]) -> dict[str, Any] | list[Any]:
    """Turn the collected items of a block into a dict or a list."""
    if not items:
        return {}
    if all(key is None for key, _ in items):
        return [value for _, value in items]

    block: dict[str, Any] = {}
    for key, value in items:
        if key is None:
            key = ""
        if key in block:
            existing = block[key]
            if isinstance(existing, Repeated):
                existing.append(value)
            else:
                block[key] = Repeated((existing, value))
        else:
            block[key] = value
    return block


def _next_punct(tokens: list[tuple[str, str, str, str]], i: int, count: int) -> str:
    """Return the punctuation of the next non-comment token, or ``""``."""
    i = _skip_comments(tokens, i, count)
    return tokens[i][1] if i < count else ""


def _skip_comments(tokens: list[tuple[str, str, str, str]], i: int, count: int) -> int:
    """Advance ``i`` past any comment tokens."""
    while i < count and tokens[i][3]:
        i += 1
    return i


def _convert(word: str) -> str | int | float | bool:
    """Convert an unquoted scalar to ``int``, ``float`` or ``bool`` where unambiguous."""
    if word == "yes":
        return True
    if word == "no":
        return False
    first = word[0]
    if first.isdigit() or first in "-.":
        if _INT.fullmatch(word):
            return int(word)
        if _FLOAT.fullmatch(word):
            return float(word)
    return word


def _unescape(quoted: str) -> str:
    """Resolve backslash escapes inside a quoted string."""
    if "\\" not in quoted:
        return quoted
    return re.sub(r"\\(.)", r"\1", quoted)


def _scan_two_levels(
    text: str, start: int, end: int
) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """Spans of the first-level blocks, each with the spans of its own first-level blocks.

    One pass over the tokens that matter (braces, strings, comments), so braces inside
    quoted strings or comments are never counted. Stray closing braces are ignored and
    unterminated blocks run to the end, mirroring :func:`parse`.
    """
    spans: list[tuple[int, int, list[tuple[int, int]]]] = []
    children: list[tuple[int, int]] = []
    depth = 0
    block_start = child_start = start
    for match in _BRACE_OR_STRING.finditer(text, start, end):
        char = match.group()
        if char == "{":
            depth += 1
            if depth == 1:
                block_start = match.end()
                children = []
            elif depth == 2:
                child_start = match.end()
        elif char == "}":
            if depth == 0:
                continue  # stray closing brace
            depth -= 1
            if depth == 0:
                spans.append((block_start, match.start(), children))
            elif depth == 1:
                children.append((child_start, match.start()))
    if depth >= 2:  # unterminated inner block
        children.append((child_start, end))
    if depth >= 1:  # unterminated block: let it run to the end
        spans.append((block_start, end, children))
    return spans
