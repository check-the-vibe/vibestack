package capabilities

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"io"
	"os"
	"syscall"
)

//go:embed project_summary.json
var projectSummaryDefinition []byte

// Builtins is the explicit compiled extension list. Dependencies are supplied
// by the operator, never selected by a request, project file or URL.
func Builtins(projects *os.Root) []Registration {
	return []Registration{{Definition: projectSummaryDefinition, Handle: projectSummary(projects)}}
}

func projectSummary(projects *os.Root) Handler {
	return func(ctx context.Context, _ Principal, raw json.RawMessage) (any, error) {
		var input struct {
			Project    string `json:"project"`
			MaxEntries int    `json:"max_entries"`
		}
		if json.Unmarshal(raw, &input) != nil {
			return nil, Fail("invalid_input")
		}
		if input.MaxEntries == 0 {
			input.MaxEntries = 100
		}
		result := map[string]any{"project": input.Project, "exists": false, "entry_count": 0, "truncated": false}
		if projects == nil {
			return nil, Fail("unavailable")
		}
		// The validated project name is one path component. O_NOFOLLOW also closes
		// the lstat/open race; an attacker cannot swap in a link to another project.
		f, err := projects.OpenFile(input.Project, os.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
		if errors.Is(err, os.ErrNotExist) {
			return result, nil
		}
		if err != nil {
			return nil, Fail("not_found")
		}
		defer f.Close()
		if err := ctx.Err(); err != nil {
			return nil, Fail("cancelled")
		}
		names, err := f.Readdirnames(input.MaxEntries + 1)
		if err != nil && !errors.Is(err, io.EOF) {
			return nil, Fail("unavailable")
		}
		result["exists"] = true
		result["truncated"] = len(names) > input.MaxEntries
		if len(names) > input.MaxEntries {
			names = names[:input.MaxEntries]
		}
		result["entry_count"] = len(names)
		return result, nil
	}
}
