.PHONY: run repl bump-version lint fix-lint test build local-install-test FORCE

VENV_DIR:=.venv
VENV_ACTIVATE:=. $(VENV_DIR)/bin/activate
VENV_PY:=$(VENV_DIR)/bin/python
VENV_DEPS_FILE:=$(VENV_DIR)/.deps
VENV_DEPS:=flake8 black requests textual textual-autocomplete textual-dev unidecode build hatchling
PYTHON_BIN?=$(or \
	$(shell command -v python3.11 2>/dev/null),\
	$(shell command -v python3.12 2>/dev/null),\
	$(shell command -v python3.13 2>/dev/null),\
	python3)
SOURCE_DIR:=src

$(VENV_DIR):
	$(PYTHON_BIN) -m venv $@

$(VENV_PY): $(VENV_DIR)
	@$(VENV_PY) -c "import sys" >/dev/null 2>&1 || rm -rf $(VENV_DIR)
	@test -x $(VENV_PY) || $(MAKE) $(VENV_DIR)

$(VENV_DEPS_FILE): $(VENV_PY) Makefile pyproject.toml FORCE
	@$(VENV_PY) -m pip show $(VENV_DEPS) >/dev/null 2>&1 || ($(VENV_ACTIVATE) && pip install --upgrade pip && pip install $(VENV_DEPS))
	@touch $(VENV_DEPS_FILE)

install: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && pip -v install '.[dev]'

clean-venv:
	@rm -rf $(VENV_DIR)

run: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

serve: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit.serve)

bump-version:
	@./bump-version.sh
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

run-dev: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual run --dev bibleit.app:Bibleit)

serve-dev: $(VENV_DEPS_FILE)
	$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual serve --dev "python -m bibleit")

lint: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

fix-lint: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && black $(SOURCE_DIR)

shell:
	@($(VENV_ACTIVATE) && cd $(SOURCE_DIR) && $(VENV_PY))

test: $(VENV_DEPS_FILE)
	$(VENV_PY) -m unittest discover src

build: $(VENV_DEPS_FILE)
	@rm -rf dist
	@$(VENV_ACTIVATE) && python -m build

install-local: install build
	$(VENV_ACTIVATE) && pip install dist/*.whl
