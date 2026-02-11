````md
# godot-project-report

A lightweight Python script that scans a Godot project folder and generates a single Markdown report.  
It is intended to produce an AI-friendly “context dump” for review, documentation, or sharing.

## What it generates

One Markdown file containing:

- Project file tree (`res://`)
- Scene node trees for `.tscn` files (node name, type, attached script if present)
- Persisted scene signal connections from `.tscn` (`[connection ...]`)
- Best-effort hints from scripts:
  - `class_name` registry
  - `@export*` variables (pattern-based)
  - `signal` declarations
  - heuristic `connect()` call detection
- Best-effort dependency views:
  - script→script dependency edges (derived from detected references)
  - resource usage reverse index (who references what)
  - unused resource list (heuristic; excludes some editor “recent/last opened” references)
- Input Map from `project.godot` `[input]` section (when present)

## Limitations (important)

- Static analysis only — runtime/dynamic loads may not be detected.
- Parses text formats only:
  - supported: `.tscn`, `.tres`, `.gd`
  - not supported: binary `.scn`, `.res`
- `uid://...` references are preserved but not resolved to a filesystem path.
- Input Map output depends on what is stored in `project.godot`. If `[input]` is missing, actions/events may not be available to parse.
- “Unused resources” is best-effort and can produce false positives/negatives depending on project style.

## Requirements

- Python 3.9+
- A Godot project directory containing `project.godot`

## Usage

1) Edit the config block near the top of `report.py`:

```python
PROJECT_ROOT = Path(r"C:\path\to\your\godot-project").resolve()
OUTPUT_MD = (PROJECT_ROOT / "project_report.md").resolve()
INCLUDE_SCRIPT_CONTENTS = True
````

2. Run:

```bash
python report.py
```

The report will be written to `OUTPUT_MD`.

## Example

See `example/sample_output.md`.

## License

MIT

## Disclaimer

This is an independent community tool and is not affiliated with or endorsed by the Godot Engine project.
Some parts of this project were developed with assistance from AI tools (e.g. ChatGPT).