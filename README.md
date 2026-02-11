# godot-project-report

A lightweight Python tool that analyzes a Godot project and generates
a single Markdown report containing:

- Full project file structure
- Scene node trees with attached scripts
- Full contents of all `.gd` scripts

This tool is designed to help with:
- Project documentation
- Code review
- Team onboarding
- Project auditing

It works with **Godot 4.x** text-based scenes (`.tscn`).

---

## Features

- Recursively scans a Godot project directory (`res://`)
- Outputs a **single Markdown file**
- Scene analysis includes:
  - Node hierarchy
  - Node types
  - Attached scripts (displayed as `[ScriptName.gd]`)
- Dumps all GDScript files with syntax highlighting
- No external dependencies (pure Python)

---

## Requirements

- Python 3.9+
- Godot project using text-based `.tscn` scenes

---

## Usage

### Option 1 — Command line (recommended)

```bash
python report.py --project-root "/path/to/godot/project" --output "project_report.md"
````

### Option 2 — Edit default paths

You can edit the default path values inside `report.py`:

```python
PROJECT_ROOT = Path("/path/to/your/godot/project")
OUTPUT_MD = PROJECT_ROOT / "project_report.md"
```

Then run:

```bash
python report.py
```

The report will be generated at the specified output path.

---

## Example Output

See [`example/sample_output.md`](example/sample_output.md) for a real
example of the generated Markdown report.

---

## Notes

* Parses `.tscn` (text-based) scenes directly without requiring the Godot Editor.
* Binary scene files (`.scn`) are not supported.
* Instanced sub-scenes are listed as nodes but their internal structure is not expanded.

---

## License

MIT License.

---

## Disclaimer

This is an independent community tool and is **not affiliated with or
endorsed by the Godot Engine project**.

Some parts of this project were developed with assistance from AI tools
such as ChatGPT.
