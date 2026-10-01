site:
	python -m http.server 8766 --directory docs

.PHONY: cli cli-test cli-version versions

CLI_VERSION ?= $(shell tr -d '[:space:]' < cli/VERSION)
CLI_SSH_SERVER ?= 127.0.0.1:2222
CLI_WEB_URL ?= http://127.0.0.1:8080
CLI_LDFLAGS = -X main.cliVersion=$(CLI_VERSION) -X main.defaultSSHServer=$(CLI_SSH_SERVER) -X main.defaultWebURL=$(CLI_WEB_URL)

cli:
	cd cli && go build -ldflags "$(CLI_LDFLAGS)" .

cli-test:
	cd cli && go test ./...

cli-version:
	@tr -d '[:space:]' < cli/VERSION && printf '\n'

versions:
	@printf 'CLI:    ' && tr -d '[:space:]' < cli/VERSION && printf '\n'
