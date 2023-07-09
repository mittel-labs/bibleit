.PHONY: run bump-version lint fix-lint

run:
	@(cd src; python -m bibleit)

bump-version:
	@./bump-version.sh

lint:
	@flake8 --config=.flake8 .

fix-lint:
	black .
