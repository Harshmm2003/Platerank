// Writes a fingerprint of web/src into web/dist so `python check.py` can tell if the build is out of date.
// Line endings are normalised so Windows (CRLF) and Mac/Linux (LF) checkouts give the same fingerprint.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync, statSync } from "node:fs";
import { join } from "node:path";
const files = [];
const walk = (d) => readdirSync(d).sort().forEach((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : files.push(join(d, f))));
walk("src");
const h = createHash("sha256");
for (const f of files) h.update(f.replaceAll("\\", "/") + "\n" + readFileSync(f, "utf8").replaceAll("\r\n", "\n"));
writeFileSync("dist/src-fingerprint.txt", h.digest("hex"));
