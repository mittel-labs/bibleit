package main

import (
	"encoding/json"
	"errors"
	"fmt"
	bibleit "github.com/mittel-labs/bibleit/clients/go"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type config struct {
	Name, Transport, Endpoint string
	Identity, AccessToken     string
	implicit                  bool
}
type profile struct {
	Transport   string `json:"transport"`
	Endpoint    string `json:"endpoint"`
	Identity    string `json:"identity,omitempty"`
	AccessToken string `json:"access_token,omitempty"`
}
type profileStore struct {
	Version  int                `json:"version"`
	Active   string             `json:"active_profile"`
	Profiles map[string]profile `json:"profiles"`
}

var profileName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`)

func validateProfile(p profile) error {
	switch p.Transport {
	case "http":
		// Apply exactly the same endpoint validation as library requests.
		if _, err := bibleit.NewAuthClient(bibleit.AuthConfig{Endpoint: p.Endpoint}); err != nil {
			return err
		}
		endpoint, err := url.Parse(p.Endpoint)
		if err != nil || endpoint.Hostname() == "" {
			return errors.New("HTTP endpoint requires a hostname")
		}
		if port := endpoint.Port(); port != "" {
			n, err := strconv.Atoi(port)
			if err != nil || n < 1 || n > 65535 {
				return errors.New("HTTP endpoint port must be from 1 to 65535")
			}
		}
		if p.Identity != "" {
			return errors.New("HTTP profiles cannot contain an SSH identity")
		}
	case "ssh":
		host, port, err := net.SplitHostPort(p.Endpoint)
		n, parseErr := strconv.Atoi(port)
		if err != nil || parseErr != nil || n < 1 || n > 65535 || host == "" || strings.ContainsAny(host, " \t\r\n\x00/@") || strings.HasPrefix(host, "-") {
			return errors.New("SSH endpoint must be host:port with a port from 1 to 65535")
		}
		if p.AccessToken != "" {
			return errors.New("SSH profiles cannot contain a bearer token")
		}
	default:
		return errors.New("profile transport must be http or ssh")
	}
	if strings.ContainsAny(p.AccessToken, "\r\n\x00") {
		return errors.New("invalid profile credential")
	}
	return nil
}

func loadStore() (profileStore, bool, error) {
	data, err := os.ReadFile(configPath())
	if os.IsNotExist(err) {
		return profileStore{Version: 1, Active: "default", Profiles: map[string]profile{"default": {Transport: "http", Endpoint: defaultWebURL}}}, true, nil
	}
	if err != nil {
		return profileStore{}, false, err
	}
	var keys map[string]json.RawMessage
	if err = json.Unmarshal(data, &keys); err != nil || keys == nil {
		return profileStore{}, false, errors.New("invalid configuration JSON")
	}
	var store profileStore
	if _, versioned := keys["version"]; versioned {
		if err = json.Unmarshal(data, &store); err != nil {
			return store, false, errors.New("invalid profile configuration")
		}
		if store.Version != 1 {
			return store, false, errors.New("unsupported configuration version")
		}
	} else {
		// Bind legacy credentials to the original built-in server, never a new URL.
		if _, ok := keys["profiles"]; ok {
			return store, false, errors.New("profile configuration requires a version")
		}
		for key := range keys {
			if key != "identity" && key != "access_token" {
				return store, false, errors.New("unknown legacy configuration field")
			}
		}
		var legacy struct {
			Identity    string `json:"identity"`
			AccessToken string `json:"access_token"`
		}
		if err = json.Unmarshal(data, &legacy); err != nil {
			return store, false, errors.New("invalid legacy configuration")
		}
		p := profile{Transport: "ssh", Endpoint: defaultSSHServer, Identity: legacy.Identity}
		if legacy.AccessToken != "" {
			p = profile{Transport: "http", Endpoint: defaultWebURL, AccessToken: legacy.AccessToken}
		}
		store = profileStore{Version: 1, Active: "default", Profiles: map[string]profile{"default": p}}
	}
	if !profileName.MatchString(store.Active) {
		return store, false, errors.New("invalid active profile")
	}
	if _, ok := store.Profiles[store.Active]; !ok {
		return store, false, errors.New("active profile does not exist")
	}
	for name, p := range store.Profiles {
		if !profileName.MatchString(name) {
			return store, false, errors.New("invalid profile name")
		}
		if err := validateProfile(p); err != nil {
			return store, false, fmt.Errorf("invalid profile %s: %w", name, err)
		}
	}
	return store, false, nil
}
func loadConfig() (config, error) { return loadSelectedConfig("") }
func loadSelectedConfig(name string) (config, error) {
	store, implicit, err := loadStore()
	if err != nil {
		return config{}, err
	}
	if name == "" {
		name = store.Active
	}
	p, ok := store.Profiles[name]
	if !ok {
		return config{}, fmt.Errorf("profile %q does not exist", name)
	}
	return config{Name: name, Transport: p.Transport, Endpoint: p.Endpoint, Identity: p.Identity, AccessToken: p.AccessToken, implicit: implicit}, nil
}
func profileFor(c config) profile {
	transport, endpoint := c.Transport, c.Endpoint
	if transport == "" {
		transport = "ssh"
		if c.AccessToken != "" {
			transport = "http"
		}
	}
	if endpoint == "" {
		endpoint = defaultSSHServer
		if transport == "http" {
			endpoint = defaultWebURL
		}
	}
	return profile{Transport: transport, Endpoint: endpoint, Identity: c.Identity, AccessToken: c.AccessToken}
}
func saveConfig(c config) error {
	store, _, err := loadStore()
	if err != nil {
		return err
	}
	name := c.Name
	if name == "" {
		name = store.Active
	}
	next := profileFor(c)
	if err := validateProfile(next); err != nil {
		return err
	}
	if previous, ok := store.Profiles[name]; ok && (previous.Transport != next.Transport || previous.Endpoint != next.Endpoint) && previous.AccessToken != "" {
		return errors.New("cannot change a credential's bound endpoint; create another profile")
	}
	store.Profiles[name] = next
	return saveStore(store)
}
func saveStore(store profileStore) error {
	data, err := json.MarshalIndent(store, "", "  ")
	if err != nil {
		return err
	}
	path := configPath()
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".config-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if err = restrictConfigFile(file); err == nil {
		_, err = file.Write(append(data, '\n'))
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(file.Name(), path)
}
func profileCommand(args []string, format string) int {
	if len(args) == 0 {
		return help([]string{"profile"})
	}
	store, implicit, err := loadStore()
	if err != nil {
		return fail(exitFailure, "read profiles: %v", err)
	}
	switch args[0] {
	case "add":
		options, rest, err := parseOptions(args[1:], map[string]bool{"--endpoint": true, "--transport": true})
		if err != nil || len(rest) != 1 || options["--endpoint"] == "" {
			return fail(exitUsage, "usage: bibleit profile add <name> --endpoint <url|host:port> [--transport http|ssh]")
		}
		name := rest[0]
		if !profileName.MatchString(name) {
			return fail(exitUsage, "profile names must be 1–64 letters, digits, underscores or hyphens, starting with a letter or digit")
		}
		if _, exists := store.Profiles[name]; exists && !implicit {
			return fail(exitConflict, "profile already exists; use a new name to bind another endpoint")
		}
		transport := options["--transport"]
		if transport == "" {
			transport = "http"
		}
		p := profile{Transport: transport, Endpoint: strings.TrimRight(options["--endpoint"], "/")}
		if err := validateProfile(p); err != nil {
			return fail(exitUsage, "%v", err)
		}
		if implicit {
			store.Profiles = map[string]profile{}
			store.Active = name
		}
		store.Profiles[name] = p
		if err := saveStore(store); err != nil {
			return fail(exitFailure, "save profiles: %v", err)
		}
		return printLocal("profile", map[string]string{"name": name, "transport": p.Transport, "endpoint": p.Endpoint}, format)
	case "use":
		if len(args) != 2 {
			return fail(exitUsage, "usage: bibleit profile use <name>")
		}
		if _, ok := store.Profiles[args[1]]; !ok {
			return fail(exitNotFound, "profile does not exist")
		}
		store.Active = args[1]
		if err := saveStore(store); err != nil {
			return fail(exitFailure, "save profiles: %v", err)
		}
		return printLocal("profile", map[string]string{"name": store.Active, "active": "true"}, format)
	case "remove":
		if len(args) != 2 {
			return fail(exitUsage, "usage: bibleit profile remove <name>")
		}
		p, ok := store.Profiles[args[1]]
		if !ok {
			return fail(exitNotFound, "profile does not exist")
		}
		if p.AccessToken != "" {
			return fail(exitConflict, "log out of this profile before removing its cached credential")
		}
		if store.Active == args[1] {
			return fail(exitConflict, "select another active profile before removing this one")
		}
		delete(store.Profiles, args[1])
		if err := saveStore(store); err != nil {
			return fail(exitFailure, "save profiles: %v", err)
		}
		return printLocal("profile", map[string]string{"name": args[1], "removed": "true"}, format)
	case "list", "show":
		names := []string{}
		if args[0] == "show" {
			if len(args) > 2 {
				return fail(exitUsage, "usage: bibleit profile show [name]")
			}
			name := store.Active
			if len(args) == 2 {
				name = args[1]
			}
			if _, ok := store.Profiles[name]; !ok {
				return fail(exitNotFound, "profile does not exist")
			}
			names = append(names, name)
		} else {
			if len(args) != 1 {
				return fail(exitUsage, "usage: bibleit profile list")
			}
			for name := range store.Profiles {
				names = append(names, name)
			}
			sort.Strings(names)
		}
		records := []outputRecord{}
		for _, name := range names {
			p := store.Profiles[name]
			records = append(records, outputRecord{Type: "profile", Fields: map[string]string{"name": name, "transport": p.Transport, "endpoint": p.Endpoint, "active": strconv.FormatBool(name == store.Active), "credential_cached": strconv.FormatBool(p.AccessToken != ""), "identity": p.Identity}, order: []string{"name", "transport", "endpoint", "active", "credential_cached", "identity"}})
		}
		return printOutputRecords(records, format)
	default:
		return fail(exitUsage, "unknown profile command")
	}
}
