.PHONY: build
build:
	test ! -f go.mod && go mod init worblehat || true
	test ! -f go.sum && go mod tidy || true
	go fmt
	go build

.PHONY: run
run: build
	go run main.go

.PHONY: clean
clean:
	@rm -f go.mod go.sum worblehat
