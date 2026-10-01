site:
	python -m http.server 8766 --directory docs

.PHONY: cli cli-test

cli:
	cd cli && go build ./...

cli-test:
	cd cli && go test ./...
