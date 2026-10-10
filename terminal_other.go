//go:build !darwin && !linux && !windows

package main

import "os"

func terminalInput(file *os.File) bool { return false }
