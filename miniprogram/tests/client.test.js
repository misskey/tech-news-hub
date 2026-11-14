const assert = require('node:assert/strict');
const test = require('node:test');
let storage = [];
global.wx = { getStorageSync: () => storage, setStorageSync: (_, rows) => { storage = rows; } };
const saved = require('../utils/saved');
test('favorites toggle and cap', () => {
 storage = null; assert.deepEqual(saved.list(), []);
 assert.equal(saved.toggle({ id: 1, title: 'Title' }), true);
 assert.equal(saved.toggle({ id: 1, title: 'Title' }), false);
 for (let i = 1; i <= 110; i++) saved.toggle({ id: i });
 assert.equal(saved.list().length, 100);
});
test('missing API config has actionable error', async () => {
 await assert.rejects(require('../utils/api').get('/news'), /配置服务地址/);
});
test('latest filter wins over slow response and pagination deduplicates', async () => {
 const api = require('../utils/api'); const pending = [];
 api.get = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
 let definition; global.Page = x => { definition = x; }; wx.stopPullDownRefresh = () => {};
 require('../pages/index/index');
 const page = { ...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values); } };
 const first = page.load(true); page.data.query = 'new'; const second = page.load(true);
 const payload = items => ({ items, sources: [], has_more: true, briefing: {}, total: 3 });
 pending[1].resolve(payload([{ id: 2 }])); await second;
 pending[0].resolve(payload([{ id: 1 }])); await first;
 assert.deepEqual(page.data.items, [{ id: 2 }]);
 const more = page.load(false); pending[2].resolve(payload([{id: 2}, {id: 3}])); await more;
 assert.deepEqual(page.data.items.map(x => x.id), [2,3]);
 const failed = page.load(false); pending[3].reject(new Error('offline')); await failed;
 assert.equal(page.data.page, 2); assert.equal(page.data.error, 'offline'); assert.equal(page.data.loading, false);
});
