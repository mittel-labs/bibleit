.PHONY: run bump-version lint fix-lint

VENV_DIR:=.venv
VENV_ACTIVATE:=source $(VENV_DIR)/bin/activate
SOURCE_DIR:=src

$(VENV_DIR):
	python -m venv $@
	$(VENV_ACTIVATE) && pip install flake8 black

clean-venv:
	@rm -rf $(VENV_DIR)

run:
	@(cd $(SOURCE_DIR); python -m bibleit)

bump-version:
	@./bump-version.sh

lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && flake8 --config=.flake8 $(SOURCE_DIR)

fix-lint: $(VENV_DIR)
	@$(VENV_ACTIVATE) && black $(SOURCE_DIR)

shell:
	@($(VENV_ACTIVATE) && cd $(SOURCE_DIR) && python)