# AGENTS.md - Compilers Course Repository

## Project Overview

This is a course materials repository for an Introduction to Compiler Construction course.
The project contains lecture notes, slides, and Python source code for generating diagrams.
Content is written in `.qmd` (Quarto markdown) format and compiled to PDF/HTML using Quarto.

---

## Build Commands

### Main Build
```bash
make                    # Build everything: book (HTML + PDF) and slides
make all               # Same as make
make book             # Build book only (HTML + PDF)
make book-html        # Build book HTML
make book-pdf         # Build book PDF
make slides           # Build slides (HTML + PDF)
make slides-html      # Build slides HTML (reveal.js)
make slides-pdf       # Build slides PDF
```

### Direct Quarto Commands
```bash
# Book (content directory)
cd content && quarto render          # All formats
cd content && quarto render --to html
cd content && quarto render --to pdf

# Slides (slides directory)
cd slides && quarto render 00-intro.qmd --to revealjs    # HTML slides
cd slides && quarto render 00-intro.qmd --to pdf         # PDF
```

### Publishing to GitHub Pages
```bash
make publish           # Publish book to gh-pages (https://matcom.github.io/compilers)
```

### Clean
```bash
make clean          # Remove build artifacts
```

---

## Dependencies

Python packages are managed with `uv`:

```bash
uv venv
uv pip install pydot nbformat nbclient jupyter
```

System dependencies:
- **quarto** - Document processor (https://quarto.org)
- **xelatex** - LaTeX engine (for PDF output, install via TeX Live)
- **graphviz** - Graph rendering (for diagrams - currently disabled)

---

## Directory Structure

```
/
├── makefile                    # Simple make targets
├── pyproject.toml              # Python dependencies (uv)
├── content/                    # Book chapters
│   ├── _quarto.yml            # Book configuration
│   ├── index.qmd              # Book index/home
│   └── chap*.qmd              # Chapter files (9 chapters)
├── slides/                     # Slide presentations
│   ├── _quarto.yml            # Slides configuration
│   └── *.qmd                  # Slide files (13 presentations)
├── source/                     # Python diagram generation (disabled)
│   ├── __init__.py
│   ├── base.py                # Base Graph class
│   ├── automata.py            # Automaton visualization
│   ├── trees.py               # Tree visualization
│   └── diagrams.py            # Pipeline, Lexer diagrams
├── graphics/                   # Static SVG images
├── notebooks/                  # Jupyter notebooks
└── filters/                    # OLD - pandoc filters (deprecated)
```

---

## Code Style Guidelines

### Python (source/ package)
- All Python files must start with `# coding: utf8`
- Use relative imports within packages (e.g., `from .base import Graph`)

### Naming Conventions
```python
Classes: PascalCase
    class Automaton(Graph): ...

Functions/Methods: snake_case
    def graph(self): ...

Variables: snake_case
    self.start = start
```

### Diagrams (TEMPORARILY DISABLED)
The diagram generation system (`source/`) is currently disabled due to graphviz
unavailability. To re-enable:
1. Install graphviz: `sudo pacman -S graphviz` (Arch) or `sudo apt install graphviz`
2. Enable execution in `_quarto.yml`: set `execute: enabled: true`
3. Add setup block with imports to each .qmd file

---

## Quarto Content Format

### Book Chapters (.qmd)
```markdown
---
title: "Chapter Title"
---

# Chapter Title

Content with **markdown** formatting.

```{python}
#| echo: false
#| output: asis
# Diagram code here (when re-enabled)
```
```

### Slides (.qmd)
Each slide file needs a YAML header:
```markdown
---
title: "Slide Title"
format: revealjs
---

# Slide Title

## Section 1

Content for this slide.

:::{.notes}
Speaker notes go here (optional)
:::
```

Slide features:
- `##` headings create new slides
- `. . .` creates pauses/animations
- `:::{.notes}` for speaker notes
- `--` for slide separators

---

## Python Package (source/)

The `source/` package provides graph/diagram generation using pydot:

```python
from source.trees import Tree
from source.diagrams import Pipeline, Lexer
from source.automata import Automaton

# Generate diagrams (when graphviz is available)
Tree("IF", Tree("a"), Tree("b")).print()
Pipeline(['A', 'B', 'C'], [(0, 1, "x"), (1, 2, "y")]).print()
```

Classes:
- `Graph` - Base class in `source/base.py`
- `Tree` - Tree visualization in `source/trees.py`
- `Pipeline` - Pipeline diagram in `source/diagrams.py`
- `Lexer` - Lexer visualization in `source/diagrams.py`
- `Automaton` - Automaton visualization in `source/automata.py`

---

## Notes

- Diagrams are currently disabled (no graphviz). See "Diagrams (TEMPORARILY DISABLED)" above.
- Build outputs go to `content/_book/` and `slides/_site/`.
