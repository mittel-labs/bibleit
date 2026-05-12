.PHONY: run repl bump-version lint fix-lint test build local-install-test FORCE

VENV_DIR:=.venv
VENV_ACTIVATE:=. $(VENV_DIR)/bin/activate
VENV_PY:=$(VENV_DIR)/bin/python
VENV_DEPS:=$(VENV_DIR)/.deps
PYTHON_BIN?=$(or \
	$(shell command -v python3.13 2>/dev/null),\
	$(shell command -v python3.12 2>/dev/null),\
	$(shell command -v python3.11 2>/dev/null),\
	$(shell command -v python3.10 2>/dev/null),\
	python3)
SOURCE_DIR:=src

$(VENV_DIR):
	$(PYTHON_BIN) -m venv $@

$(VENV_PY): $(VENV_DIR)
	@$(VENV_PY) -c "import sys" >/dev/null 2>&1 || rm -rf $(VENV_DIR)
	@test -x $(VENV_PY) || $(MAKE) $(VENV_DIR)

$(VENV_DEPS): $(VENV_PY) Makefile pyproject.toml FORCE
	@$(VENV_PY) -m pip show flake8 black requests textual textual-autocomplete unidecode build hatchling >/dev/null 2>&1 || \
		($(VENV_ACTIVATE) && pip install --upgrade pip && pip install flake8 black requests textual textual-autocomplete unidecode build hatchling)
	@touch $(VENV_DEPS)

install: $(VENV_DEPS)
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

lint: $(VENV_DEPS)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

fix-lint: $(VENV_DEPS)
	@$(VENV_ACTIVATE) && black $(SOURCE_DIR)

shell:
	@($(VENV_ACTIVATE) && cd $(SOURCE_DIR) && $(VENV_PY))

test: $(VENV_DEPS)
	$(VENV_PY) -m unittest discover src

build: $(VENV_DEPS)
	@rm -rf dist
	@$(VENV_ACTIVATE) && python -m build

local-install-test: build
	@set -e; \
	tmpdir=$$(mktemp -d); \
	$(VENV_PY) -m venv $$tmpdir/venv; \
	. $$tmpdir/venv/bin/activate; \
	pip install --upgrade pip >/dev/null; \
	pip install --no-deps dist/*.whl; \
	python -c "import bibleit._ffi as ffi; print('loaded', ffi._lib_name())"; \
	rm -rf $$tmpdir
