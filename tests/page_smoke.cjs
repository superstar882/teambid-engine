// fake browser: any property/call returns another fake, so only real script errors (like using a value before it exists) surface
const fake = () => new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : (k in t ? t[k] : (t[k] = fake())),
  set: (t, k, v) => { t[k] = v; return true; }, apply: () => fake(), construct: () => fake() });
globalThis.document = fake(); globalThis.window = fake(); globalThis.location = { hash: "", reload() {} };
globalThis.localStorage = { getItem: () => "remembered-password", setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.fetch = () => Promise.reject(new Error("no network in test"));
const src = require("fs").readFileSync(process.argv[2], "utf8");
try { new Function(src)(); console.log("page script ran to the end with a remembered password: OK"); }
catch (e) { console.log("CRASH:", e.message); process.exit(1); }
