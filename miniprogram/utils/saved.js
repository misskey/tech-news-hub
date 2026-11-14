const KEY = 'tnh_saved_v1';
function list() { try { const data = wx.getStorageSync(KEY); return Array.isArray(data) ? data.filter(x => x && Number.isInteger(x.id)) : []; } catch (_) { return []; } }
function toggle(item) {
  const rows = list(); const found = rows.some(x => x.id === item.id);
  const next = found ? rows.filter(x => x.id !== item.id) : [{ id: item.id, title: item.title, source_label: item.source_label }, ...rows].slice(0, 100);
  wx.setStorageSync(KEY, next); return !found;
}
module.exports = { list, toggle };
