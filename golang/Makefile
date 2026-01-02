build: main.go
	test ! -f go.mod && go mod init worblehat || true
	test ! -f go.sum && go mod tidy || true
	go fmt
	go build

.PHONY: update
update:
	@rm -f go.mod go.sum
	go mod init worblehat
	go mod tidy

.PHONY: run
run: build
	go run main.go

.PHONY: clean
clean:
	@rm -f worblehat
