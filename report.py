# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Godot Project → Single Markdown Report

Outputs ONE Markdown file containing:
1) Full file tree (res://)
2) .tscn scene node trees + attached scripts
3) Full contents of all .gd scripts

Assumption: PROJECT_ROOT is the Godot project root, treated as res://
"""

import argparse
import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# =========================
# USER CONFIG (hard-coded defaults)
# =========================
PROJECT_ROOT = Path(r"").resolve()
OUTPUT_MD = Path(r"").resolve()

IGNORE_DIRS = {".git", ".godot", ".import", "__pycache__", ".venv", "venv"}
IGNORE_FILES = {".DS_Store"}

SCENE_EXTS = {".tscn"}  # .scn is often binary; not supported here


# -------------------------
# Markdown helpers
# -------------------------
def choose_fence(text: str, char: str) -> str:
    """
    Return a fence string that:
    - Uses the given char (e.g. '~' or '`')
    - Is always at least length 3
    - Is longer than any run of that char inside 'text'
    """
    runs = re.findall(rf"{re.escape(char)}+", text)
    longest = max((len(r) for r in runs), default=0)
    return char * max(3, longest + 1)


def fenced(text: str, lang: str = "text") -> str:
    """
    Create a fenced code block safely.
    Use ~~~ by default to avoid conflicts with ``` inside code snippets/comments.
    """
    char = "~"
    fence = choose_fence(text, char)
    return f"{fence}{lang}\n{text}\n{fence}\n"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def to_res_path(project_root: Path, p: Path) -> str:
    rel = p.relative_to(project_root).as_posix()
    return "res://" if rel == "." else f"res:///{rel}"


# -------------------------
# File tree
# -------------------------
def build_file_tree(project_root: Path) -> str:
    """
    Produce a tree like:
    res://
      scenes/
        main.tscn
      scripts/
        main.gd
    """
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
# TSCN parsing (robust for Godot 4 id formats)
# -------------------------
EXT_RESOURCE_HEADER_RE = re.compile(r"^\[ext_resource\s+(.*)\]\s*$")
NODE_HEADER_RE = re.compile(r"^\[node\s+(.*)\]\s*$")
KV_RE = re.compile(r'(\w+)\s*=\s*(".*?"|\S+)')

# Supports:
# - ExtResource(3)
# - ExtResource("3")
# - ExtResource("1_abcd")
# - ExtResource( 1_abcd )
EXTRESOURCE_ID_RE = re.compile(r'ExtResource\(\s*(?:"([^"]+)"|([^)]+))\s*\)')
RES_PATH_IN_QUOTES_RE = re.compile(r'"(res://[^"]+)"')


def parse_header_kv(header: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in KV_RE.finditer(header):
        k = m.group(1)
        v = m.group(2)
        out[k] = v[1:-1] if v.startswith('"') and v.endswith('"') else v
    return out


def parse_script_value(raw: str, ext_id_to_path: Dict[str, str]) -> Optional[str]:
    v = raw.strip()
    if v == "null":
        return None

    m = EXTRESOURCE_ID_RE.search(v)
    if m:
        rid = (m.group(1) or m.group(2) or "").strip()
        if not rid:
            return None
        return ext_id_to_path.get(rid, f"ExtResource({rid})")

    m2 = RES_PATH_IN_QUOTES_RE.search(v)
    if m2:
        return m2.group(1)

    # Keep visibility for uncommon cases rather than dropping silently
    if "SubResource" in v:
        return v

    return None


@dataclass
class SceneNode:
    name: str
    type_name: str
    parent_full: Optional[str]
    order: int
    script_path: Optional[str] = None
    children: List["SceneNode"] = field(default_factory=list)

    def script_label(self) -> Optional[str]:
        if not self.script_path:
            return None
        if self.script_path.startswith("res://"):
            return Path(self.script_path.replace("res://", "").lstrip("/")).name
        return self.script_path


def parse_tscn(scene_path: Path) -> Tuple[Optional[SceneNode], List[str]]:
    warnings: List[str] = []
    text = read_text(scene_path)
    lines = text.splitlines()

    ext_id_to_path: Dict[str, str] = {}
    nodes: List[Tuple[Dict[str, str], Dict[str, str]]] = []  # (header kv, props kv)

    cur_hdr: Optional[Dict[str, str]] = None
    cur_props: Optional[Dict[str, str]] = None

    def flush() -> None:
        nonlocal cur_hdr, cur_props
        if cur_hdr is not None and cur_props is not None:
            nodes.append((cur_hdr, cur_props))
        cur_hdr, cur_props = None, None

    for raw in lines:
        line = raw.strip()

        if line.startswith("[") and line.endswith("]"):
            mnode = NODE_HEADER_RE.match(line)
            if mnode:
                flush()
                cur_hdr = parse_header_kv(mnode.group(1))
                cur_props = {}
                continue

            mext = EXT_RESOURCE_HEADER_RE.match(line)
            if mext:
                flush()
                kv = parse_header_kv(mext.group(1))
                rid, path = kv.get("id"), kv.get("path")
                if rid and path:
                    ext_id_to_path[str(rid)] = path
                continue

            flush()
            continue

        if cur_props is not None and "=" in line:
            k, v = line.split("=", 1)
            cur_props[k.strip()] = v.strip()

    flush()

    if not nodes:
        warnings.append("No [node ...] blocks found; file may not be a text .tscn or format is unexpected.")
        return None, warnings

    # Root node is the first node
    root_hdr, _ = nodes[0]
    root_name = root_hdr.get("name", "<ROOT>")
    root_type = root_hdr.get("type", "Node")
    root = SceneNode(name=root_name, type_name=root_type, parent_full=None, order=0)

    path_to_node: Dict[str, SceneNode] = {root_name: root}

    # Create all nodes with stable order from file
    for idx, (hdr, props) in enumerate(nodes):
        name = hdr.get("name", f"<unnamed_{idx}>")
        type_name = hdr.get("type", "Node")
        parent_raw = hdr.get("parent")

        if idx == 0:
            parent_full = None
            full_path = root_name
        else:
            parent_full = root_name if (not parent_raw or parent_raw == ".") else f"{root_name}/{parent_raw}"
            full_path = f"{parent_full}/{name}"

        script_path = parse_script_value(props["script"], ext_id_to_path) if "script" in props else None

        n = path_to_node.get(full_path)
        if n is None:
            path_to_node[full_path] = SceneNode(
                name=name,
                type_name=type_name,
                parent_full=parent_full,
                order=idx,
                script_path=script_path,
            )
        else:
            n.name = name
            n.type_name = type_name
            n.parent_full = parent_full
            n.order = idx
            n.script_path = script_path

    # Link children
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

    # Sort children by scene file order for stable output
    for n in path_to_node.values():
        n.children.sort(key=lambda c: c.order)

    return root, warnings


def render_scene_tree(root: SceneNode) -> str:
    out: List[str] = []

    def walk(n: SceneNode, indent: int) -> None:
        pad = "  " * indent
        sl = n.script_label()
        out.append(f"{pad}{n.name} ({n.type_name}) [{sl}]" if sl else f"{pad}{n.name} ({n.type_name})")
        for c in n.children:
            walk(c, indent + 1)

    walk(root, 0)
    return "\n".join(out)


# -------------------------
# Collect files
# -------------------------
def collect_files(project_root: Path, exts: set[str]) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn in IGNORE_FILES or fn.startswith("."):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in exts:
                out.append(p)
    out.sort(key=lambda x: x.as_posix().casefold())
    return out


# -------------------------
# Report generation
# -------------------------
def generate_report(project_root: Path, output_md: Path) -> None:
    if not project_root.exists() or not project_root.is_dir():
        raise RuntimeError(f"Project root does not exist or is not a directory: {project_root}")

    now = dt.datetime.now().astimezone()
    scenes = collect_files(project_root, SCENE_EXTS)
    scripts = collect_files(project_root, {".gd"})

    md: List[str] = []
    md.append("# Godot Project Report\n")
    md.append(f"- Generated at: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    md.append(f"- Project root (as res://): `{project_root.as_posix()}`")
    md.append(f"- Scenes: {len(scenes)}")
    md.append(f"- Scripts: {len(scripts)}\n")

    # 1) File tree
    md.append("## 1. File Tree\n")
    tree = build_file_tree(project_root)
    md.append(fenced(tree, "text"))

    # 2) Scene node trees
    md.append("## 2. Scene Node Trees (with attached scripts)\n")
    for sp in scenes:
        md.append(f"### <Scene> {sp.name}\n")
        md.append(f"{to_res_path(project_root, sp)}\n")

        root, warnings = parse_tscn(sp)
        if not root:
            md.append("> Failed to parse this scene.\n")
            for w in warnings:
                md.append(f"> - {w}")
            md.append("")
            continue

        scene_tree = render_scene_tree(root)
        md.append(fenced(scene_tree, "text"))

        if warnings:
            md.append("> Warnings:")
            for w in warnings:
                md.append(f"> - {w}")
            md.append("")

    # 3) Script contents
    md.append("## 3. GDScript Files\n")
    for gp in scripts:
        content = read_text(gp).rstrip("\n")
        md.append(f"### <Script> {gp.name}\n")
        md.append(f"{to_res_path(project_root, gp)}\n")
        md.append(fenced(content, "gdscript"))

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(md).replace("\r\n", "\n"), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a single Markdown report for a Godot project (.tscn + .gd). "
                    "CLI options override the hard-coded defaults."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Godot project root directory (treated as res://). Overrides PROJECT_ROOT.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output Markdown path. Overrides OUTPUT_MD.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT
    output_md = Path(args.output).resolve() if args.output else OUTPUT_MD

    generate_report(project_root, output_md)
    print(f"✅ Report written to: {output_md}")
