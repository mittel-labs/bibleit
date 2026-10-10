//go:build !windows

package main

import "os"

func restrictConfigFile(file *os.File) error { return file.Chmod(0600) }
