# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Godot Project → Single Markdown Context Report (AI-friendly)

Generates ONE Markdown file containing:
- File tree (res://)
- Scene node trees (+ attached scripts)
- Script dependency graph (best-effort)
- Signal mapping (.tscn persisted [connection ...] + heuristic connect() scan)
- Exported vars (@export*)
- Class registry (class_name)
- Resource usage mapping (reverse index, best-effort)
- Unused resources (best-effort; excludes editor "recent/last opened" references)
- Input Map (ui_up, etc) parsed from project.godot

Notes:
- Text formats only: .tscn / .tres / .gd
- Binary .scn / .res are not supported
"""

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


# =========================
# USER CONFIG (edit these)
# =========================
# Folder containing project.godot
PROJECT_ROOT = Path(r"C:\Users\User\Documents\example").resolve()

# Default output location: inside the project root
OUTPUT_MD = (PROJECT_ROOT / "project_report.md").resolve()

# If True, dumps full GDScript contents (good for AI context, but report can be huge)
INCLUDE_SCRIPT_CONTENTS = True

IGNORE_DIRS = {".git", ".godot", ".import", "__pycache__", ".venv", "venv"}
IGNORE_FILES = {".DS_Store"}

# Treat these as "resources" for unused detection (best-effort).
RESOURCE_EXTS = {
    ".tscn", ".tres", ".gd", ".gdshader", ".gdshaderinc",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".svg",
    ".wav", ".ogg", ".mp3",
    ".ttf", ".otf",
    ".json", ".cfg", ".ini", ".csv", ".txt", ".md",
}

SCENE_EXTS = {".tscn"}
SCRIPT_EXTS = {".gd"}
TEXT_RESOURCE_EXTS = {".tres"}  # .res is often binary


# -------------------------
# Markdown helpers
# -------------------------
def choose_fence(text: str, char: str = "~") -> str:
    runs = re.findall(rf"{re.escape(char)}+", text)
    longest = max((len(r) for r in runs), default=0)
    return char * max(3, longest + 1)


def fenced(text: str, lang: str = "text") -> str:
    fence = choose_fence(text, "~")
    return f"{fence}{lang}\n{text}\n{fence}\n"


# -------------------------
# IO helpers
# -------------------------
def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def to_res_path(project_root: Path, p: Path) -> str:
    rel = p.relative_to(project_root).as_posix()
    return "res://" if rel == "." else f"res://{rel if rel.startswith('/') else '/' + rel}"


def normalize_res_like_path(raw: str, base_dir: Path, project_root: Path) -> str:
    s = raw.strip().strip('"').strip("'")
    if not s:
        return s
    if s.startswith("uid://"):
        return s
    if s.startswith("res://"):
        tail = s[len("res://") :].lstrip("/")
        return f"res:///{tail}" if tail else "res://"
    abs_path = (base_dir / s).resolve()
    try:
        return to_res_path(project_root, abs_path)
    except Exception:
        return s


# -------------------------
# Common patterns for references
# -------------------------
RES_STR_RE = re.compile(r"""(['"])(res://[^'"]+)\1""")
UID_STR_RE = re.compile(r"""(['"])(uid://[^'"]+)\1""")

EXTRESOURCE_ID_RE = re.compile(r'ExtResource\(\s*(?:"([^"]+)"|([^)]+))\s*\)')

HEADING_RE = re.compile(r"^\[(\w+)\s*(.*)\]\s*$")
KV_RE = re.compile(r'(\w+)\s*=\s*(".*?"|\S+)')


def parse_header_kv(header: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in KV_RE.finditer(header):
        k = m.group(1)
        v = m.group(2)
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out[k] = v
    return out


def extract_res_uid_strings(text: str, base_dir: Path, project_root: Path) -> Set[str]:
    refs: Set[str] = set()
    for _, p in RES_STR_RE.findall(text):
        refs.add(normalize_res_like_path(p, base_dir, project_root))
    for _, p in UID_STR_RE.findall(text):
        refs.add(p.strip())
    return refs


def parse_script_value(raw: str, ext_id_to_path: Dict[str, str], base_dir: Path, project_root: Path) -> Optional[str]:
    v = raw.strip()
    if v == "null":
        return None

    m = EXTRESOURCE_ID_RE.search(v)
    if m:
        rid = (m.group(1) or m.group(2) or "").strip()
        if not rid:
            return None
        p = ext_id_to_path.get(rid)
        if p:
            return normalize_res_like_path(p, base_dir, project_root)
        return f'ExtResource("{rid}")'

    m2 = RES_STR_RE.search(v)
    if m2:
        return normalize_res_like_path(m2.group(2), base_dir, project_root)
    m3 = UID_STR_RE.search(v)
    if m3:
        return m3.group(2)

    # Keep visibility for uncommon cases rather than dropping silently
    if "SubResource" in v:
        return v

    return None


# -------------------------
# project.godot parsing (INI-like, supports multi-line { ... } blocks)
# -------------------------
def _brace_delta_outside_quotes(s: str) -> int:
    delta = 0
    in_q: Optional[str] = None
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if in_q:
            if ch == in_q:
                in_q = None
            continue
        if ch in ('"', "'"):
            in_q = ch
            continue
        if ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
    return delta


def parse_project_godot(project_root: Path) -> Tuple[Optional[str], List[str], Dict[str, str]]:
    proj = project_root / "project.godot"
    if not proj.exists():
        return None, [], {}

    lines = read_text(proj).splitlines()
    data: Dict[str, Dict[str, str]] = {}
    section: Optional[str] = None

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line or line.startswith(";"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue

        if section and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()

            # multi-line dict block: key={ ... }
            if v.endswith("{") or v == "{":
                block = [v]
                bal = _brace_delta_outside_quotes(v)
                while i < len(lines) and bal > 0:
                    nxt = lines[i]
                    i += 1
                    block.append(nxt.rstrip("\n"))
                    bal += _brace_delta_outside_quotes(nxt)
                v = "\n".join(block)

            # strip quotes for simple one-liners (but keep multi-line as-is)
            if "\n" not in v and v.startswith('"') and v.endswith('"'):
                v = v[1:-1]

            data.setdefault(section, {})[k] = v

    # main scene
    main_scene = None
    app = data.get("application", {})
    if "run/main_scene" in app:
        main_scene = normalize_res_like_path(app["run/main_scene"], project_root, project_root)

    # autoloads
    autoloads: List[str] = []
    for _, val in data.get("autoload", {}).items():
        vv = val.strip()
        if vv.startswith("*"):
            vv = vv[1:]
        autoloads.append(normalize_res_like_path(vv, project_root, project_root))

    # input map (raw multi-line blocks)
    input_map = data.get("input", {}).copy() if "input" in data else {}
    return main_scene, autoloads, input_map


# -------------------------
# Detect editor "auto / recent" referenced scenes (best-effort)
# -------------------------
def detect_editor_references(project_root: Path) -> Set[str]:
    """
    Reads common editor metadata under .godot/editor/ and extracts res:// / uid:// strings.
    Used only to reduce false positives in "Unused Resources".
    """
    editor_dir = project_root / ".godot" / "editor"
    if not editor_dir.exists():
        return set()

    candidates = [
        editor_dir / "project_metadata.cfg",
        editor_dir / "editor_layout.cfg",
        editor_dir / "recent_dirs",
        editor_dir / "recent_files",
    ]

    refs: Set[str] = set()
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                txt = read_text(p)
            except Exception:
                continue
            refs |= extract_res_uid_strings(txt, p.parent, project_root)

    for cfg in editor_dir.glob("*.cfg"):
        try:
            txt = read_text(cfg)
        except Exception:
            continue
        refs |= extract_res_uid_strings(txt, cfg.parent, project_root)

    return refs


# -------------------------
# File collection
# -------------------------
def iter_project_files(project_root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn in IGNORE_FILES or fn.startswith("."):
                continue
            yield (Path(dirpath) / fn)


def collect_files(project_root: Path, exts: Set[str]) -> List[Path]:
    out = [p for p in iter_project_files(project_root) if p.suffix.lower() in exts]
    out.sort(key=lambda x: x.as_posix().casefold())
    return out


def collect_resource_files(project_root: Path) -> List[Path]:
    out = [p for p in iter_project_files(project_root) if p.suffix.lower() in RESOURCE_EXTS]
    out.sort(key=lambda x: x.as_posix().casefold())
    return out


# -------------------------
# File tree
# -------------------------
def build_file_tree(project_root: Path) -> str:
    lines: List[str] = ["res://"]

    def walk(cur: Path, indent: int) -> None:
        try:
            entries = list(cur.iterdir())
        except PermissionError:
            return

        dirs = sorted(
            [e for e in entries if e.is_dir() and e.name not in IGNORE_DIRS and not e.name.startswith(".")],
            key=lambda x: x.name.casefold(),
        )
        files = sorted(
            [e for e in entries if e.is_file() and e.name not in IGNORE_FILES and not e.name.startswith(".")],
            key=lambda x: x.name.casefold(),
        )

        pad = "  " * indent
        for d in dirs:
            lines.append(f"{pad}{d.name}/")
            walk(d, indent + 1)
        for f in files:
            lines.append(f"{pad}{f.name}")

    walk(project_root, 1)
    return "\n".join(lines)


# -------------------------
# Scene parsing (.tscn)
# -------------------------
@dataclass
class SceneNode:
    name: str
    type_name: str
    parent_full: Optional[str]
    order: int
    script_path: Optional[str] = None
    instance_path: Optional[str] = None
    children: List["SceneNode"] = field(default_factory=list)

    def script_label(self) -> Optional[str]:
        if not self.script_path:
            return None
        if self.script_path.startswith("res://"):
            tail = self.script_path.replace("res://", "").lstrip("/")
            return Path(tail).name
        return self.script_path

    def instance_label(self) -> Optional[str]:
        if not self.instance_path:
            return None
        if self.instance_path.startswith("res://"):
            tail = self.instance_path.replace("res://", "").lstrip("/")
            return Path(tail).name
        return self.instance_path


@dataclass
class SceneConnection:
    signal: str
    from_path: str
    to_path: str
    method: str


@dataclass
class SceneParseResult:
    scene_path: Path
    root: Optional[SceneNode]
    connections: List[SceneConnection]
    references: Set[str]
    warnings: List[str]


def parse_tscn(project_root: Path, scene_path: Path) -> SceneParseResult:
    text = read_text(scene_path)
    base_dir = scene_path.parent
    warnings: List[str] = []

    ext_id_to_path: Dict[str, str] = {}
    nodes: List[Tuple[Dict[str, str], Dict[str, str], int]] = []
    connections: List[SceneConnection] = []

    cur_node_hdr: Optional[Dict[str, str]] = None
    cur_node_props: Optional[Dict[str, str]] = None
    order = 0

    def flush_node() -> None:
        nonlocal cur_node_hdr, cur_node_props, order
        if cur_node_hdr is not None and cur_node_props is not None:
            nodes.append((cur_node_hdr, cur_node_props, order))
            order += 1
        cur_node_hdr, cur_node_props = None, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue

        m = HEADING_RE.match(line)
        if m:
            kind = m.group(1)
            hdr = m.group(2) or ""
            kv = parse_header_kv(hdr)

            if kind == "ext_resource":
                flush_node()
                rid = kv.get("id")
                p = kv.get("path")
                if rid and p:
                    ext_id_to_path[str(rid)] = p
                continue

            if kind == "node":
                flush_node()
                cur_node_hdr = kv
                cur_node_props = {}
                continue

            if kind == "connection":
                flush_node()
                sig = kv.get("signal", "")
                frm = kv.get("from", "")
                to = kv.get("to", "")
                method = kv.get("method", "")
                if sig and frm and to and method:
                    connections.append(SceneConnection(sig, frm, to, method))
                else:
                    warnings.append(f"Malformed connection heading: {line}")
                continue

            flush_node()
            continue

        if cur_node_props is not None and "=" in line:
            k, v = line.split("=", 1)
            cur_node_props[k.strip()] = v.strip()

    flush_node()

    if not nodes:
        warnings.append("No [node ...] blocks found; file may not be a text .tscn or format is unexpected.")
        return SceneParseResult(scene_path, None, connections, set(), warnings)

    ext_id_to_path_norm = {
        rid: normalize_res_like_path(p, base_dir, project_root) for rid, p in ext_id_to_path.items()
    }

    root_hdr, _, root_order = nodes[0]
    root_name = root_hdr.get("name", "<ROOT>")
    root_type = root_hdr.get("type", "Node")
    root = SceneNode(name=root_name, type_name=root_type, parent_full=None, order=root_order)

    path_to_node: Dict[str, SceneNode] = {root_name: root}

    for (hdr, props, idx) in nodes:
        name = hdr.get("name", f"<unnamed_{idx}>")
        parent_raw = hdr.get("parent")
        instance_raw = hdr.get("instance")

        type_name = hdr.get("type", "Node")
        instance_path = None
        if instance_raw:
            ip = parse_script_value(instance_raw, ext_id_to_path_norm, base_dir, project_root)
            instance_path = ip
            if "type" not in hdr:
                type_name = "Instance"

        if idx == 0:
            parent_full = None
            full_path = root_name
        else:
            parent_full = root_name if (not parent_raw or parent_raw == ".") else f"{root_name}/{parent_raw}"
            full_path = f"{parent_full}/{name}"

        script_path = None
        if "script" in props:
            script_path = parse_script_value(props["script"], ext_id_to_path_norm, base_dir, project_root)

        n = path_to_node.get(full_path)
        if n is None:
            path_to_node[full_path] = SceneNode(
                name=name,
                type_name=type_name,
                parent_full=parent_full,
                order=idx,
                script_path=script_path,
                instance_path=instance_path,
            )
        else:
            n.name = name
            n.type_name = type_name
            n.parent_full = parent_full
            n.order = idx
            n.script_path = script_path
            n.instance_path = instance_path

    for full_path, n in list(path_to_node.items()):
        if n is root:
            continue
        if not n.parent_full:
            warnings.append(f"Node has no parent: {full_path}")
            continue
        parent = path_to_node.get(n.parent_full)
        if not parent:
            warnings.append(f"Missing parent '{n.parent_full}' for node: {full_path}")
            continue
        parent.children.append(n)

    for n in path_to_node.values():
        n.children.sort(key=lambda c: c.order)

    references: Set[str] = set(ext_id_to_path_norm.values())
    references |= extract_res_uid_strings(text, base_dir, project_root)
    for mm in EXTRESOURCE_ID_RE.finditer(text):
        rid = (mm.group(1) or mm.group(2) or "").strip()
        if rid and rid in ext_id_to_path_norm:
            references.add(ext_id_to_path_norm[rid])

    return SceneParseResult(scene_path, root, connections, references, warnings)


def render_scene_tree(root: SceneNode) -> str:
    out: List[str] = []

    def walk(n: SceneNode, indent: int) -> None:
        pad = "  " * indent
        sl = n.script_label()
        il = n.instance_label()
        suffix = f" <{il}>" if il else ""
        out.append(f"{pad}{n.name} ({n.type_name}){suffix}" + (f" [{sl}]" if sl else ""))
        for c in n.children:
            walk(c, indent + 1)

    walk(root, 0)
    return "\n".join(out)


# -------------------------
# Text resource parsing (.tres)
# -------------------------
def parse_tres_references(project_root: Path, tres_path: Path) -> Set[str]:
    text = read_text(tres_path)
    base_dir = tres_path.parent

    ext_id_to_path: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = HEADING_RE.match(line)
        if m and m.group(1) == "ext_resource":
            kv = parse_header_kv(m.group(2) or "")
            rid = kv.get("id")
            p = kv.get("path")
            if rid and p:
                ext_id_to_path[str(rid)] = normalize_res_like_path(p, base_dir, project_root)

    refs: Set[str] = set(ext_id_to_path.values())
    refs |= extract_res_uid_strings(text, base_dir, project_root)
    for mm in EXTRESOURCE_ID_RE.finditer(text):
        rid = (mm.group(1) or mm.group(2) or "").strip()
        if rid and rid in ext_id_to_path:
            refs.add(ext_id_to_path[rid])
    return refs


# -------------------------
# Script parsing (.gd)
# -------------------------
CLASS_NAME_RE = re.compile(r"^\s*class_name\s+([A-Za-z_]\w*)", re.MULTILINE)
EXTENDS_RE = re.compile(r"^\s*extends\s+([^\s#]+)", re.MULTILINE)
SIGNAL_DECL_RE = re.compile(r"^\s*signal\s+([A-Za-z_]\w*)\s*(\([^)]*\))?", re.MULTILINE)

VAR_DECL_RE = re.compile(r"^\s*var\s+([A-Za-z_]\w*)\s*(?::\s*([^=]+))?\s*(?:=\s*(.*))?$")
CONNECT_CALL_RE = re.compile(
    r"""(?x)
    (?P<lhs>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\.\s*connect\s*\(\s*
    (?:
        (?P<sigq>["'])(?P<sig>[^"']+)(?P=sigq)
        |
        (?P<sigident>[A-Za-z_]\w*)
    )
    """,
    re.MULTILINE,
)


@dataclass
class ExportedVar:
    decorators: List[str]
    name: str
    vtype: str
    default: str


@dataclass
class ScriptParseResult:
    script_path: Path
    res_path: str
    class_name: Optional[str]
    extends: Optional[str]
    signals: List[Tuple[str, str]]
    exports: List[ExportedVar]
    references: Set[str]
    connect_calls: List[Tuple[str, str]]
    content: str


def parse_gd(project_root: Path, gd_path: Path) -> ScriptParseResult:
    text = read_text(gd_path)
    res_path = to_res_path(project_root, gd_path)

    class_name = None
    mcn = CLASS_NAME_RE.search(text)
    if mcn:
        class_name = mcn.group(1)

    extends = None
    mex = EXTENDS_RE.search(text)
    if mex:
        extends = mex.group(1)

    signals: List[Tuple[str, str]] = [(ms.group(1), (ms.group(2) or "").strip()) for ms in SIGNAL_DECL_RE.finditer(text)]

    exports: List[ExportedVar] = []
    pending: List[str] = []

    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        if s.startswith("@export"):
            if " var " in f" {s} ":
                parts = s.split(" var ", 1)
                deco_only = parts[0].strip()
                rest = "var " + parts[1].strip()
                mvar = VAR_DECL_RE.match(rest)
                if mvar:
                    exports.append(
                        ExportedVar(
                            [deco_only],
                            mvar.group(1),
                            (mvar.group(2) or "").strip(),
                            (mvar.group(3) or "").strip(),
                        )
                    )
                pending.clear()
            else:
                pending.append(s)
            continue

        if pending:
            mvar = VAR_DECL_RE.match(line)
            if mvar:
                exports.append(
                    ExportedVar(
                        pending[:],
                        mvar.group(1),
                        (mvar.group(2) or "").strip(),
                        (mvar.group(3) or "").strip(),
                    )
                )
                pending.clear()
            if len(pending) > 8:
                pending = pending[-2:]

    references = extract_res_uid_strings(text, gd_path.parent, project_root)

    connect_calls: List[Tuple[str, str]] = []
    for mc in CONNECT_CALL_RE.finditer(text):
        lhs = mc.group("lhs") or ""
        sig = mc.group("sig") or mc.group("sigident") or ""
        if lhs and sig:
            connect_calls.append((lhs, sig))

    return ScriptParseResult(
        script_path=gd_path,
        res_path=res_path,
        class_name=class_name,
        extends=extends,
        signals=signals,
        exports=exports,
        references=references,
        connect_calls=connect_calls,
        content=text.rstrip("\n"),
    )


# -------------------------
# Input Map parsing (project.godot [input])
# -------------------------
OBJ_HEAD_RE = re.compile(r"Object\(\s*([A-Za-z_]\w*)\s*,")
FIELD_INT_RE = re.compile(r'"([^"]+)"\s*:\s*(-?\d+)')
FIELD_BOOL_RE = re.compile(r'"([^"]+)"\s*:\s*(true|false)')
FIELD_FLOAT_RE = re.compile(r'"([^"]+)"\s*:\s*(-?\d+(?:\.\d+)?)')


def split_object_variants(s: str) -> List[str]:
    out: List[str] = []
    i = 0
    while True:
        start = s.find("Object(", i)
        if start < 0:
            break
        depth = 0
        j = start
        while j < len(s):
            ch = s[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out.append(s[start : j + 1])
                    i = j + 1
                    break
            j += 1
        else:
            break
    return out


def event_summary(obj: str) -> str:
    mh = OBJ_HEAD_RE.search(obj)
    cls = mh.group(1) if mh else "Unknown"

    ints = dict(FIELD_INT_RE.findall(obj))
    bools = {k: (v == "true") for k, v in FIELD_BOOL_RE.findall(obj)}
    floats = dict(FIELD_FLOAT_RE.findall(obj))

    def mods() -> str:
        parts = []
        if bools.get("shift_pressed"):
            parts.append("Shift")
        if bools.get("ctrl_pressed"):
            parts.append("Ctrl")
        if bools.get("alt_pressed"):
            parts.append("Alt")
        if bools.get("meta_pressed"):
            parts.append("Meta")
        return "+".join(parts)

    if cls == "InputEventKey":
        keycode = int(ints.get("keycode", "0"))
        physical = int(ints.get("physical_keycode", "0"))
        uni = int(ints.get("unicode", "0"))

        if 32 <= uni <= 126:
            label = f"'{chr(uni)}' (unicode={uni})"
        elif 65 <= physical <= 90:
            label = f"'{chr(physical)}' (physical={physical})"
        elif 32 <= keycode <= 126:
            label = f"'{chr(keycode)}' (keycode={keycode})"
        else:
            label = f"keycode={keycode}" if keycode else (f"physical={physical}" if physical else (f"unicode={uni}" if uni else "key=?"))

        m = mods()
        return f"Key {label}" + (f" + {m}" if m else "")

    if cls == "InputEventMouseButton":
        bi = ints.get("button_index") or ints.get("button")
        return f"MouseButton {bi}" if bi else "MouseButton"

    if cls == "InputEventJoypadButton":
        bi = ints.get("button_index") or ints.get("button")
        return f"JoypadButton {bi}" if bi else "JoypadButton"

    if cls == "InputEventJoypadMotion":
        axis = ints.get("axis", "?")
        av = floats.get("axis_value", "")
        return f"JoypadAxis axis={axis} value={av}" if av else f"JoypadAxis axis={axis}"

    if cls == "InputEventAction":
        act = ints.get("action", "")
        return f"Action {act}" if act else "Action"

    return cls


def parse_input_map_variants(input_map: Dict[str, str]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for action, raw in input_map.items():
        dz = None
        m = re.search(r'"deadzone"\s*:\s*([0-9.]+)', raw)
        if m:
            try:
                dz = float(m.group(1))
            except ValueError:
                dz = None

        objs = split_object_variants(raw)
        events = [event_summary(o) for o in objs] if objs else []
        out[action] = {"deadzone": dz, "events": events, "raw": raw}
    return out


# -------------------------
# Graph helpers
# -------------------------
def build_reverse_index(edges: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    rev: Dict[str, Set[str]] = {}
    for src, tgts in edges.items():
        for t in tgts:
            rev.setdefault(t, set()).add(src)
    return rev


def sanitize_mermaid_id(s: str) -> str:
    return "N" + re.sub(r"[^A-Za-z0-9_]", "_", s)


def mermaid_graph(edges: List[Tuple[str, str]], title: str) -> str:
    lines = ["```mermaid", "graph TD", f"%% {title}"]
    for a, b in edges:
        ida = sanitize_mermaid_id(a)
        idb = sanitize_mermaid_id(b)
        la = a.replace('"', '\\"')
        lb = b.replace('"', '\\"')
        lines.append(f'{ida}["{la}"] --> {idb}["{lb}"]')
    lines.append("```")
    return "\n".join(lines) + "\n"


# -------------------------
# Report generation
# -------------------------
def generate_report(project_root: Path, output_md: Path) -> None:
    if not project_root.exists() or not project_root.is_dir():
        raise RuntimeError(f"PROJECT_ROOT does not exist or is not a directory: {project_root}")

    now = dt.datetime.now().astimezone()

    main_scene, autoloads, input_map_raw = parse_project_godot(project_root)
    input_map = parse_input_map_variants(input_map_raw)
    editor_refs = detect_editor_references(project_root)

    scenes = collect_files(project_root, SCENE_EXTS)
    scripts = collect_files(project_root, SCRIPT_EXTS)
    tres_files = collect_files(project_root, TEXT_RESOURCE_EXTS)
    resource_files = collect_resource_files(project_root)

    scene_results = [parse_tscn(project_root, sp) for sp in scenes]
    script_results = [parse_gd(project_root, gp) for gp in scripts]

    # .tres references
    tres_refs: Dict[str, Set[str]] = {}
    for tp in tres_files:
        tres_refs[to_res_path(project_root, tp)] = parse_tres_references(project_root, tp)

    # Build edges: source -> targets
    edges: Dict[str, Set[str]] = {}

    for r in scene_results:
        src = to_res_path(project_root, r.scene_path)
        edges[src] = set(r.references)
        if r.root:
            stack = [r.root]
            while stack:
                n = stack.pop()
                if n.script_path and n.script_path.startswith("res://"):
                    edges[src].add(n.script_path)
                if n.instance_path and n.instance_path.startswith("res://"):
                    edges[src].add(n.instance_path)
                stack.extend(n.children)

    for sr in script_results:
        edges[sr.res_path] = set(sr.references)

    for src, refs in tres_refs.items():
        edges[src] = set(refs)

    # project roots
    project_src = "project://project.godot"
    edges.setdefault(project_src, set())
    roots: Set[str] = set()
    if main_scene:
        edges[project_src].add(main_scene)
        roots.add(main_scene)
    for a in autoloads:
        edges[project_src].add(a)
        roots.add(a)

    # editor refs are only used to exclude from unused list
    auto_ignore_from_unused = set(editor_refs)

    # Class registry & class-name token dependency (best-effort)
    class_registry: List[Tuple[str, str, str]] = []
    class_to_script: Dict[str, str] = {}
    for sr in script_results:
        if sr.class_name:
            class_to_script[sr.class_name] = sr.res_path
            class_registry.append((sr.class_name, sr.res_path, sr.extends or ""))

    if class_to_script:
        compiled = {cn: re.compile(rf"\b{re.escape(cn)}\b") for cn in class_to_script}
        for sr in script_results:
            for cn, cre in compiled.items():
                if cn == sr.class_name:
                    continue
                if cre.search(sr.content):
                    edges.setdefault(sr.res_path, set()).add(class_to_script[cn])

    used_by = build_reverse_index(edges)

    # Unused resources (best-effort)
    all_resources_set: Set[str] = set()
    for p in resource_files:
        try:
            all_resources_set.add(to_res_path(project_root, p))
        except Exception:
            continue

    used_set: Set[str] = set(used_by.keys()) | roots

    unused = sorted(
        [r for r in all_resources_set if (r not in used_set) and (r not in auto_ignore_from_unused)],
        key=lambda x: x.casefold(),
    )

    # Resource usage map (reverse)
    usage_map: Dict[str, List[str]] = {}
    for tgt, srcs in used_by.items():
        if tgt.startswith("res://") and tgt in all_resources_set:
            usage_map[tgt] = sorted(srcs, key=lambda x: x.casefold())

    # Script dependency edges (Mermaid)
    script_to_script_edges: List[Tuple[str, str]] = []
    for src, tgts in edges.items():
        if src.startswith("res://") and src.endswith(".gd"):
            for t in tgts:
                if isinstance(t, str) and t.startswith("res://") and t.endswith(".gd"):
                    script_to_script_edges.append((src, t))
    script_to_script_edges = sorted(set(script_to_script_edges), key=lambda x: (x[0].casefold(), x[1].casefold()))

    # Scene persisted connections
    all_connections: List[Tuple[str, SceneConnection]] = []
    for r in scene_results:
        scene_res = to_res_path(project_root, r.scene_path)
        for c in r.connections:
            all_connections.append((scene_res, c))

    # Exported vars aggregated
    exported_rows: List[Tuple[str, str, str, str]] = []
    for sr in script_results:
        for ev in sr.exports:
            exported_rows.append((sr.res_path, ev.name, ev.vtype, " | ".join(ev.decorators)))

    # Declared signals aggregated
    declared_signal_rows: List[Tuple[str, str, str]] = []
    for sr in script_results:
        for sig, params in sr.signals:
            declared_signal_rows.append((sr.res_path, sig, params))

    # -------------------------
    # Markdown
    # -------------------------
    md: List[str] = []
    md.append("# Godot Project Context Report\n")
    md.append(f"- Generated at: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    md.append(f"- Project root (as res://): `{project_root.as_posix()}`")
    md.append(f"- Scenes: {len(scenes)}")
    md.append(f"- Scripts: {len(scripts)}")
    md.append(f"- Text Resources (.tres): {len(tres_files)}")
    md.append(f"- Resource files (for unused check): {len(resource_files)}\n")

    md.append("## 0) Project Settings\n")
    md.append(f"- Main scene: `{main_scene or ''}`")
    if autoloads:
        md.append("- Autoloads:")
        for a in autoloads:
            md.append(f"  - `{a}`")
    else:
        md.append("- Autoloads: (none detected)")
    if auto_ignore_from_unused:
        md.append(f"- Editor auto/recent references (excluded from Unused): {len(auto_ignore_from_unused)}")
    md.append("")

    md.append("## 0.1) Input Map (project.godot)\n")
    if input_map:
        md.append("| action | deadzone | events |")
        md.append("|---|---:|---|")
        for action in sorted(input_map.keys(), key=lambda x: x.casefold()):
            dz = input_map[action]["deadzone"]
            evs = input_map[action]["events"]
            ev_text = "<br>".join(evs) if evs else "(no events parsed)"
            md.append(f"| `{action}` | `{dz if dz is not None else ''}` | {ev_text} |")
        md.append("")
        md.append("<details><summary>Raw Input Map (verbatim)</summary>\n")
        raw_lines = []
        for action in sorted(input_map_raw.keys(), key=lambda x: x.casefold()):
            raw_lines.append(f"{action}={input_map_raw[action]}")
        md.append(fenced("\n".join(raw_lines), "text"))
        md.append("</details>\n")
    else:
        md.append("(No [input] section found.)\n")

    md.append("## 1) File Tree (res://)\n")
    md.append(fenced(build_file_tree(project_root), "text"))

    md.append("## 2) Scene Node Trees (with attached scripts)\n")
    for r in scene_results:
        scene_res = to_res_path(project_root, r.scene_path)
        md.append(f"### <Scene> {r.scene_path.name}\n")
        md.append(f"`{scene_res}`\n")

        if not r.root:
            md.append("> Failed to parse this scene.\n")
            for w in r.warnings:
                md.append(f"> - {w}")
            md.append("")
            continue

        md.append(fenced(render_scene_tree(r.root), "text"))

        if r.connections:
            md.append("**Persisted Signal Connections** (`[connection ...]` in .tscn)\n")
            md.append("| from | signal | to | method |")
            md.append("|---|---|---|---|")
            for c in r.connections:
                md.append(f"| `{c.from_path}` | `{c.signal}` | `{c.to_path}` | `{c.method}` |")
            md.append("")

        if r.warnings:
            md.append("> Warnings:")
            for w in r.warnings:
                md.append(f"> - {w}")
            md.append("")

    md.append("## 3) Script Registry (class_name / extends)\n")
    if class_registry:
        md.append("| class_name | script | extends |")
        md.append("|---|---|---|")
        for cn, sp, ex in sorted(class_registry, key=lambda x: x[0].casefold()):
            md.append(f"| `{cn}` | `{sp}` | `{ex}` |")
        md.append("")
    else:
        md.append("(No `class_name` found.)\n")

    md.append("## 4) Exported Variables (@export*)\n")
    if exported_rows:
        md.append("| script | var | type | decorators |")
        md.append("|---|---|---|---|")
        for sp, name, vtype, deco in sorted(exported_rows, key=lambda x: (x[0].casefold(), x[1].casefold())):
            md.append(f"| `{sp}` | `{name}` | `{vtype}` | `{deco}` |")
        md.append("")
    else:
        md.append("(No `@export` variables found.)\n")

    md.append("## 5) Signal Mapping\n")
    md.append("### 5.1 Persisted scene connections (.tscn `[connection ...]`)\n")
    if all_connections:
        md.append("| scene | from | signal | to | method |")
        md.append("|---|---|---|---|---|")
        for scene_res, c in all_connections:
            md.append(f"| `{scene_res}` | `{c.from_path}` | `{c.signal}` | `{c.to_path}` | `{c.method}` |")
        md.append("")
    else:
        md.append("(No persisted `.tscn` connections found.)\n")

    md.append("### 5.2 Declared signals in scripts (`signal ...`)\n")
    if declared_signal_rows:
        md.append("| script | signal | params |")
        md.append("|---|---|---|")
        for sp, sig, params in sorted(declared_signal_rows, key=lambda x: (x[0].casefold(), x[1].casefold())):
            md.append(f"| `{sp}` | `{sig}` | `{params}` |")
        md.append("")
    else:
        md.append("(No `signal` declarations found.)\n")

    md.append("### 5.3 Potential code-based `connect()` calls (heuristic)\n")
    any_connect = False
    for sr in script_results:
        if sr.connect_calls:
            any_connect = True
            md.append(f"- `{sr.res_path}`")
            for lhs, sig in sr.connect_calls[:80]:
                md.append(f"  - `{lhs}.connect({sig})`")
    if not any_connect:
        md.append("(No `connect()` patterns detected.)\n")
    md.append("")

    md.append("## 6) Script Dependency Graph (best-effort)\n")
    if script_to_script_edges:
        md.append(mermaid_graph(script_to_script_edges, "Script → Script dependencies"))
    else:
        md.append("(No script→script edges detected.)\n")

    md.append("## 7) Resource Usage Mapping (reverse index)\n")
    md.append("> `target` ← referenced by `sources` (best-effort)\n")
    if usage_map:
        md.append("<details><summary>Show usage map</summary>\n")
        lines: List[str] = []
        for tgt in sorted(usage_map.keys(), key=lambda x: x.casefold()):
            lines.append(tgt)
            for src in usage_map[tgt]:
                lines.append(f"  <- {src}")
            lines.append("")
        md.append(fenced("\n".join(lines).rstrip(), "text"))
        md.append("</details>\n")
    else:
        md.append("(No resource usage edges detected.)\n")

    md.append("## 8) Unused Resources (best-effort)\n")
    md.append("> Unused = not referenced by parsed scenes/scripts/tres, not main scene/autoload, and not in editor auto/recent references.\n")
    if unused:
        md.append(f"- Unused count: **{len(unused)}**\n")
        by_ext: Dict[str, List[str]] = {}
        for r in unused:
            ext = Path(r.replace("res://", "").replace("res:///", "")).suffix.lower()
            by_ext.setdefault(ext or "(no_ext)", []).append(r)

        for ext in sorted(by_ext.keys(), key=lambda x: x.casefold()):
            md.append(f"### {ext}\n")
            md.append(fenced("\n".join(by_ext[ext]), "text"))
    else:
        md.append("(No unused resources detected by current heuristics.)\n")

    md.append("## 9) Scripts (details)\n")
    for sr in script_results:
        md.append(f"### <Script> {sr.script_path.name}\n")
        md.append(f"`{sr.res_path}`\n")
        md.append(f"- class_name: `{sr.class_name or ''}`")
        md.append(f"- extends: `{sr.extends or ''}`")
        md.append(f"- referenced resources (strings): {len(sr.references)}")
        md.append(f"- exported vars: {len(sr.exports)}")
        md.append(f"- declared signals: {len(sr.signals)}\n")

        if sr.exports:
            md.append("| var | type | default | decorators |")
            md.append("|---|---|---|---|")
            for ev in sr.exports:
                md.append(f"| `{ev.name}` | `{ev.vtype}` | `{ev.default}` | `{ ' | '.join(ev.decorators) }` |")
            md.append("")

        if INCLUDE_SCRIPT_CONTENTS:
            md.append(fenced(sr.content, "gdscript"))

    md.append("## 10) Caveats (static analysis limits)\n")
    md.append("- Dynamic loads (constructed paths, runtime resources) may not be detected.")
    md.append("- `uid://...` references are preserved but not resolved to filesystem paths here.")
    md.append("- Editor metadata files may contain personal/temporary paths; they are only used to avoid false 'unused' reports.\n")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(md).replace("\r\n", "\n"), encoding="utf-8")


if __name__ == "__main__":
    generate_report(PROJECT_ROOT, OUTPUT_MD)
    print(f"✅ Report written to: {OUTPUT_MD}")
