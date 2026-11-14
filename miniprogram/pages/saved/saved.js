const saved = require('../../utils/saved');
Page({ data: { items: [] }, onShow() { this.setData({ items: saved.list() }); }, open(e) { wx.navigateTo({ url: '/pages/detail/detail?id=' + e.currentTarget.dataset.id }); } });
