# Tesserax Skill

Tesserax is a pure-Python library for rendering professional CS graphics as SVG. It's installed as an editable dependency from `vendor/tesserax`.

## Quick Start

```python
from tesserax import Canvas, Rect, Text
from tesserax.color import Colors

with Canvas() as c:
    Rect(100, 50, fill=Colors.LightBlue)
    Text("Hello", size=24)

c.fit()
c.display()  # In Jupyter
```

## Components for This Book

This project includes reusable diagram components in `source/tesserax_components.py`:

```python
import sys
import os
_root = os.path.abspath(os.path.join(".."))
sys.path.insert(0, _root)

from tesserax import Canvas
from source.tesserax_components import Pipeline, Tree, Lexer, Automaton
pipeline = Pipeline
tree = Tree
lexer = Lexer
automaton = Automaton
```

## Usage in Quarto

```python
#| echo: false
import sys
import os
_root = os.path.abspath(os.path.join(".."))
sys.path.insert(0, _root)

from tesserax import Canvas
from source.tesserax_components import Pipeline, Tree, Lexer, Automaton
pipeline = Pipeline
tree = Tree
lexer = Lexer
automaton = Automaton
```

Then in code blocks:

```python
# Pipeline
with Canvas() as canvas:
    pipeline(['HULK', 'Parser', 'MIPS'], [(0, 1, ""), (1, 2, "")])
canvas.fit(padding=20)
canvas.display()

# Tree
with Canvas() as canvas:
    tree("E", tree("T", tree("int")), tree("+", tree("int")))
canvas.fit(padding=20)
canvas.display()

# Lexer
with Canvas() as canvas:
    lexer(['if', '(', 'a', ')', 'b'])
canvas.fit(padding=20)
canvas.display()

# Automaton
with Canvas() as canvas:
    automaton('q0', ['q2'], {
        ('q0', 'a'): 'q1',
        ('q1', 'a'): 'q2',
        ('q0', 'b'): 'q0',
    })
canvas.fit(padding=20)
canvas.display()
```

## Core Concepts

### Canvas
- Container and viewport for all shapes
- Use `with canvas:` to add shapes
- `.fit(padding=10)` - auto-sizes canvas to content
- `.display()` - displays in Jupyter (for HTML output)

### Component Pattern (for reusable diagrams)

Components inherit from `Component` and implement `_build()`:

```python
from tesserax import Rect, Text, Group
from tesserax.core import Component

class MyDiagram(Component):
    def __init__(self, labels):
        super().__init__()
        self.labels = labels
    
    def _build(self) -> Group:
        with Group() as g:
            for label in self.labels:
                Rect(80, 40)
                Text(label, size=12)
        return g
```

### Basic Shapes
```python
from tesserax import Rect, Square, Circle, Text, Arrow, Polyline

Rect(width, height)
Square(size)
Circle(radius)
Text("label", size=14)
Arrow(start_point, end_point)
Polyline([points], marker_end="arrow")
```

### Colors
```python
from tesserax.color import Colors

Colors.LightBlue, Colors.DarkBlue
Colors.LightYellow, Colors.LightGreen
Colors.White, Colors.Black, Colors.DarkGray
```

## Layouts

### RowLayout
```python
from tesserax.layout import RowLayout

with RowLayout(gap=20) as row:
    Rect(60, 40)
    Rect(60, 40)
# row.shapes gives you access to created shapes
```

### HierarchicalLayout (Trees)
```python
from tesserax.layout import HierarchicalLayout

with HierarchicalLayout(orientation="vertical") as tree:
    root = Circle(25)
    left = Circle(20)
    tree.root(root)
    tree.connect(root, left)
```

## Alignment

```python
Text(label).align_to(shape, "center")
shape.anchor("top"), .anchor("bottom"), .anchor("left"), .anchor("right")
```

## Reference

- Source: `vendor/tesserax`
- Docs: https://apiad.github.io/tesserax
- Components: `source/tesserax_components.py`
- Playground: `.playground/`
