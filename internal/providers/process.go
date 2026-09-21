package providers

import (
	"io"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"time"
)

// No caller-controlled executable, argv or environment reaches this helper.
// In particular, host/outer-Codespace API keys are not inherited by providers.
func runtimeEnvironment() []string {
	env := []string{"HOME=/home/vibe", "USER=vibe", "LOGNAME=vibe", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8"}
	for _, key := range []string{"DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"} {
		if value := os.Getenv(key); value != "" {
			env = append(env, key+"="+value)
		}
	}
	return env
}

type childProcess struct {
	cmd  *exec.Cmd
	done chan struct{}
	once sync.Once
}

func startChild(binary string, args []string, dir string, extraEnv []string, stdio bool) (*childProcess, io.ReadCloser, io.WriteCloser, error) {
	cmd := exec.Command(binary, args...)
	cmd.Dir = dir
	cmd.Env = append(runtimeEnvironment(), extraEnv...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Stderr = io.Discard // Native diagnostics can contain prompts or auth URLs.
	var input io.ReadCloser
	var output io.WriteCloser
	var err error
	if stdio {
		input, err = cmd.StdoutPipe()
		if err != nil {
			return nil, nil, nil, ErrUnavailable
		}
		output, err = cmd.StdinPipe()
		if err != nil {
			input.Close()
			return nil, nil, nil, ErrUnavailable
		}
	} else {
		cmd.Stdout = io.Discard
	}
	if err = cmd.Start(); err != nil {
		if input != nil {
			input.Close()
			output.Close()
		}
		return nil, nil, nil, ErrUnavailable
	}
	p := &childProcess{cmd: cmd, done: make(chan struct{})}
	go func() { cmd.Wait(); close(p.done) }()
	return p, input, output, nil
}

func (p *childProcess) close() {
	p.once.Do(func() {
		// The group can outlive its leader. Terminate remaining children even
		// when the provider exited before its event stream was closed.
		syscall.Kill(-p.cmd.Process.Pid, syscall.SIGTERM)
		until := time.Now().Add(3 * time.Second)
		for syscall.Kill(-p.cmd.Process.Pid, 0) == nil && time.Now().Before(until) {
			time.Sleep(25 * time.Millisecond)
		}
		syscall.Kill(-p.cmd.Process.Pid, syscall.SIGKILL)
		<-p.done
	})
}
