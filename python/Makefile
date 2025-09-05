.PHONY: run repl bump-version lint fix-lint test

VENV_DIR:=.venv
VENV_ACTIVATE:=source $(VENV_DIR)/bin/activate
VENV_PY:=$(VENV_DIR)/bin/python
PYTHON_BIN?=$(or \
	$(shell command -v python3.13 2>/dev/null),\
	$(shell command -v python3.12 2>/dev/null),\
	$(shell command -v python3.11 2>/dev/null),\
	$(shell command -v python3.10 2>/dev/null),\
	python3)
SOURCE_DIR:=src

$(VENV_DIR):
	$(PYTHON_BIN) -m venv $@
	$(VENV_ACTIVATE) && pip install --upgrade pip && pip install gnureadline flake8 black requests
	python -m venv $@

install: $(VENV_DIR)
	@$(VENV_ACTIVATE) && pip -v install '.[dev]'

clean-venv:
	@rm -rf $(VENV_DIR)

run:
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

bump-version:
	@./bump-version.sh
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

run-dev:
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual run --dev bibleit.app:Bibleit)

serve:
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual serve --dev "python -m bibleit")

lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

fix-lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && black $(SOURCE_DIR)

shell:
	@($(VENV_ACTIVATE) && cd $(SOURCE_DIR) && $(VENV_PY))

test:
	$(VENV_PY) -m unittest discover src
