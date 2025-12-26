// This is derived from
// https://gist.github.com/staaldraad/d835126cd46969330a8fdadba62b9b69

package main

import (
	"errors"
	"flag"
	"fmt"
	"golang.org/x/net/webdav"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"
)

var lock sync.RWMutex
var timeout time.Duration
var lastOp time.Time

func main() {

	baseHref, dir, bindAddr, timeout_i, err := parse()
	if err != nil {
		log.Fatalf("[PARSER] %w", err)
	}
	lastOp = time.Now()
	timeout = time.Duration(timeout_i)

	go reap()
	serve(baseHref, dir, bindAddr)
}

func parse() (string, string, string, int, error) {

	baseHrefE := "WORBLEHAT_BASE_HREF"
	dirE := "WORBLEHAT_DIR"
	portE := "WORBLEHAT_PORT"
	timeoutE := "WORBLEHAT_TIMEOUT"

	// If Go had either a ternary operator or let you treat empty strings
	// as false and non-empty strings as true, this would be less clunky.

	baseHrefV := os.Getenv(baseHrefE)
	dirV := os.Getenv(dirE)
	if dirV == "" {
		dirV = "./"
	}
	portVS := os.Getenv(portE)
	portV := 8000
	var err error
	if portVS != "" {
		if portV, err = strconv.Atoi(portVS); err != nil {
			errmsg := fmt.Sprintf("Could not convert port %s to integer.", portVS)
			return "", "", "", 0, errors.New(errmsg)
		}
	}
	timeoutVS := os.Getenv(timeoutE)
	timeoutV := 600
	if timeoutVS != "" {
		if timeoutV, err = strconv.Atoi(timeoutVS); err != nil {
			errmsg := fmt.Sprintf("Could not convert timeout %s to integer.", timeoutVS)
			return "", "", "", 0, errors.New(errmsg)
		}
	}

	baseHrefF := flag.String("b", baseHrefV, fmt.Sprintf("Base HREF [$%s:/].", baseHrefE))
	dirF := flag.String("d", dirV, fmt.Sprintf("Root of served directory tree [$%s:./].", dirE))
	portF := flag.Int("p", portV, fmt.Sprintf("Port to serve on [$%s:8000].", portE))
	timeoutF := flag.Int("t", timeoutV, fmt.Sprintf("Idle timeout in seconds [$%s:600].", timeoutE))

	flag.Parse()

	lastOp = time.Now()
	i_timeout := (int(1e9) * *timeoutF)
	bindAddr := fmt.Sprintf(":%d", *portF)

	baseHref := *baseHrefF
	dir := *dirF

	return baseHref, dir, bindAddr, i_timeout, nil
}

func reap() {
	// We rely on the global lastOp being updated by the route handler
	log.Printf("[REAPER] Starting with timeout %s", timeout)
	for {
		lock.RLock()
		since := time.Since(lastOp)
		lock.RUnlock()
		if since > timeout {
			// This is our normal exit, hence the zero return code
			log.Printf("[REAPER] No operations in %v; shutting down.", timeout)
			os.Exit(0)
		}
		time.Sleep(time.Second)
	}
}

func serve(baseHref string, dir string, bindAddr string) {
	log.Printf("[SERVER] Starting to serve %s at %s on %s", dir, bindAddr, baseHref)
	prefix := baseHref
	if prefix == "/" {
		prefix = ""
	}
	dav := &webdav.Handler{
		Prefix:     prefix,
		FileSystem: webdav.Dir(dir),
		LockSystem: webdav.NewMemLS(),
		Logger: func(r *http.Request, err error) {
			// We're totally abusing the logger here to update
			// the global lastOp, since it's called on every
			// request.

			// We do not count (or log) PROPFIND: on large
			// filesystems, it does a traversal of
			// everything, and tries to write ._<file>
			// properties files, and it's very spammy and
			// is unlikely to complete in a reasonable
			// time.

			if r.Method == "PROPFIND" {
				return
			}

			lock.Lock()
			lastOp = time.Now()
			lock.Unlock()
			// But we might as well log the action too.
			logmsg := fmt.Sprintf("[SERVER] %s %s", r.Method, r.URL)
			if err != nil {
				logmsg += fmt.Sprintf(" -> ERROR: %s", err)
			}
			log.Printf(logmsg)
		},
	}
	http.Handle("/", dav)

	if err := http.ListenAndServe(bindAddr, nil); err != nil {
		log.Fatalf("[SERVER] ERROR: %w", err)
	}

}
