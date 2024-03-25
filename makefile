test:
	poetry run python -m unittest discover tests -v

dev:
	poetry run python develop.py

main:
	poetry run python main.py linux-kernel-history-links

main-cache:
	poetry run python main.py linux-kernel-history-links --usecache true

handle-confuse:
	poetry run python main.py handle-confuse

main-year:
	poetry run python main.py linux-kernel-links-years $(EXTRA_ARGS)

kernel-extract:
	poetry run python main.py linux-kernel-history-extract-cache

dev_test:
	poetry run python main.py linux-kernel-test-link

init_protos:
	poetry run python -m grpc_tools.protoc -I ./protos --python_out=./src/protos --pyi_out=./src/protos --grpc_python_out=./src/protos ./protos/text_mate.proto

js_server:
	cd js_textmate_server;pnpm run server

js_test:
	cd js_textmate_server;pnpm run test

js_test_tm:
	cd js_textmate_server;pnpm run test_tm

dev_c_42:
	poetry remove c_formatter_42;poetry add ./submodule/c_formatter_42