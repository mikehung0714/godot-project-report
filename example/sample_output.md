# Godot Project Report

- Generated at: 2026-02-11 00:00:00 國際標准時間
- Project root (as res://): `C:/Users/User/Documents/sample`
- Scenes: 1
- Scripts: 2

## 1. File Tree

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

## 2. Scene Node Trees (with attached scripts)

### <Scene> main.tscn

res:///main.tscn

~~~text
main (Node2D) [main.gd]
  CharacterBody2D (CharacterBody2D) [character_body_2d.gd]
    CollisionShape2D (CollisionShape2D)
~~~

## 3. GDScript Files

### <Script> character_body_2d.gd

res:///character_body_2d.gd

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

res:///main.gd

~~~gdscript
extends Node2D


# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	pass # Replace with function body.


# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	pass
~~~
