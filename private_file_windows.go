package main

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
)

// Windows mode bits do not restrict read access. Remove inherited grants on
// the newly created, still-empty file and grant only the current user's SID.
func restrictConfigFile(file *os.File) error {
	current, err := user.Current()
	if err != nil {
		return fmt.Errorf("identify config owner: %w", err)
	}
	output, err := exec.Command("icacls.exe", file.Name(), "/inheritance:r", "/grant:r", "*"+current.Uid+":F").CombinedOutput()
	if err != nil {
		return fmt.Errorf("restrict config ACL: %w (%s)", err, output)
	}
	return nil
}
