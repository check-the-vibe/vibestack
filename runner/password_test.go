package runner

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	api "github.com/check-the-vibe/vibestack/pkg/vibestack"
	"github.com/docker/docker/client"
)

func TestPasswordLifecycleAndHelperFailure(t *testing.T) {
	s, store := trustedServer(t)
	i := api.Instance{ID: strings.Repeat("c", 32), Name: "test", Owner: s.sharedPrincipal, ContainerID: "container", Ports: map[string]int{}, URLs: map[string]string{}, CreatedAt: nowISO(), UpdatedAt: nowISO()}
	if err := store.CreateInstance(context.Background(), i, "d", "p", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	if err := store.UpdateInstanceObserved(context.Background(), i.ID, "container", "running", "running", true, ""); err != nil {
		t.Fatal(err)
	}
	secret, _ := randomID()
	healthy := false
	calls := 0
	docker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/json") {
			status := "stopped"
			running := "false"
			if healthy {
				status = "healthy"
				running = "true"
			}
			io.WriteString(w, `{"Id":"container","Config":{"Labels":{"dev.vibestack.runner.managed":"true","dev.vibestack.runner.instance":"`+i.ID+`"}},"State":{"Running":`+running+`,"Health":{"Status":"`+status+`"}}}`)
		} else {
			body, _ := io.ReadAll(r.Body)
			if strings.Contains(string(body), secret) {
				t.Error("plaintext in Docker exec configuration")
			}
			w.WriteHeader(500)
			io.WriteString(w, `{"message":"`+secret+`"}`)
		}
	}))
	defer docker.Close()
	cli, err := client.NewClientWithOpts(client.WithHost(docker.URL), client.WithVersion("1.47"))
	if err != nil {
		t.Fatal(err)
	}
	defer cli.Close()
	m := &Manager{Config: s.Config, Store: store, Docker: cli}
	s.Manager = m
	lock := m.instanceLock(i.ID)
	lock.Lock()
	result := m.SetPassword(context.Background(), i, secret)
	lock.Unlock()
	if result == nil || result.Status != 409 || calls != 0 {
		t.Fatal("lifecycle lock not respected")
	}
	result = m.SetPassword(context.Background(), i, secret)
	if result == nil || result.Status != 409 {
		t.Fatal("stopped accepted")
	}
	healthy = true
	result = m.SetPassword(context.Background(), i, secret)
	if result == nil || result.Status != 502 || strings.Contains(result.Message, secret) {
		t.Fatalf("unsafe helper error %+v", result)
	}
}
