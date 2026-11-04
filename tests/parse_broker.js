// Runs the page's own broker-CSV reader (parseBroker in app/index.html) on files, printing JSON. Used by test_import.py.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const code = src.match(/function csvTable[\s\S]*?\nfunction pickBrokerFile/)[0].replace(/\nfunction pickBrokerFile$/, "");
eval(code.replace(/^const /gm, "var ") + ";globalThis.parseBroker=parseBroker;");
console.log(JSON.stringify(process.argv.slice(3).map(f => parseBroker(fs.readFileSync(f, "utf8")))));
