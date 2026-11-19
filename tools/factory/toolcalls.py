import json
import os
import re

READ = {"cat", "ls", "sed", "grep", "egrep", "fgrep", "rg", "head", "tail", "find", "wc", "nl", "tree", "stat", "file", "awk", "less",
        "more", "diff", "sort", "uniq", "cut", "jq"}
GIT_READ = {"show", "log", "diff", "grep", "blame", "ls-files"}
NEUTRAL = {"cd", "echo", "printf", "true", "false", "pwd", ":", "done", "fi", "esac", "for", "in", "{", "}", "set", "export", "exit",
           "return", "local", "test", "["}
LEAD = {"do", "then", "else", "elif", "if", "while", "until", "!", "time", "env", "command", "exec", "nohup", "timeout", "nice", "stdbuf"}
WRAPPERS = {"timeout", "nice", "stdbuf"}
WRAP_VALUE = {"-n", "-s", "-k", "--signal", "--kill-after", "--adjustment", "-i", "-o", "-e", "--input", "--output", "--error"}
DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
FIND_ACTS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}
HEREDOC = re.compile(r"(?<![<\w])<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MARK = re.compile(r"… \[truncated\] \d+ more chars elided to save context$")
CMD = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)')
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIR = re.compile(r"^(?:\d+|&)?([<>]+)(&?)(.*)$")
OPWORD = re.compile(r"^\d*&?[<>&]*$")


def command(call):
    if str(call.get("tool") or "").split("__")[-1] != "shell_exec":
        return None
    raw = call.get("input")
    try:
        if isinstance(raw, dict):
            cmd = raw.get("command")
        else:
            text = MARK.sub("", str(raw))
            try:
                cmd = json.loads(text)["command"]
            except Exception:
                m = CMD.search(text)
                cmd = json.loads('"' + m.group(1) + '"') if m else ""
    except Exception:
        cmd = ""
    return cmd if isinstance(cmd, str) else ""


def drop_heredocs(text):
    out, waiting = [], []
    for line in text.split("\n"):
        if waiting:
            if line.strip() == waiting[0]:
                waiting.pop(0)
            continue
        out.append(line)
        waiting = [m.group(2) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def parts(text):
    found, part, word = [], [], []
    state = {"has": False, "bare": True}

    def end_word():
        if state["has"]:
            part.append(("".join(word), state["bare"]))
        word.clear()
        state["has"], state["bare"] = False, True

    def end_part():
        end_word()
        if part:
            found.append(list(part))
        part.clear()

    def take(chars, bare):
        if not state["has"]:
            state["has"], state["bare"] = True, bare
        word.append(chars)

    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            take(text[i + 1:j], False)
            i = j + 1
        elif c == '"':
            take("", False)
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n and text[i + 1] in '"\\$`':
                    word.append(text[i + 1])
                    i += 2
                else:
                    word.append(text[i])
                    i += 1
            i += 1
        elif c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            take(text[i + 1:i + 2], False)
            i += 2
        elif c in " \t\r":
            end_word()
            i += 1
        elif c == "#" and not state["has"]:
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c in "<>":
            if state["has"] and not (state["bare"] and OPWORD.match("".join(word))):
                end_word()
            take(c, True)
            i += 1
        elif c == "&" and ((state["has"] and state["bare"] and OPWORD.match("".join(word)) and re.search(r"[<>]", "".join(word)))
                           or text[i + 1:i + 2] == ">"):
            if state["has"] and not (state["bare"] and OPWORD.match("".join(word))):
                end_word()
            take(c, True)
            i += 1
        elif c in ";|&()\n":
            end_part()
            i += 1
        else:
            take(c, True)
            i += 1
    end_part()
    return found


def strip_redirects(part):
    words, writes, i = [], False, 0
    while i < len(part):
        w, bare = part[i]
        m = REDIR.match(w) if bare else None
        i += 1
        if m is None:
            words.append(w)
            continue
        target = m.group(3)
        if not target and i < len(part):
            target = part[i][0]
            i += 1
        dup = m.group(2) == "&" and (target.isdigit() or target == "-")
        if ">" in m.group(1) and target != "/dev/null" and not dup:
            writes = True
    return words, writes


def head(words):
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if w in LEAD or ASSIGN.match(w):
            i += 1
            if w in WRAPPERS:
                while i < n and words[i].startswith("-"):
                    i += 2 if words[i] in WRAP_VALUE else 1
                if w == "timeout" and i < n and DURATION.match(words[i]):
                    i += 1
            continue
        return os.path.basename(w), words[i + 1:]
    return "", []


def read_part(name, rest, writes):
    if writes:
        return False
    if name == "git":
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-C", "-c") else 1
        return i < len(rest) and rest[i] in GIT_READ
    if name == "sed" and any(re.match(r"^-[A-Za-z]*i", w) or w.startswith("--in-place") for w in rest):
        return False
    if name == "find" and any(w in FIND_ACTS for w in rest):
        return False
    return name in READ


def classify(cmd):
    named, reads, writes, sleep = False, True, False, False
    for p in parts(drop_heredocs(cmd)):
        words, w = strip_redirects(p)
        name, rest = head(words)
        writes = writes or w
        sleep = sleep or name == "sleep"
        if name and name not in NEUTRAL:
            named = True
            reads = reads and read_part(name, rest, w)
    return named and reads and not writes, sleep


def count(calls):
    c = {"shell": 0, "read": 0, "sleep": 0}
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, dict):
            continue
        cmd = command(call)
        if cmd is None:
            continue
        read, sleep = classify(cmd)
        c["shell"] += 1
        c["read"] += int(read)
        c["sleep"] += int(sleep)
    return c
