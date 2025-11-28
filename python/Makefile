.PHONY: run repl bump-version lint fix-lint test

VENV_DIR:=.venv
VENV_ACTIVATE:=source $(VENV_DIR)/bin/activate
SOURCE_DIR:=src

$(VENV_DIR):
	python3 -m venv $@
	$(VENV_ACTIVATE) && pip install --upgrade pip && pip install gnureadline flake8 black

clean-venv:
	@rm -rf $(VENV_DIR)

run: ARGS?=--repl --bold
run:
	@(cd $(SOURCE_DIR); python -m bibleit $(ARGS))

repl: $(VENV_DIR)
	@$(VENV_ACTIVATE) && PYTHONPATH=$(SOURCE_DIR) python3 -m bibleit --repl

bump-version:
	@./bump-version.sh

lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

fix-lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && black $(SOURCE_DIR)

shell:
	@($(VENV_ACTIVATE) && cd $(SOURCE_DIR) && python)

test:
	python -m unittest discover src