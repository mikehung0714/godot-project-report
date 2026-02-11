# Godot Project Context Report

- Generated at: 2026-02-11 18:17:55 台北標準時間
- Project root (as res://): `C:/Users/User/Documents/example`
- Scenes: 1
- Scripts: 2
- Text Resources (.tres): 0
- Resource files (for unused check): 4

## 0) Project Settings

- Main scene: ``
- Autoloads: (none detected)
- Editor auto/recent references (excluded from Unused): 4

## 0.1) Input Map (project.godot)

(No [input] section found.)

## 1) File Tree (res://)

~~~text
res://
  character_body_2d.gd
  character_body_2d.gd.uid
  icon.svg
  icon.svg.import
  main.gd
  main.gd.uid
  main.tscn
  project.godot
~~~

## 2) Scene Node Trees (with attached scripts)

### <Scene> main.tscn

`res:///main.tscn`

~~~text
main (Node2D) [main.gd]
  CharacterBody2D (CharacterBody2D) [character_body_2d.gd]
    CollisionShape2D (CollisionShape2D)
~~~

## 3) Script Registry (class_name / extends)

(No `class_name` found.)

## 4) Exported Variables (@export*)

(No `@export` variables found.)

## 5) Signal Mapping

### 5.1 Persisted scene connections (.tscn `[connection ...]`)

(No persisted `.tscn` connections found.)

### 5.2 Declared signals in scripts (`signal ...`)

(No `signal` declarations found.)

### 5.3 Potential code-based `connect()` calls (heuristic)

(No `connect()` patterns detected.)


## 6) Script Dependency Graph (best-effort)

(No script→script edges detected.)

## 7) Resource Usage Mapping (reverse index)

> `target` ← referenced by `sources` (best-effort)

<details><summary>Show usage map</summary>

~~~text
res:///character_body_2d.gd
  <- res:///main.tscn

res:///main.gd
  <- res:///main.tscn
~~~

</details>

## 8) Unused Resources (best-effort)

> Unused = not referenced by parsed scenes/scripts/tres, not main scene/autoload, and not in editor auto/recent references.

- Unused count: **1**

### .svg

~~~text
res:///icon.svg
~~~

## 9) Scripts (details)

### <Script> character_body_2d.gd

`res:///character_body_2d.gd`

- class_name: ``
- extends: `CharacterBody2D`
- referenced resources (strings): 0
- exported vars: 0
- declared signals: 0

~~~gdscript
extends CharacterBody2D


const SPEED = 300.0
const JUMP_VELOCITY = -400.0


func _physics_process(delta: float) -> void:
	# Add the gravity.
	if not is_on_floor():
		velocity += get_gravity() * delta

	# Handle jump.
	if Input.is_action_just_pressed("ui_accept") and is_on_floor():
		velocity.y = JUMP_VELOCITY

	# Get the input direction and handle the movement/deceleration.
	# As good practice, you should replace UI actions with custom gameplay actions.
	var direction := Input.get_axis("ui_left", "ui_right")
	if direction:
		velocity.x = direction * SPEED
	else:
		velocity.x = move_toward(velocity.x, 0, SPEED)

	move_and_slide()
~~~

### <Script> main.gd

`res:///main.gd`

- class_name: ``
- extends: `Node2D`
- referenced resources (strings): 0
- exported vars: 0
- declared signals: 0

~~~gdscript
extends Node2D


# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	pass # Replace with function body.


# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	pass
~~~

## 10) Caveats (static analysis limits)

- Dynamic loads (constructed paths, runtime resources) may not be detected.
- `uid://...` references are preserved but not resolved to filesystem paths here.
- Editor metadata files may contain personal/temporary paths; they are only used to avoid false 'unused' reports.
