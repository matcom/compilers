# Compilers Course - Quarto Build System

export QUARTO_TECH_PREVIEW=1

.PHONY: all book book-html book-pdf slides slides-pdf slides-html publish clean

# All
all: book slides

# Book targets
book: book-html book-pdf

book-html:
	cd content && uv run quarto render

book-pdf:
	cd content && uv run quarto render --to pdf

# Slides targets
slides: slides-pdf

slides-pdf:
	cd slides && for f in *.qmd; do uv run quarto render "$$f" --to beamer; done

# Publish to GitHub Pages
publish:
	cd content && uv run quarto publish gh-pages

# Clean
clean:
	rm -rf content/_book content/_freeze content/_site slides/_site slides/_freeze
