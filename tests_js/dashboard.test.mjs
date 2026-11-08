import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

test('a blocked chart CDN leaves summary and tables readable', async () => {
  const html = await readFile(new URL('../docs/index.html', import.meta.url), 'utf8');
  const data = JSON.parse(await readFile(new URL('../docs/data.json', import.meta.url), 'utf8'));
  const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent: '', innerHTML: '', insertAdjacentHTML(position, value) {this.innerHTML += value;}});
    return nodes.get(id);
  };
  const context = vm.createContext({
    fetch: async () => ({ok: true, json: async () => data}),
    document: {getElementById: node, querySelector: node},
    kpis: node('kpis'),
  });
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(node('kpis').innerHTML, /Gross item revenue/);
  assert.match(node('#t tbody').innerHTML, /<tr>/);
  assert.match(node('#t2 tbody').innerHTML, /<tr>/);
  assert.match(node('main').innerHTML, /Charts could not be loaded/);
  assert.doesNotMatch(node('main').innerHTML, /dashboard data did not load/);
});
