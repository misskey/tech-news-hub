// Real HTTP transport check; not a substitute for the WeChat runtime.
const assert = require('node:assert/strict');
const base = process.env.SMOKE_API_BASE || 'http://127.0.0.1:8765';
require('../miniprogram/config').apiBase = base;
global.wx = {
  request(options) {
    const url = new URL(options.url);
    Object.entries(options.data).forEach(([k,v]) => url.searchParams.set(k,v));
    fetch(url, {signal: AbortSignal.timeout(options.timeout)})
      .then(async r => options.success({statusCode:r.status, data:await r.json()}))
      .catch(options.fail);
  }, stopPullDownRefresh() {}
};
let page;
global.Page = definition => { page = definition; page.data = structuredClone(definition.data); page.setData = data => Object.assign(page.data, data); };
require('../miniprogram/pages/index/index');
(async () => {
  page.data.windowIndex = 2;
  await page.load(true);
  assert.equal(page.data.error, '');
  assert.ok(page.data.items.length > 0, 'Fetch real data before running smoke test');
  const first = page.data.items[0];
  if (page.data.hasMore) { await page.load(false); assert.equal(page.data.page, 2); }
  assert.equal(new Set(page.data.items.map(x=>x.id)).size, page.data.items.length);
  const api = require('../miniprogram/utils/api');
  const detail = await api.get('/news/' + first.id);
  assert.equal(detail.id, first.id); assert.equal(detail.title, first.title);
  page.data.query = first.title; await page.load(true);
  assert.ok(page.data.items.some(x=>x.id===first.id));
  page.data.query = 'no-match-8c23decc'; await page.load(true);
  assert.equal(page.data.items.length, 0);
  await assert.rejects(api.get('/news/999999999'), /不存在/);
  console.log('PASS: live feed, pagination, unique IDs, detail, search, empty state, 404');
})().catch(e=>{console.error(e);process.exitCode=1;});
