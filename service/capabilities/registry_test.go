package capabilities

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

type grant struct{ allowed bool }

func (p grant) Allows(string, bool) bool { return p.allowed }
func definition(t *testing.T, changes func(map[string]any)) json.RawMessage {
	t.Helper()
	var d map[string]any
	if err := json.Unmarshal(projectSummaryDefinition, &d); err != nil {
		t.Fatal(err)
	}
	if changes != nil {
		changes(d)
	}
	b, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	return b
}
func validResult() any {
	return map[string]any{"project": "demo", "exists": true, "entry_count": 0, "truncated": false}
}
func registry(t *testing.T, definition json.RawMessage, handler Handler) *Registry {
	t.Helper()
	r, err := New([]Registration{{definition, handler}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestRegistrationFailsBeforeServing(t *testing.T) {
	handler := func(context.Context, Principal, json.RawMessage) (any, error) { return validResult(), nil }
	for name, change := range map[string]func(map[string]any){
		"remote schema":           func(d map[string]any) { d["input_schema"].(map[string]any)["$ref"] = "https://attacker.invalid/schema" },
		"invalid schema":          func(d map[string]any) { d["input_schema"].(map[string]any)["required"] = 42 },
		"reserved route":          func(d map[string]any) { d["rest"].(map[string]any)["path"] = "/api/v1/capabilities/steal" },
		"route wildcard":          func(d map[string]any) { d["rest"].(map[string]any)["path"] = "/api/v1/{everything}" },
		"missing unknown policy":  func(d map[string]any) { delete(d["input_schema"].(map[string]any), "additionalProperties") },
		"unbounded timeout":       func(d map[string]any) { d["timeout_ms"] = 300001 },
		"unsafe retry":            func(d map[string]any) { d["effect"] = "write" },
		"unbounded output fields": func(d map[string]any) { delete(d["output_schema"].(map[string]any), "additionalProperties") },
		"unknown nested fields": func(d map[string]any) {
			d["input_schema"].(map[string]any)["properties"].(map[string]any)["extra"] = map[string]any{"type": "object"}
		},
		"GET mutation": func(d map[string]any) {
			d["rest"].(map[string]any)["method"] = "GET"
			d["effect"] = "write"
			d["retry"] = "inspect-before-retry"
		},
		"unsupported query schema": func(d map[string]any) {
			d["rest"].(map[string]any)["method"] = "GET"
			d["input_schema"].(map[string]any)["properties"].(map[string]any)["project"] = map[string]any{"type": "array", "maxItems": 4}
		},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := New([]Registration{{definition(t, change), handler}}, nil, nil); err == nil {
				t.Fatal("invalid registration accepted")
			}
		})
	}
	d := definition(t, nil)
	for name, regs := range map[string][]Registration{
		"duplicate ID":    {{d, handler}, {d, handler}},
		"duplicate route": {{d, handler}, {definition(t, func(v map[string]any) { v["id"] = "another" }), handler}},
		"missing handler": {{d, nil}},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := New(regs, nil, nil); err == nil {
				t.Fatal("invalid registration accepted")
			}
		})
	}
	if _, err := New([]Registration{{d, handler}}, []string{"project_summary"}, nil); err == nil {
		t.Fatal("reserved ID accepted")
	}
	if _, err := New([]Registration{{d, handler}}, nil, []string{"POST /api/v1/{operation}"}); err == nil {
		t.Fatal("legacy wildcard shadow accepted")
	}
}

func TestDispatchValidationPermissionFailureAndPanic(t *testing.T) {
	var calls atomic.Int32
	r := registry(t, definition(t, nil), func(context.Context, Principal, json.RawMessage) (any, error) {
		calls.Add(1)
		return validResult(), nil
	})
	for _, input := range []string{`{}`, `{"project":"../secret"}`, `{"project":"demo","command":"secret"}`, `{"project":"demo","max_entries":0}`, `{"project":"demo"} trailing`} {
		if _, failure := r.Execute(context.Background(), grant{true}, "project_summary", []byte(input)); failure == nil || failure.Code != "invalid_input" {
			t.Fatal("invalid input reached handler")
		}
	}
	if _, f := r.Execute(context.Background(), grant{}, "project_summary", []byte(`{"project":"demo"}`)); f == nil || f.Code != "forbidden" {
		t.Fatal("denied grant executed")
	}
	if calls.Load() != 0 {
		t.Fatal("denied input had a side effect")
	}
	if result, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"demo"}`)); f != nil || !json.Valid(result) {
		t.Fatal("valid invocation failed")
	}
	if calls.Load() != 1 {
		t.Fatal("handler replayed")
	}
	for name, handler := range map[string]Handler{
		"panic": func(context.Context, Principal, json.RawMessage) (any, error) { panic("secret") },
		"error": func(context.Context, Principal, json.RawMessage) (any, error) { return nil, errors.New("secret") },
		"bad output": func(context.Context, Principal, json.RawMessage) (any, error) {
			return map[string]any{"secret": "private"}, nil
		},
	} {
		t.Run(name, func(t *testing.T) {
			r := registry(t, definition(t, nil), handler)
			result, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"demo"}`))
			if result != nil || f == nil || f.Code != "internal_error" || strings.Contains(f.Message(), "secret") {
				t.Fatal("unsafe failure")
			}
		})
	}
	r = registry(t, definition(t, func(d map[string]any) { d["response_bytes"] = 2 }), func(context.Context, Principal, json.RawMessage) (any, error) { return validResult(), nil })
	if _, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"demo"}`)); f == nil || f.Code != "limit_exceeded" {
		t.Fatal("result limit not enforced")
	}
}

func TestTimeoutKeepsCapacityUntilHandlerExitsAndNeverReplays(t *testing.T) {
	release := make(chan struct{})
	defer close(release)
	var calls atomic.Int32
	r := registry(t, definition(t, func(d map[string]any) { d["timeout_ms"] = 2 }), func(context.Context, Principal, json.RawMessage) (any, error) {
		calls.Add(1)
		<-release
		return validResult(), nil
	})
	for i := 0; i < 32; i++ {
		if _, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"demo"}`)); f == nil || f.Code != "timeout" {
			t.Fatal("handler deadline not enforced")
		}
	}
	if _, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"demo"}`)); f == nil || f.Code != "busy" || !f.Retryable() {
		t.Fatal("unbounded timed-out handlers")
	}
	if calls.Load() != 32 {
		t.Fatal("handler replayed or capacity exceeded")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, f := r.Execute(ctx, grant{true}, "project_summary", []byte(`{"project":"demo"}`)); f == nil || f.Code != "cancelled" {
		t.Fatal("cancelled request executed")
	}
}

func TestProjectSummaryUsesOnlyImmediateNonSymlinkProject(t *testing.T) {
	path := t.TempDir()
	if err := os.Mkdir(filepath.Join(path, "demo"), 0700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"a", "b", ".git"} {
		if err := os.WriteFile(filepath.Join(path, "demo", name), nil, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(t.TempDir(), filepath.Join(path, "escape")); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(path)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	r, err := New(Builtins(root), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		input     string
		exists    bool
		count     float64
		truncated bool
	}{
		{`{"project":"demo","max_entries":2}`, true, 2, true},
		{`{"project":"missing"}`, false, 0, false},
		{`{"project":"demo"}`, true, 3, false},
	} {
		raw, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(tc.input))
		if f != nil {
			t.Fatal(f)
		}
		var v map[string]any
		json.Unmarshal(raw, &v)
		if v["exists"] != tc.exists || v["entry_count"] != tc.count || v["truncated"] != tc.truncated {
			t.Fatal("incorrect bounded summary")
		}
	}
	if _, f := r.Execute(context.Background(), grant{true}, "project_summary", []byte(`{"project":"escape"}`)); f == nil || f.Code != "not_found" {
		t.Fatal("symlink project accepted")
	}
	reference, err := os.ReadFile("../../docs/architecture/examples/project_summary.json")
	if err != nil || !bytes.Equal(bytes.TrimSpace(reference), bytes.TrimSpace(projectSummaryDefinition)) {
		t.Fatal("published extension example drifted from registered definition")
	}
}
