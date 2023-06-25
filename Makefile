.PHONY: run bump-version

run:
	@(cd src; python -m bibleit)

bump-version:
	@./bump-version.sh
