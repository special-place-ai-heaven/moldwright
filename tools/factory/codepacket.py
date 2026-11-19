import ast
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cutshape
import proof

WHOLE_CHARS = 12000
BLOCK_LINES = 150
OUTLINE_CUT = 100
MATCHES = 2
READ_S = 6
NOTE_ROOM = 200
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
DECL = (r"^(\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:(?:async|unsafe|const|static)\s+)*"
        r"(?:def|class|function\*?|interface|type|enum|const|let|var|fn|struct|trait|mod|impl)\s+%s\b")
METHOD = r"^(\s+)(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*%s\s*(?:<[^>]*>)?\("


def units(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def paths(body, number):
    return cutshape.parse({"number": number, "body": body})["paths"]


def names(body):
    out = []
    for ask in proof.change_asks(body):
        for span in re.findall(r"`([^`]*)`", ask):
            for name in IDENT.findall(span):
                if len(name) >= 3 and name not in out:
                    out.append(name)
    return out


def python_defs(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    out = []

    def walk(node, depth):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                out.append((start, child.end_lineno, child.name, depth, child.lineno))
                walk(child, depth + 1)
            else:
                walk(child, depth)
    walk(tree, 0)
    return sorted(out)


def indent(line):
    wide = line.expandtabs(4)
    return len(wide) - len(wide.lstrip(" "))


def block_end(lines, i):
    base, end, j = indent(lines[i]), i, i + 1
    while j < len(lines):
        s = lines[j].strip()
        if not s or indent(lines[j]) > base:
            end = j if s else end
            j += 1
            continue
        if s[0] in ")]}":
            end = j
            if s[-1] in "{([:":
                j += 1
                continue
        break
    return end


def named(lines, name):
    word = re.escape(name)
    hits = [i for i, line in enumerate(lines) if re.match(DECL % word, line)]
    if not hits:
        hits = [i for i, line in enumerate(lines) if re.match(METHOD % word, line) and line.rstrip().endswith(("{", "(", ","))
                and "=>" not in line and "function" not in line]
    return [(i + 1, block_end(lines, i) + 1) for i in hits[:MATCHES]]


def render(path, text, wanted, label, outline_only=False):
    if text is None:
        return "### `%s`: not on %s (a new file, or GitHub did not give it)" % (path, label)
    if "\x00" in text:
        return "### `%s`: binary, not shown" % path
    lines = text.splitlines()
    if units(text) <= WHOLE_CHARS and not outline_only:
        return "### `%s` (whole, %d lines)\n%s" % (path, len(lines), text.rstrip("\n"))
    defs = python_defs(text) if path.endswith(".py") else None
    out = []
    if defs:
        out.append("### `%s` (%d lines: outline and the named definitions)" % (path, len(lines)))
        out.append("outline:")
        out += ["  %d: %s" % (d[4], lines[d[4] - 1].strip()[:OUTLINE_CUT]) for d in defs if d[3] <= 1]
    else:
        out.append("### `%s` (%d lines: the named definitions)" % (path, len(lines)))
    if outline_only:
        if not defs:
            out.append("(not shown in full: the packet's code room is used; read it in your worktree)")
        return "\n".join(out)
    if defs is not None:
        blocks = [(d[0], d[1]) for d in defs if d[2] in wanted]
    else:
        blocks = [b for name in wanted for b in named(lines, name)]
    shown, last = 0, 0
    for a, b in sorted(set(blocks)):
        if a <= last:
            continue
        out.append("lines %d-%d:" % (a, b))
        if b - a + 1 > BLOCK_LINES:
            out += lines[a - 1:a - 1 + BLOCK_LINES]
            out.append("[... %d more lines: sed -n '%d,%dp' %s]" % (b - a + 1 - BLOCK_LINES, a + BLOCK_LINES, b, path))
        else:
            out += lines[a - 1:b]
        shown, last = shown + 1, b
    if not shown:
        out.append("(no definition that **Change** names is in this file; read it in your worktree)")
    return "\n".join(out)


def section(body, number, read, label, cap, seconds, clock=time.monotonic):
    head = "## Code on %s (the files of **Files** as they are there; your worktree may be newer)" % label
    files = paths(body, number)
    if not files:
        return head + "\n(the issue has no **Files** block)"
    wanted, pieces, used, t0 = names(body), [head], units(head), clock()
    for k, path in enumerate(files):
        room = NOTE_ROOM * (len(files) - k - 1)
        left = seconds - (clock() - t0)
        if left <= 0:
            piece = "### `%s`: not shown, the packet's %s s for code reads ran out; read it in your worktree" % (path, seconds)
        else:
            text = read(path, min(READ_S, left))
            piece = render(path, text, wanted, label)
            if used + units(piece) + 1 + room > cap:
                piece = render(path, text, wanted, label, outline_only=True)
                if used + units(piece) + 1 + room > cap:
                    piece = "### `%s`: not shown, the packet's code room of %d characters is used; read it in your worktree" % (path, cap)
        pieces.append(piece)
        used += units(piece) + 1
    return "\n".join(pieces)
