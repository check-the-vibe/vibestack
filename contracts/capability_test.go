package contracts_test

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/google/jsonschema-go/jsonschema"
)

func readJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	if err := json.Unmarshal(b, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

func resolve(t *testing.T, value map[string]any) *jsonschema.Resolved {
	t.Helper()
	b, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	var schema jsonschema.Schema
	if err := json.Unmarshal(b, &schema); err != nil {
		t.Fatal(err)
	}
	rs, err := schema.Resolve(&jsonschema.ResolveOptions{ValidateDefaults: true})
	if err != nil {
		t.Fatal(err)
	}
	return rs
}

func TestExtensionDefinitionContract(t *testing.T) {
	schema := resolve(t, readJSON(t, "capability-definition-v1.schema.json"))
	example := "../docs/architecture/examples/project_summary.json"
	if err := schema.Validate(readJSON(t, example)); err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(map[string]any){
		"missing authorization": func(v map[string]any) { delete(v, "permission") },
		"unknown policy":        func(v map[string]any) { v["permission"] = "host" },
		"unsafe retry":          func(v map[string]any) { v["effect"] = "write" },
		"unbounded timeout":     func(v map[string]any) { v["timeout_ms"] = 300001 },
		"unbounded result":      func(v map[string]any) { v["response_bytes"] = 25165825 },
		"invalid identifier":    func(v map[string]any) { v["id"] = "../escape" },
		"reserved route":        func(v map[string]any) { v["rest"].(map[string]any)["path"] = "/auth" },
		"authentication bypass": func(v map[string]any) { v["anonymous"] = true },
		"runtime source URL":    func(v map[string]any) { v["handler_url"] = "https://example.com/module" },
	} {
		t.Run(name, func(t *testing.T) {
			v := readJSON(t, example)
			change(v)
			if err := schema.Validate(v); err == nil {
				t.Fatal("invalid definition accepted")
			}
		})
	}
}

func TestProjectSummaryInputAndOutput(t *testing.T) {
	v := readJSON(t, "../docs/architecture/examples/project_summary.json")
	input := resolve(t, v["input_schema"].(map[string]any))
	output := resolve(t, v["output_schema"].(map[string]any))
	if err := input.Validate(map[string]any{"project": "demo"}); err != nil {
		t.Fatal(err)
	}
	for _, body := range []map[string]any{
		{}, {"project": "../private"}, {"project": "/etc"}, {"project": ".."},
		{"project": "demo", "max_entries": 1001}, {"project": "demo", "max_entries": 0},
		{"project": "demo", "max_entries": 1.5}, {"project": "demo", "command": "id"},
	} {
		if err := input.Validate(body); err == nil {
			t.Errorf("accepted invalid input: %v", body)
		}
	}
	good := map[string]any{"project": "demo", "exists": true, "entry_count": 3, "truncated": false}
	if err := output.Validate(good); err != nil {
		t.Fatal(err)
	}
	good["entry_count"] = 1001
	if err := output.Validate(good); err == nil {
		t.Fatal("accepted unbounded result")
	}
	good["entry_count"] = 3
	good["private_path"] = "/data/credentials"
	if err := output.Validate(good); err == nil {
		t.Fatal("accepted undocumented result field")
	}
}
