const api = require('../../utils/api');
const saved = require('../../utils/saved');
Page({
 data: { item: null, error: '', loading: true, saved: false },
 onLoad(options) { this.id = Number(options.id); this.load(); },
 onUnload() { this.closed = true; },
 async load() {
  if (!Number.isInteger(this.id) || this.id < 1) { this.setData({ loading: false, error: '无效的资讯链接' }); return; }
  this.setData({ loading: true, error: '' });
  try { const item = await api.get('/news/' + this.id); if (!this.closed) this.setData({ item, saved: saved.list().some(x => x.id === this.id) }); }
  catch (err) { if (!this.closed) this.setData({ error: err.message }); }
  finally { if (!this.closed) this.setData({ loading: false }); }
 },
 toggleSave() { try { this.setData({ saved: saved.toggle(this.data.item) }); } catch (_) { wx.showToast({ title: '保存失败，请重试', icon: 'none' }); } },
 copyLink() { const url = this.data.item.url; if (!/^https?:\/\//i.test(url)) { wx.showToast({ title: '原文地址不可用', icon: 'none' }); return; } wx.setClipboardData({ data: url }); },
 onShareAppMessage() { return { title: this.data.item ? this.data.item.title : '科技早报', path: '/pages/detail/detail?id=' + this.id }; }
});
