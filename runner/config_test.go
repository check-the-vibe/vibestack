package runner

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigRejectsUnknownFieldsAndTrailingValues(t *testing.T) {
	value := DefaultConfig()
	value.StateDir = filepath.Join(t.TempDir(), "state")
	valid, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range map[string][]byte{
		"unknown":  append(valid[:len(valid)-1], []byte(`,"surprise":true}`)...),
		"trailing": append(append([]byte{}, valid...), []byte(` {}`)...),
		"garbage":  append(append([]byte{}, valid...), []byte(` no`)...),
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "runner.json")
			if err := os.WriteFile(path, data, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := LoadConfig(path); err == nil {
				t.Fatal("invalid configuration was accepted")
			}
		})
	}
}

func TestLoadConfigPreservesPreviewDefaults(t *testing.T) {
	value := DefaultConfig()
	value.StateDir = filepath.Join(t.TempDir(), "state")
	value.MaxMemoryBytes = 0
	value.MaxNanoCPUs = 0
	value.MaxPIDs = 0
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "runner.json")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	defaults := DefaultConfig()
	if loaded.MaxMemoryBytes != defaults.MaxMemoryBytes || loaded.MaxNanoCPUs != defaults.MaxNanoCPUs || loaded.MaxPIDs != defaults.MaxPIDs {
		t.Fatalf("preview maxima were not restored: %#v", loaded)
	}
}
