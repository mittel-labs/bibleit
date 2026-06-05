.PHONY: run native native-clean repl bump-version lint fix-lint test build local-install-test FORCE

VENV_DIR:=.venv
VENV_ACTIVATE:=. $(VENV_DIR)/bin/activate
VENV_PY:=$(VENV_DIR)/bin/python
VENV_DEPS_FILE:=$(VENV_DIR)/.deps
VENV_DEPS:=aiohttp flake8 black rapidfuzz requests textual textual-dev textual-serve unidecode build hatchling
PYTHON_BIN?=$(or \
	$(shell command -v python3.11 2>/dev/null),\
	$(shell command -v python3.12 2>/dev/null),\
	$(shell command -v python3.13 2>/dev/null),\
	python3)
SOURCE_DIR:=src
LIBBIBLEIT_DIR:=$(abspath ../libbibleit)
NATIVE_DIR:=$(SOURCE_DIR)/bibleit/_native
UNAME_S:=$(shell uname -s)
ifeq ($(UNAME_S),Darwin)
NATIVE_LIB:=libbibleit.dylib
else
NATIVE_LIB:=libbibleit.so
endif
NATIVE_STAMP:=$(NATIVE_DIR)/$(NATIVE_LIB)
LIBBIBLEIT_SRCS:=$(wildcard $(LIBBIBLEIT_DIR)/src/*.c $(LIBBIBLEIT_DIR)/include/bibleit/*.h)

$(NATIVE_STAMP): $(LIBBIBLEIT_SRCS) $(LIBBIBLEIT_DIR)/Makefile
	@test -f $(LIBBIBLEIT_DIR)/Makefile || (echo "libbibleit not found at $(LIBBIBLEIT_DIR)" >&2; exit 1)
	$(MAKE) -C $(LIBBIBLEIT_DIR)
	@mkdir -p $(NATIVE_DIR)
	@touch $(NATIVE_DIR)/__init__.py
	cp -Lf $(LIBBIBLEIT_DIR)/$(NATIVE_LIB) $@
ifeq ($(UNAME_S),Darwin)
	@command -v codesign >/dev/null 2>&1 && codesign --force --sign - $@ || true
endif

native: $(NATIVE_STAMP)

native-clean:
	$(MAKE) -C $(LIBBIBLEIT_DIR) clean
	@rm -f $(NATIVE_DIR)/$(NATIVE_LIB) $(NATIVE_DIR)/libbibleit.so.*

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

run: $(VENV_DEPS_FILE) $(NATIVE_STAMP)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

serve: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit.serve)

live: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit.live)

bump-version:
	@./bump-version.sh
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); python -m bibleit)

run-dev: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual run --dev bibleit.app:Bibleit)

serve-dev: $(VENV_DEPS_FILE)
	$(VENV_ACTIVATE) && (cd $(SOURCE_DIR); textual serve --dev "python -m bibleit")

lint: $(VENV_DEPS_FILE)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

lint-fix: $(VENV_DEPS_FILE)
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
