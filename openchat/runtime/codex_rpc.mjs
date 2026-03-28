import process from "node:process";

const [url, method] = process.argv.slice(2);

if (!url || !method) {
  console.error("usage: node codex_rpc.mjs <ws-url> <method>");
  process.exit(2);
}

const stdin = await new Promise((resolve, reject) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    data += chunk;
  });
  process.stdin.on("end", () => resolve(data.trim() || "{}"));
  process.stdin.on("error", reject);
});

const params = JSON.parse(stdin);
const ws = new WebSocket(url);
let initialized = false;
let requestSent = false;
let finished = false;

const fail = (message) => {
  if (finished) {
    return;
  }
  finished = true;
  console.error(message);
  try {
    ws.close();
  } catch {
    // Ignore close failures during teardown.
  }
  process.exit(1);
};

const succeed = (result) => {
  if (finished) {
    return;
  }
  finished = true;
  process.stdout.write(JSON.stringify(result));
  try {
    ws.close();
  } catch {
    // Ignore close failures during teardown.
  }
  process.exit(0);
};

const sendRequest = (id, requestMethod, requestParams) => {
  ws.send(JSON.stringify({ id, method: requestMethod, params: requestParams }));
};

ws.addEventListener("open", () => {
  sendRequest(1, "initialize", {
    clientInfo: {
      name: "openchat-runtime",
      title: "OpenChat Runtime",
      version: "0.1.0",
    },
    capabilities: {
      experimentalApi: true,
    },
  });
});

ws.addEventListener("message", (event) => {
  const payload = JSON.parse(event.data.toString());
  if (payload.id === 1 && payload.result && !initialized) {
    initialized = true;
    ws.send(JSON.stringify({ method: "initialized" }));
    sendRequest(2, method, params);
    requestSent = true;
    return;
  }
  if (payload.id === 2 && Object.prototype.hasOwnProperty.call(payload, "result")) {
    succeed(payload.result);
    return;
  }
  if (payload.id === 2 && payload.error) {
    fail(JSON.stringify(payload.error));
  }
});

ws.addEventListener("error", () => {
  if (!finished) {
    fail(`websocket error while calling ${method}`);
  }
});

ws.addEventListener("close", () => {
  if (!finished && requestSent) {
    fail(`connection closed before ${method} completed`);
  }
});

setTimeout(() => {
  fail(`timeout while calling ${method}`);
}, 15000);
