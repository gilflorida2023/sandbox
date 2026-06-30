package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

const (
	ScoutPort         = ":8080"
	SessionsDir       = "/home/scout/projects/sandbox/scout/sessions"
	DefaultSessionTTL = 3600
	SessionCookieName = "scout_session"
)

type Session struct {
	ID         string         `json:"id"`
	Created    int64          `json:"created"`
	TTL        int            `json:"ttl"`
	LastAccess int64          `json:"last_access"`
	Data       map[string]any `json:"data"`
	mu         sync.Mutex
}

func (s *Session) IsExpired() bool {
	return time.Now().Unix() > s.LastAccess+int64(s.TTL)
}

func (s *Session) UpdateAccess() {
	s.mu.Lock()
	s.LastAccess = time.Now().Unix()
	s.mu.Unlock()
	s.persist()
}

func (s *Session) persist() {
	data, _ := json.Marshal(s)
	path := filepath.Join(SessionsDir, s.ID+".json")
	os.WriteFile(path, data, 0644)
}

type Event struct {
	Type      string `json:"type"`
	Timestamp int64  `json:"timestamp"`
	Data      any    `json:"data"`
}

type Server struct {
	sessions   map[string]*Session
	sessionsMu sync.RWMutex
	events     chan Event
	eventsMu   sync.Mutex
	clients    map[chan Event]bool
}

func main() {
	if err := os.MkdirAll(SessionsDir, 0755); err != nil {
		log.Fatalf("mkdir %s: %v", SessionsDir, err)
	}

	s := &Server{
		sessions: make(map[string]*Session),
		events:   make(chan Event, 100),
		clients:  make(map[chan Event]bool),
	}

	go s.cleanupSessions()
	go s.broadcastEvents()

	http.HandleFunc("/cgi-bin/", s.cgiHandler)
	http.HandleFunc("/status", s.statusHandler)
	http.HandleFunc("/events", s.eventsHandler)
	http.HandleFunc("/health", healthHandler)

	log.Printf("Scout CGI MCP server starting on %s", ScoutPort)
	log.Fatal(http.ListenAndServe(ScoutPort, nil))
}

func (s *Server) getSession(r *http.Request) (*Session, bool) {
	cookie, err := r.Cookie(SessionCookieName)
	if err != nil {
		return nil, false
	}

	s.sessionsMu.RLock()
	session, ok := s.sessions[cookie.Value]
	s.sessionsMu.RUnlock()

	if !ok || session.IsExpired() {
		return nil, false
	}

	session.UpdateAccess()
	return session, true
}

func (s *Server) createSession(ttl int) *Session {
	id := uuid.New().String()
	now := time.Now().Unix()
	session := &Session{
		ID:         id,
		Created:    now,
		TTL:        ttl,
		LastAccess: now,
		Data:       make(map[string]any),
	}

	s.sessionsMu.Lock()
	s.sessions[id] = session
	s.sessionsMu.Unlock()

	session.persist()
	return session
}

func (s *Server) cleanupSessions() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	for range ticker.C {
		s.sessionsMu.Lock()
		for id, session := range s.sessions {
			if session.IsExpired() {
				delete(s.sessions, id)
				os.Remove(filepath.Join(SessionsDir, id+".json"))
			}
		}
		s.sessionsMu.Unlock()
	}
}

func (s *Server) cgiHandler(w http.ResponseWriter, r *http.Request) {
	toolPath := strings.TrimPrefix(r.URL.Path, "/cgi-bin/")
	if toolPath == "" {
		http.Error(w, "Tool path required", http.StatusBadRequest)
		return
	}

	ttl := DefaultSessionTTL
	if h := r.Header.Get("X-Session-TTL"); h != "" {
		if v, err := strconv.Atoi(h); err == nil && v > 0 {
			ttl = v
		}
	}

	session, ok := s.getSession(r)
	if !ok {
		session = s.createSession(ttl)
		http.SetCookie(w, &http.Cookie{
			Name:     SessionCookieName,
			Value:    session.ID,
			Path:     "/",
			MaxAge:   ttl,
			HttpOnly: true,
			SameSite: http.SameSiteLaxMode,
		})
	} else {
		http.SetCookie(w, &http.Cookie{
			Name:     SessionCookieName,
			Value:    session.ID,
			Path:     "/",
			MaxAge:   session.TTL,
			HttpOnly: true,
			SameSite: http.SameSiteLaxMode,
		})
	}

	env := s.buildCGIEnv(r, session, toolPath)

	scriptPath := filepath.Join("/home/scout/projects/sandbox/scout/cgi-bin", toolPath)
	if _, err := os.Stat(scriptPath); os.IsNotExist(err) {
		http.Error(w, "Tool not found", http.StatusNotFound)
		return
	}

	if err := os.Chmod(scriptPath, 0755); err != nil {
		log.Printf("chmod %s: %v", scriptPath, err)
	}

	bodyBytes, _ := io.ReadAll(r.Body)

	cmd := exec.Command(scriptPath)
	cmd.Env = env
	cmd.Dir = filepath.Dir(scriptPath)
	cmd.Stdin = bytes.NewReader(bodyBytes)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		http.Error(w, "CGI stdout pipe failed", http.StatusInternalServerError)
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		http.Error(w, "CGI stderr pipe failed", http.StatusInternalServerError)
		return
	}

	if err := cmd.Start(); err != nil {
		http.Error(w, "CGI start failed", http.StatusInternalServerError)
		return
	}

	var stdoutData, stderrData []byte
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		stdoutData, _ = io.ReadAll(stdout)
	}()
	go func() {
		defer wg.Done()
		stderrData, _ = io.ReadAll(stderr)
	}()
	wg.Wait()
	cmd.Wait()

	w.Header().Set("Content-Type", "application/json")
	w.Write(stdoutData)

	if len(stderrData) > 0 {
		log.Printf("CGI stderr [%s]: %s", toolPath, string(stderrData))
	}

	s.emitEvent(Event{
		Type:      "cgi_call",
		Timestamp: time.Now().UnixMilli(),
		Data: map[string]any{
			"tool":     toolPath,
			"session":  session.ID,
			"method":   r.Method,
			"exitCode": cmd.ProcessState.ExitCode(),
		},
	})
}

func (s *Server) buildCGIEnv(r *http.Request, session *Session, toolPath string) []string {
	env := os.Environ()
	env = append(env,
		"SCOUT_SESSION_ID="+session.ID,
		"SCOUT_SESSION_TTL="+strconv.Itoa(session.TTL),
		"REQUEST_METHOD="+r.Method,
		"QUERY_STRING="+r.URL.RawQuery,
		"CONTENT_TYPE="+r.Header.Get("Content-Type"),
		"CONTENT_LENGTH="+r.Header.Get("Content-Length"),
		"HTTP_COOKIE="+r.Header.Get("Cookie"),
		"SCOUT_TOOL_PATH="+toolPath,
		"SCOUT_REMOTE_ADDR="+r.RemoteAddr,
	)
	return env
}

func (s *Server) statusHandler(w http.ResponseWriter, r *http.Request) {
	s.sessionsMu.RLock()
	activeSessions := len(s.sessions)
	s.sessionsMu.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"server_time":     time.Now().UnixMilli(),
		"active_sessions": activeSessions,
	})
}

func (s *Server) eventsHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming unsupported", http.StatusInternalServerError)
		return
	}

	clientChan := make(chan Event, 10)
	s.eventsMu.Lock()
	s.clients[clientChan] = true
	s.eventsMu.Unlock()

	ctx := r.Context()
	defer func() {
		s.eventsMu.Lock()
		delete(s.clients, clientChan)
		s.eventsMu.Unlock()
		close(clientChan)
	}()

	fmt.Fprintf(w, "data: %s\n\n", mustJSON(map[string]any{
		"type":      "connected",
		"timestamp": time.Now().UnixMilli(),
	}))
	flusher.Flush()

	for {
		select {
		case <-ctx.Done():
			return
		case event := <-clientChan:
			data := mustJSON(event)
			fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()
		}
	}
}

func (s *Server) broadcastEvents() {
	for event := range s.events {
		s.eventsMu.Lock()
		for ch := range s.clients {
			select {
			case ch <- event:
			default:
			}
		}
		s.eventsMu.Unlock()
	}
}

func (s *Server) emitEvent(event Event) {
	select {
	case s.events <- event:
	default:
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"service": "scout-cgi-mcp",
		"version": "1.0.0",
	})
}

func mustJSON(v any) string {
	data, _ := json.Marshal(v)
	return string(data)
}
