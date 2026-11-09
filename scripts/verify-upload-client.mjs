// Execute the actual TypeScript client against an isolated integration API.
import fs from "node:fs/promises";
import assert from "node:assert/strict";
import ts from "typescript";

const [base, knowledgeBaseId] = process.argv.slice(2);
assert(base && knowledgeBaseId, "Provide the isolated API URL and knowledge-base ID");
const source = await fs.readFile(new URL("../lib/api-client.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { backendApi } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const originalFetch = globalThis.fetch;
const batches = [];
globalThis.fetch = (path, options) => {
  batches.push(options.body.getAll("files").length);
  return originalFetch(new URL(path, base), options);
};
const files = [1, 2].map((number) => new File(
  [`# 客户端传输验收 ${number}\n员工年假申请说明 ${number}`], `client-${number}.md`,
));
const result = await backendApi.importDocuments("admin", knowledgeBaseId, files);
assert.deepEqual(batches, [1, 1]);
assert.equal(result.items.length, 2);
assert(result.items.every((item) => item.accepted && item.build_task_id));
console.log("TypeScript upload client: two real multipart requests, both persisted.");
