package main

import (
	"fmt"
	"os"
	"os/user"
	"syscall"
	"unsafe"
)

var (
	configSecurityAPI       = syscall.NewLazyDLL("advapi32.dll")
	convertConfigDescriptor = configSecurityAPI.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW")
	getConfigDACL           = configSecurityAPI.NewProc("GetSecurityDescriptorDacl")
	setConfigSecurity       = configSecurityAPI.NewProc("SetNamedSecurityInfoW")
	freeConfigDescriptor    = syscall.NewLazyDLL("kernel32.dll").NewProc("LocalFree")
)

// Replace the whole DACL on the still-empty temporary file. Removing inherited
// grants alone would leave explicit grants from the creation environment.
func restrictConfigFile(file *os.File) error {
	current, err := user.Current()
	if err != nil {
		return fmt.Errorf("identify config owner: %w", err)
	}
	sddl, err := syscall.UTF16PtrFromString("D:P(A;;FA;;;" + current.Uid + ")")
	if err != nil {
		return err
	}
	var descriptor uintptr
	ok, _, callErr := convertConfigDescriptor.Call(uintptr(unsafe.Pointer(sddl)), 1, uintptr(unsafe.Pointer(&descriptor)), 0)
	if ok == 0 {
		return fmt.Errorf("create private config DACL: %w", callErr)
	}
	defer freeConfigDescriptor.Call(descriptor)
	var acl uintptr
	var present, defaulted uint32
	ok, _, callErr = getConfigDACL.Call(descriptor, uintptr(unsafe.Pointer(&present)), uintptr(unsafe.Pointer(&acl)), uintptr(unsafe.Pointer(&defaulted)))
	if ok == 0 {
		return fmt.Errorf("read private config DACL: %w", callErr)
	}
	if present == 0 || acl == 0 {
		return fmt.Errorf("private config DACL is missing")
	}
	path, err := syscall.UTF16PtrFromString(file.Name())
	if err != nil {
		return err
	}
	const protectedDACL = 0x80000004                                                                    // PROTECTED_DACL_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
	code, _, _ := setConfigSecurity.Call(uintptr(unsafe.Pointer(path)), 1, protectedDACL, 0, 0, acl, 0) // SE_FILE_OBJECT
	if code != 0 {
		return fmt.Errorf("apply private config DACL: %w", syscall.Errno(code))
	}
	return nil
}
