package main

import (
	"encoding/binary"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf16"
)

func assertPrivateConfig(t *testing.T, path string) {
	t.Helper()
	aclPath := filepath.Join(t.TempDir(), "acl.txt")
	out, err := exec.Command("icacls.exe", path, "/save", aclPath).CombinedOutput()
	if err != nil {
		t.Fatalf("read config ACL: %v %s", err, out)
	}
	data, err := os.ReadFile(aclPath)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) < 2 || data[0] != 0xff || data[1] != 0xfe || len(data)%2 != 0 {
		t.Fatal("unexpected icacls ACL file encoding")
	}
	units := make([]uint16, (len(data)-2)/2)
	for i := range units {
		units[i] = binary.LittleEndian.Uint16(data[2+i*2:])
	}
	sddl := string(utf16.Decode(units))
	current, err := user.Current()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(sddl, "(A;") != 1 || !strings.Contains(sddl, "(A;;FA;;;"+current.Uid+")") {
		t.Fatalf("config must grant full access only to current user; ACL: %s", sddl)
	}
}
