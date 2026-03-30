# Compilers Course - Quarto Build System

.PHONY: all book book-html book-pdf slides slides-pdf slides-html publish clean

# Book targets
book: book-html book-pdf

book-html:
	cd content && uv run quarto render

book-pdf:
	cd content && uv run quarto render --to pdf

# Slides targets
slides: slides-html slides-pdf

slides-html:
	cd slides && for f in *.qmd; do uv run quarto render "$$f" --to revealjs; done

slides-pdf:
	cd slides && for f in *.qmd; do uv run quarto render "$$f" --to pdf; done

# Publish to GitHub Pages
publish:
	cd content && uv run quarto publish gh-pages

# All
all: book slides

# Clean
clean:
	rm -rf content/_book content/_freeze content/_site slides/_site slides/_freeze
