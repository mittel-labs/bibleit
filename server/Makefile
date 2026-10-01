# Homebrew normally puts these on PATH. The fallback also works while its links
# are being refreshed during a macOS package upgrade; callers may override both.
ERLC ?= $(shell command -v erlc 2>/dev/null || printf '%s' /opt/homebrew/opt/erlang/lib/erlang/bin/erlc)
ERL ?= $(shell command -v erl 2>/dev/null || printf '%s' /opt/homebrew/opt/erlang/lib/erlang/bin/erl)
REBAR3 ?= $(shell if command -v rebar3 >/dev/null 2>&1; then command -v rebar3; elif test -x "$$HOME/.cache/rebar3/bin/rebar3"; then printf '%s' "$$HOME/.cache/rebar3/bin/rebar3"; fi)
NIF := priv/bibleit_translation_nif.so
LIB := ../libbibleit/libbibleit.a
LIB_INPUTS := $(shell find ../libbibleit/src ../libbibleit/include -type f | sort) ../libbibleit/Makefile
TLS_CERT := priv/local-cert.pem
TLS_KEY := priv/local-key.pem
SSH_PORT ?= 2222
SSH_SYSTEM_DIR := priv/ssh
ERL_ROOT := $(shell $(ERL) -noshell -eval 'io:format("~s", [code:root_dir()]), halt().')
DEPS_EBIN = $(wildcard _build/default/lib/*/ebin)
ERL_PATHS = $(foreach path,$(DEPS_EBIN),-pa $(path))
TEST_EBIN := _build/test/test_ebin
TEST_MODULES := bibleit_live_session_tests,bibleit_protocol_tests,bibleit_account_tests,bibleit_translation_integration_tests,bibleit_live_persistence_tests,bibleit_rate_limiter_tests,bibleit_tls_transport_tests,bibleit_ssh_channel_tests,bibleit_ssh_identity_tests,bibleit_http_session_tests,bibleit_email_account_tests

# Development uses the same environment-driven bootstrap as a release, but
# never silently promotes the developer's personal SSH key to server_admin.
# Supply BIBLEIT_BOOTSTRAP_PUBLIC_KEY explicitly when a fresh data directory
# needs its first administrator.
BIBLEIT_BOOTSTRAP_ACTOR ?= admin
BIBLEIT_SERVER_PORT ?= 7070
BIBLEIT_HTTP_PORT ?= 8080
BIBLEIT_DATA_DIR ?= $(CURDIR)/.data
export BIBLEIT_BOOTSTRAP_PUBLIC_KEY BIBLEIT_BOOTSTRAP_ACTOR BIBLEIT_SERVER_PORT BIBLEIT_HTTP_PORT BIBLEIT_DATA_DIR

UNAME_S := $(shell uname -s)
NIF_LDFLAGS := $(if $(filter Darwin,$(UNAME_S)),-dynamiclib -undefined dynamic_lookup,-shared)

.PHONY: install-rebar3 version deps rebar3 compile release nif resources test run run-tls shell cert ssh-host-key clean

install-rebar3:
	@BootstrapDir=$$(mktemp -d /tmp/bibleit-rebar3.XXXXXX) && \
		Bootstrap="$$BootstrapDir/rebar3" && \
		curl --fail --location --silent --show-error https://s3.amazonaws.com/rebar3/rebar3 -o "$$Bootstrap" && \
		chmod 0755 "$$Bootstrap" && \
		"$$Bootstrap" local install && \
		rm -f "$$Bootstrap" && rmdir "$$BootstrapDir"

version:
	@tr -d '[:space:]' < VERSION && printf '\n'

deps:
	@test -n "$(REBAR3)" || { echo "rebar3 is required; run 'make install-rebar3' or install it globally." >&2; exit 1; }
	$(REBAR3) tree

rebar3:
	@test -n "$(REBAR3)" || { echo "rebar3 is required; run 'make install-rebar3' or install it globally." >&2; exit 1; }
	@test -n "$(ARGS)" || { echo 'Usage: make rebar3 ARGS="<rebar3 command and options>"' >&2; exit 1; }
	$(REBAR3) $(ARGS)

nif: $(NIF)

resources: ../config/languages.json ../config/translations_books.json
	@mkdir -p priv/config
	cp ../config/languages.json ../config/translations_books.json priv/config/

compile:
	@test -n "$(REBAR3)" || { echo "rebar3 is required; run 'make install-rebar3' or install it globally." >&2; exit 1; }
	$(REBAR3) compile

release:
	@test -n "$(REBAR3)" || { echo "rebar3 is required; run 'make install-rebar3' or install it globally." >&2; exit 1; }
	$(REBAR3) as prod release

$(LIB): $(LIB_INPUTS)
	$(MAKE) -C ../libbibleit libbibleit.a

$(NIF): c_src/bibleit_translation_nif.c $(LIB)
	@mkdir -p priv
	$(CC) -I../libbibleit/include -I$(ERL_ROOT)/usr/include -std=c99 -Wall -Wextra -Werror -fPIC $(NIF_LDFLAGS) -o $(NIF) c_src/bibleit_translation_nif.c ../libbibleit/libbibleit.a

test: compile
	@mkdir -p $(TEST_EBIN)
	$(ERLC) -Werror $(ERL_PATHS) -o $(TEST_EBIN) $(shell find test -type f -name '*.erl' | sort)
	$(ERL) -noshell $(ERL_PATHS) -pa $(TEST_EBIN) -eval 'case eunit:test([$(TEST_MODULES)], [verbose]) of ok -> halt(0); _ -> halt(1) end.'

run: ssh-host-key compile
	BIBLEIT_SSH_PORT=$(SSH_PORT) BIBLEIT_SSH_SYSTEM_DIR=$(SSH_SYSTEM_DIR) $(ERL) -noshell $(ERL_PATHS) -eval 'bibleit_server_boot:start().'

run-tls: cert ssh-host-key compile
	BIBLEIT_SSH_PORT=$(SSH_PORT) BIBLEIT_SSH_SYSTEM_DIR=$(SSH_SYSTEM_DIR) $(ERL) -noshell $(ERL_PATHS) -eval 'application:set_env(bibleit_server, tls, #{port => 7443, certfile => "$(TLS_CERT)", keyfile => "$(TLS_KEY)", handshake_timeout_ms => 10000}), bibleit_server_boot:start().'

shell: compile
	$(ERL) $(ERL_PATHS)

cert:
	@mkdir -p priv
	@if test -f $(TLS_CERT) && test -f $(TLS_KEY); then \
		echo "Development TLS certificate already exists: $(TLS_CERT)"; \
	elif test -e $(TLS_CERT) || test -e $(TLS_KEY); then \
		echo "Refusing to replace a partial TLS certificate pair in priv/." >&2; \
		exit 1; \
	else \
		openssl req -x509 -newkey rsa:2048 -nodes -keyout $(TLS_KEY) -out $(TLS_CERT) -days 7 -subj '/CN=localhost'; \
	fi

ssh-host-key:
	@mkdir -p $(SSH_SYSTEM_DIR)
	@if test -f $(SSH_SYSTEM_DIR)/ssh_host_ed25519_key; then \
		echo "Development SSH host key already exists: $(SSH_SYSTEM_DIR)/ssh_host_ed25519_key"; \
	elif test -e $(SSH_SYSTEM_DIR)/ssh_host_ed25519_key || test -e $(SSH_SYSTEM_DIR)/ssh_host_ed25519_key.pub; then \
		echo "Refusing to replace a partial SSH host-key pair in $(SSH_SYSTEM_DIR)." >&2; \
		exit 1; \
	else \
		ssh-keygen -q -t ed25519 -N '' -f $(SSH_SYSTEM_DIR)/ssh_host_ed25519_key; \
	fi

clean:
	@test -n "$(REBAR3)" || { echo "rebar3 is required; run 'make install-rebar3' or install it globally." >&2; exit 1; }
	$(REBAR3) clean
	rm -rf ebin $(NIF) $(TEST_EBIN)
