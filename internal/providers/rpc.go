// Package providers adapts private, in-container agent runtimes. It does not
// expose a listener or make authorization decisions for external clients.
package providers

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"sync"
	"unicode/utf8"
)

var (
	ErrDisconnected = errors.New("provider connection ended; inspect the existing turn before retrying")
	ErrProtocol     = errors.New("provider protocol is incompatible or exceeded its limits")
	ErrRejected     = errors.New("provider rejected the request")
	ErrBusy         = errors.New("provider request capacity is full")
)

const (
	rpcFrameBytes   = 4 << 20
	rpcRequestBytes = 128 << 10
	rpcPendingLimit = 16
)

// wireEvent is private adapter input, never an external API response. Native
// authentication events and unknown payload fields must not be forwarded raw.
type wireEvent struct {
	ID     json.RawMessage
	Method string
	Params json.RawMessage
}

type rpcReply struct {
	value json.RawMessage
	err   error
}

type rpcWrite struct {
	ctx   context.Context
	frame []byte
	done  chan error
}

// rpcConn owns one JSONL stream. It never retries requests, automatically
// approves server requests, or treats loss of a reply as cancellation of work.
type rpcConn struct {
	in      io.ReadCloser
	out     io.WriteCloser
	mu      sync.Mutex
	next    uint64
	pending map[uint64]chan rpcReply
	writes  chan rpcWrite
	events  chan wireEvent
	done    chan struct{}
	once    sync.Once
	err     error
}

func newRPC(in io.ReadCloser, out io.WriteCloser) *rpcConn {
	c := &rpcConn{in: in, out: out, pending: make(map[uint64]chan rpcReply),
		writes: make(chan rpcWrite, rpcPendingLimit), events: make(chan wireEvent, 64), done: make(chan struct{})}
	go c.readLoop()
	go c.writeLoop()
	return c
}

func (c *rpcConn) stop(err error) {
	c.once.Do(func() {
		c.mu.Lock()
		c.err = err
		c.mu.Unlock()
		close(c.done)
		c.in.Close()
		c.out.Close()
	})
}

func (c *rpcConn) failure() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.err != nil {
		return c.err
	}
	return ErrDisconnected
}

func (c *rpcConn) call(ctx context.Context, method string, params any) (json.RawMessage, error) {
	c.mu.Lock()
	if c.err != nil {
		err := c.err
		c.mu.Unlock()
		return nil, err
	}
	if len(c.pending) >= rpcPendingLimit {
		c.mu.Unlock()
		return nil, ErrBusy
	}
	c.next++
	id := c.next
	reply := make(chan rpcReply, 1)
	c.pending[id] = reply
	c.mu.Unlock()
	defer func() { c.mu.Lock(); delete(c.pending, id); c.mu.Unlock() }()
	if err := c.send(ctx, map[string]any{"id": id, "method": method, "params": params}); err != nil {
		select {
		case value := <-reply:
			return value.value, value.err
		default:
			return nil, err
		}
	}
	select {
	case value := <-reply:
		return value.value, value.err
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-c.done:
		// A fully received reply remains valid if EOF follows immediately.
		select {
		case value := <-reply:
			return value.value, value.err
		default:
			return nil, c.failure()
		}
	}
}

func (c *rpcConn) notify(ctx context.Context, method string, params any) error {
	return c.send(ctx, map[string]any{"method": method, "params": params})
}

func (c *rpcConn) respond(ctx context.Context, id json.RawMessage, result any) error {
	if !validRPCID(id) {
		return ErrProtocol
	}
	return c.send(ctx, map[string]any{"id": id, "result": result})
}

func (c *rpcConn) rejectUnsupported(ctx context.Context, id json.RawMessage) error {
	if !validRPCID(id) {
		return ErrProtocol
	}
	return c.send(ctx, map[string]any{"id": id, "error": map[string]any{"code": -32601, "message": "This provider request is not supported by the VibeStack adapter."}})
}

func validRPCID(id json.RawMessage) bool {
	if len(id) == 0 || len(id) > 256 || !utf8.Valid(id) {
		return false
	}
	var value any
	decoder := json.NewDecoder(bytes.NewReader(id))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil {
		return false
	}
	switch value.(type) {
	case string, json.Number:
		encoded, err := json.Marshal(value)
		return err == nil && len(encoded) <= 256 && decoder.Decode(&value) == io.EOF
	default:
		return false
	}
}

func (c *rpcConn) send(ctx context.Context, value any) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	frame, err := json.Marshal(value)
	if err != nil || len(frame) > rpcRequestBytes {
		return ErrProtocol
	}
	packet := rpcWrite{ctx: ctx, frame: append(frame, '\n'), done: make(chan error, 1)}
	select {
	case c.writes <- packet:
	case <-ctx.Done():
		return ctx.Err()
	case <-c.done:
		return c.failure()
	}
	select {
	case err := <-packet.done:
		return err
	case <-ctx.Done():
		return ctx.Err()
	case <-c.done:
		return c.failure()
	}
}

func (c *rpcConn) writeLoop() {
	for {
		select {
		case <-c.done:
			return
		case packet := <-c.writes:
			if err := packet.ctx.Err(); err != nil {
				packet.done <- err
				continue
			}
			// A blocked OS pipe does not block caller cancellation. There is one
			// bounded writer; closing the process/connection releases it. A write
			// already in progress can have an uncertain remote outcome.
			n, err := c.out.Write(packet.frame)
			if err != nil || n != len(packet.frame) {
				c.stop(ErrDisconnected)
				packet.done <- ErrDisconnected
				return
			}
			packet.done <- nil
		}
	}
}

func (c *rpcConn) readLoop() {
	defer close(c.events)
	scanner := bufio.NewScanner(c.in)
	scanner.Buffer(make([]byte, 64<<10), rpcFrameBytes+1)
	scanner.Split(func(data []byte, atEOF bool) (int, []byte, error) {
		if i := bytes.IndexByte(data, '\n'); i >= 0 {
			return i + 1, data[:i], nil
		}
		if atEOF && len(data) != 0 {
			return 0, nil, io.ErrUnexpectedEOF
		}
		return 0, nil, nil
	})
	for scanner.Scan() {
		frame := scanner.Bytes()
		if len(frame) > rpcFrameBytes || !utf8.Valid(frame) {
			c.stop(ErrProtocol)
			return
		}
		var value struct {
			ID     json.RawMessage `json:"id"`
			Method string          `json:"method"`
			Params json.RawMessage `json:"params"`
			Result json.RawMessage `json:"result"`
			Error  json.RawMessage `json:"error"`
		}
		if json.Unmarshal(frame, &value) != nil || (len(value.ID) != 0 && !validRPCID(value.ID)) {
			c.stop(ErrProtocol)
			return
		}
		if value.Method != "" {
			if len(value.Method) > 128 || len(value.Result) != 0 || len(value.Error) != 0 {
				c.stop(ErrProtocol)
				return
			}
			select {
			case c.events <- wireEvent{ID: value.ID, Method: value.Method, Params: value.Params}:
			case <-c.done:
				return
			default:
				// Dropping approval or completion events would invent state.
				c.stop(ErrProtocol)
				return
			}
			continue
		}
		var id uint64
		if json.Unmarshal(value.ID, &id) != nil || (len(value.Result) == 0) == (len(value.Error) == 0) {
			c.stop(ErrProtocol)
			return
		}
		c.mu.Lock()
		reply := c.pending[id]
		delete(c.pending, id)
		c.mu.Unlock()
		if reply != nil {
			result := rpcReply{value: value.Result}
			if len(value.Error) != 0 {
				result = rpcReply{err: ErrRejected} // never surface raw vendor diagnostics
			}
			reply <- result
		}
	}
	if scanner.Err() != nil {
		c.stop(ErrProtocol)
	} else {
		c.stop(ErrDisconnected)
	}
}
