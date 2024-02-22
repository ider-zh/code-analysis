test:
	poetry run python -m unittest discover tests -v

dev:
	poetry run python develop.py

main:
	poetry run python main.py linux-kernel-test-link

init_protos:
	poetry run python -m grpc_tools.protoc -I ./protos --python_out=./src/protos --pyi_out=./src/protos --grpc_python_out=./src/protos ./protos/text_mate.proto

js_server:
	cd js_textmate_server;pnpm run server

js_test:
	cd js_textmate_server;pnpm run test

js_test_tm:
	cd js_textmate_server;pnpm run test_tm


