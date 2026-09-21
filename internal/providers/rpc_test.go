package providers

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"
)

func rpcFixture(t *testing.T) (*rpcConn, *io.PipeReader, *io.PipeWriter) {
	t.Helper()
	in, serverOut := io.Pipe()
	serverIn, out := io.Pipe()
	c := newRPC(in, out)
	t.Cleanup(func() { c.stop(ErrDisconnected); serverIn.Close(); serverOut.Close() })
	return c, serverIn, serverOut
}

func deadline(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	t.Cleanup(cancel)
	return ctx
}

func TestRPCRepliesAreCorrelatedAndVendorErrorsStayPrivate(t *testing.T) {
	c, input, output := rpcFixture(t)
	go func() {
		scanner := bufio.NewScanner(input)
		for scanner.Scan() {
			var request struct {
				ID     uint64 `json:"id"`
				Method string `json:"method"`
			}
			if json.Unmarshal(scanner.Bytes(), &request) != nil {
				return
			}
			if request.Method == "denied" {
				fmt.Fprintf(output, "{\"id\":%d,\"error\":{\"message\":\"private fixture output\"}}\n", request.ID)
			} else {
				fmt.Fprintf(output, "{\"id\":%d,\"result\":{\"method\":%q}}\n", request.ID, request.Method)
			}
		}
	}()
	results := make(chan error, 8)
	for n := range 8 {
		go func() {
			method := fmt.Sprintf("fixture/%d", n)
			value, err := c.call(deadline(t), method, map[string]any{})
			if err == nil && string(value) != fmt.Sprintf("{\"method\":%q}", method) {
				err = errors.New("response crossed a request boundary")
			}
			results <- err
		}()
	}
	for range 8 {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
	_, err := c.call(deadline(t), "denied", nil)
	if !errors.Is(err, ErrRejected) || strings.Contains(err.Error(), "private fixture") {
		t.Fatal("raw provider diagnostics escaped")
	}
}

func TestRPCCancellationDoesNotResubmitOrAcceptALateReplyForAnotherRequest(t *testing.T) {
	c, input, output := rpcFixture(t)
	firstSeen := make(chan uint64, 1)
	secondSeen := make(chan uint64, 1)
	go func() {
		scanner := bufio.NewScanner(input)
		for n := 0; scanner.Scan(); n++ {
			var frame struct{ ID uint64 }
			if json.Unmarshal(scanner.Bytes(), &frame) != nil {
				return
			}
			if n == 0 {
				firstSeen <- frame.ID
			} else {
				secondSeen <- frame.ID
				return
			}
		}
	}()
	ctx, cancel := context.WithCancel(deadline(t))
	firstDone := make(chan error, 1)
	go func() { _, err := c.call(ctx, "turn/start", nil); firstDone <- err }()
	firstID := <-firstSeen
	cancel()
	if !errors.Is(<-firstDone, context.Canceled) {
		t.Fatal("cancellation did not return to caller")
	}
	secondDone := make(chan rpcReply, 1)
	go func() { v, err := c.call(deadline(t), "thread/read", nil); secondDone <- rpcReply{v, err} }()
	secondID := <-secondSeen
	if firstID == secondID {
		t.Fatal("request identifier was reused")
	}
	fmt.Fprintf(output, "{\"id\":%d,\"result\":{\"late\":true}}\n", firstID)
	fmt.Fprintf(output, "{\"id\":%d,\"result\":{\"current\":true}}\n", secondID)
	got := <-secondDone
	if got.err != nil || string(got.value) != `{"current":true}` {
		t.Fatal("late mutation reply crossed into the state request")
	}
}

func TestRPCPartialAndOversizedFramesFailClosed(t *testing.T) {
	for _, frame := range []string{`{"id":1,"result":{}}`, strings.Repeat("x", rpcFrameBytes+1) + "\n", "{invalid}\n", "{\"id\":\"" + strings.Repeat("x", 257) + "\",\"method\":\"approval\"}\n"} {
		c, _, output := rpcFixture(t)
		go func() { io.WriteString(output, frame); output.Close() }()
		select {
		case <-c.done:
			if !errors.Is(c.failure(), ErrProtocol) {
				t.Fatal("malformed frame did not produce a bounded protocol failure")
			}
		case <-deadline(t).Done():
			t.Fatal("malformed frame hung the adapter")
		}
	}
}

func TestRPCApprovalRequiresAnExplicitResponse(t *testing.T) {
	c, input, output := rpcFixture(t)
	id := json.RawMessage(`"approval-1"`)
	go fmt.Fprintf(output, "{\"id\":%s,\"method\":\"item/commandExecution/requestApproval\",\"params\":{\"threadId\":\"thread-a\"}}\n", id)
	var event wireEvent
	select {
	case event = <-c.events:
	case <-deadline(t).Done():
		t.Fatal("approval request was not delivered")
	}
	if string(event.ID) != string(id) || event.Method != "item/commandExecution/requestApproval" {
		t.Fatal("approval correlation was lost")
	}
	line := make(chan string, 1)
	go func() { value, _ := bufio.NewReader(input).ReadString('\n'); line <- value }()
	select {
	case <-line:
		t.Fatal("adapter automatically answered a native approval")
	default:
	}
	if err := c.respond(deadline(t), event.ID, map[string]string{"decision": "decline"}); err != nil {
		t.Fatal(err)
	}
	var response struct {
		ID     json.RawMessage           `json:"id"`
		Result struct{ Decision string } `json:"result"`
	}
	if json.Unmarshal([]byte(<-line), &response) != nil || string(response.ID) != string(id) || response.Result.Decision != "decline" {
		t.Fatal("explicit approval decision did not retain its native request ID")
	}
}

func TestRPCValidReplySurvivesImmediateEOF(t *testing.T) {
	for range 30 {
		c, input, output := rpcFixture(t)
		go func() {
			line, _ := bufio.NewReader(input).ReadString('\n')
			var request struct{ ID uint64 }
			json.Unmarshal([]byte(line), &request)
			fmt.Fprintf(output, "{\"id\":%d,\"result\":{\"accepted\":true}}\n", request.ID)
			output.Close()
		}()
		value, err := c.call(deadline(t), "fixture/read", nil)
		if err != nil || string(value) != `{"accepted":true}` {
			t.Fatal("complete reply was discarded when the process exited")
		}
	}
}
