.PHONY: all pdf clean

all: main.pdf

main.pdf: main.tex
	latexmk -pdf main.tex

pdf:
	latexmk -pdf main.tex

clean:
	latexmk -C
