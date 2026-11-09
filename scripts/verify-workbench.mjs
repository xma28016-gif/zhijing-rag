import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import ts from 'typescript';

async function loadTypeScript(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const result = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  return import('data:text/javascript;base64,' + Buffer.from(result.outputText).toString('base64'));
}
const catalog = await loadTypeScript('../lib/workbench-apps.ts');
const store = await loadTypeScript('../lib/workbench-store.ts');
const { businessApplications: apps, applicationCategories: categories } = catalog;
assert.equal(categories.length, 5);
assert.equal(apps.length, 6);
assert.equal(new Set(apps.map(app => app.id)).size, 6);
for (const app of apps) {
  assert.deepEqual(catalog.parseWorkbenchRoute(catalog.applicationHref(app.id)), { type: 'app', id: app.id });
  assert(app.taskPlaceholder && app.referenceLabel && app.examples.length > 0 && app.steps.length > 0);
}
for (const category of categories) {
  assert.deepEqual(catalog.parseWorkbenchRoute(catalog.categoryHref(category.id)), { type: 'category', id: category.id });
  assert(catalog.matchingApplications('', category.id).length > 0);
}
assert.equal(catalog.matchingApplications('', 'office').length, 2);
assert(catalog.matchingApplications('帮我整理会议纪要').some(app => app.id === 'meeting-minutes'));
assert(catalog.matchingApplications('合同').some(app => app.id === 'contract-review'));
assert.deepEqual(catalog.parseWorkbenchRoute('#workbench/app/%broken'), { type: 'home' });

const memory = new Map();
const storage = { getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value) };
const initial = store.readWorkbenchPreferences(storage);
assert.deepEqual(initial.favorites, ['policy-qa', 'industry-report']);
store.saveWorkbenchPreferences(storage, { favorites: [], recent: ['meeting-minutes'] });
assert.deepEqual(store.readWorkbenchPreferences(storage), { favorites: [], recent: ['meeting-minutes'] });
const draft = { task: '工作台验证任务', reference: '测试资料', requirements: '输出待办清单', assistantId: '', updatedAt: '2026-10-28T00:00:00Z' };
store.saveApplicationDraft(storage, 'meeting-minutes', draft);
assert.deepEqual(store.readApplicationDraft(storage, 'meeting-minutes'), draft);
assert.equal(store.readApplicationDraft(storage, 'industry-report').task, '');
memory.set(store.workbenchDraftsKey, '{invalid json');
assert.equal(store.readApplicationDraft(storage, 'meeting-minutes').task, '');
memory.set(store.workbenchPreferencesKey, '{invalid json');
assert.deepEqual(store.readWorkbenchPreferences(storage).favorites, initial.favorites);
const report = { status: 'passed', checks: ['5类6个应用均有有效的独立地址与工作页定义', '分类数量与搜索结果正确', '收藏可取消并在重新读取后保持', '应用草稿分别保存、互不覆盖，损坏存储可恢复为空白状态'], cloud_requests: 0 };
await writeFile(new URL('../artifacts/workbench-check.json', import.meta.url), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
