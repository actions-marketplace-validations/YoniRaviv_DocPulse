import hashlib

from tree_sitter_language_pack import get_parser

from docpulse.indexing.chunk_rules import rules_for_path
from docpulse.models import CodeChunk


def chunk_source(path: str, source: str) -> list[CodeChunk]:
    resolved = rules_for_path(path)
    if resolved is None:
        return []
    rules, grammar = resolved
    src_bytes = source.encode()
    tree = get_parser(grammar).parse_bytes(src_bytes)
    chunks: list[CodeChunk] = []

    # Each stack element is (name, kind) so we can check the enclosing scope's kind.
    def visit(node, name_stack: list[tuple[str, str]]) -> None:  # type: ignore[type-arg]
        kind = rules.node_kinds.get(node.kind())
        next_stack = name_stack
        if kind is not None:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name_br = name_node.byte_range()
                name = src_bytes[name_br.start:name_br.end].decode()
                # Only promote function→method when the immediate enclosing named
                # scope is a class (not another function).
                if kind == "function" and name_stack and name_stack[-1][1] == "class":
                    kind = "method"
                qualified = ".".join([s[0] for s in name_stack] + [name])
                # Decorated definitions: take content and start from the decorated_definition
                # parent so decorators are included; signature stays the inner definition's first line.
                parent = node.parent()
                if parent is not None and parent.kind() == "decorated_definition":
                    outer_br = parent.byte_range()
                    content = src_bytes[outer_br.start:outer_br.end].decode()
                    start_line = parent.start_position().row + 1
                    end_line = max(
                        parent.end_position().row + 1,
                        node.end_position().row + 1,
                    )
                else:
                    node_br = node.byte_range()
                    content = src_bytes[node_br.start:node_br.end].decode()
                    start_line = node.start_position().row + 1
                    end_line = node.end_position().row + 1
                # Signature always comes from the inner definition node's first line.
                node_br = node.byte_range()
                inner_content = src_bytes[node_br.start:node_br.end].decode()
                signature = inner_content.splitlines()[0].strip()
                chunks.append(
                    CodeChunk(
                        id=f"{path}::{qualified}",
                        path=path,
                        language=rules.language,
                        kind=kind,
                        name=qualified,
                        signature=signature,
                        content=content,
                        content_hash=hashlib.sha256(content.encode()).hexdigest(),
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
                next_stack = [*name_stack, (name, kind)]
        for i in range(node.child_count()):
            visit(node.child(i), next_stack)

    visit(tree.root_node(), [])
    return chunks
