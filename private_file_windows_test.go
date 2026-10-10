package main

import (
	"bytes"
	"encoding/binary"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf16"
	"unicode/utf8"
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
	// icacls versions may emit UTF-16LE without a BOM. Accept UTF-8
	// as well; the security assertion below still inspects the actual DACL.
	data = bytes.TrimPrefix(data, []byte{0xff, 0xfe})
	data = bytes.TrimPrefix(data, []byte{0xef, 0xbb, 0xbf})
	var sddl string
	if !bytes.Contains(data, []byte{0}) && utf8.Valid(data) {
		sddl = string(data)
	} else {
		if len(data)%2 != 0 {
			t.Fatal("invalid UTF-16 ACL file length")
		}
		units := make([]uint16, len(data)/2)
		for i := range units {
			units[i] = binary.LittleEndian.Uint16(data[i*2:])
		}
		sddl = string(utf16.Decode(units))
	}
	current, err := user.Current()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(sddl, "(A;") != 1 || !strings.Contains(sddl, "(A;;FA;;;"+current.Uid+")") {
		t.Fatalf("config must grant full access only to current user; ACL: %s", sddl)
	}
}
