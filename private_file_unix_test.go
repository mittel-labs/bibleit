//go:build !windows

package main

import (
	"os"
	"testing"
)

func assertPrivateConfig(t *testing.T, path string) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("config mode is %o", info.Mode().Perm())
	}
}
