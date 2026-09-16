package runner

import (
	"strings"
	"testing"

	dockertypes "github.com/docker/docker/api/types"
)

func TestContainerHealthReadyRequiresVibeStackHealthContract(t *testing.T) {
	tests := []struct {
		name      string
		state     *dockertypes.ContainerState
		ready     bool
		errorText string
	}{
		{name: "healthy", state: &dockertypes.ContainerState{Running: true, Health: &dockertypes.Health{Status: "healthy"}}, ready: true},
		{name: "starting", state: &dockertypes.ContainerState{Running: true, Health: &dockertypes.Health{Status: "starting"}}},
		{name: "missing health", state: &dockertypes.ContainerState{Running: true}, errorText: "required health check"},
		{name: "restart loop", state: &dockertypes.ContainerState{Running: true, Restarting: true}, errorText: "restarted"},
		{name: "stopped", state: &dockertypes.ContainerState{}, errorText: "stopped"},
		{name: "unhealthy", state: &dockertypes.ContainerState{Running: true, Health: &dockertypes.Health{Status: "unhealthy"}}, errorText: "unhealthy"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			ready, err := containerHealthReady(test.state)
			if ready != test.ready {
				t.Fatalf("ready=%v, want %v", ready, test.ready)
			}
			if test.errorText == "" && err != nil {
				t.Fatal(err)
			}
			if test.errorText != "" && (err == nil || !strings.Contains(err.Error(), test.errorText)) {
				t.Fatalf("error=%v, want text %q", err, test.errorText)
			}
		})
	}
}
