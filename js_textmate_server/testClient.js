const path = require('path');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

// const PROTO_PATH = fs.readFileSync(path.resolve(__dirname, './../protos/text_mate.proto'), 'utf8')
const PROTO_PATH = path.resolve(__dirname, './../protos/text_mate.proto')
const packageDefinition = protoLoader.loadSync(
    PROTO_PATH,
    {
        keepCase: true,
        longs: String,
        enums: String,
        defaults: true,
        oneofs: true
    });

const ServerAddress = '0.0.0.0:50051'

const textMate_proto = grpc.loadPackageDefinition(packageDefinition).textMate;


function main() {

    var client = new textMate_proto.TextMateService(ServerAddress, grpc.credentials.createInsecure());
  
    client.GetTextMatePlain({text: "call you", scope:"source.c"}, function(err, response) {
      console.log('Greeting:', JSON.parse(response.text), err);
    });
  
  }
  
  main();