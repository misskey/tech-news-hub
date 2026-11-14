const api = require('../../utils/api');
Page({
  data: { items: [], sources: [{ id: '', label: '全部来源' }], sourceIndex: 0, windows: ['今天', '近3天', '近7天'], windowIndex: 0, query: '', loading: false, error: '', page: 0, hasMore: false, briefing: null },
  onLoad() { this.load(true); },
  onUnload() { this.version = (this.version || 0) + 1; },
  onPullDownRefresh() { this.load(true); },
  onReachBottom() { if (!this.data.loading && this.data.hasMore) this.load(false); },
  onSearchInput(e) { this.setData({ query: e.detail.value }); },
  search() { this.load(true); },
  changeWindow(e) { this.setData({ windowIndex: Number(e.detail.value), sourceIndex: 0 }); this.load(true); },
  changeSource(e) { this.setData({ sourceIndex: Number(e.detail.value) }); this.load(true); },
  open(e) { wx.navigateTo({ url: '/pages/detail/detail?id=' + e.currentTarget.dataset.id }); },
  async load(reset) {
    const version = this.version = (this.version || 0) + 1;
    const page = reset ? 1 : this.data.page + 1;
    const source = this.data.sources[this.data.sourceIndex].id;
    this.setData({ loading: true, error: '', ...(reset ? { items: [], briefing: null, hasMore: false } : {}) });
    try {
      const result = await api.get('/news', { page, q: this.data.query, source, window: ['today', '3d', '7d'][this.data.windowIndex] });
      if (version !== this.version) return;
      const sources = [{ id: '', label: '全部来源' }, ...result.sources];
      const items = reset ? result.items : [...this.data.items, ...result.items];
      this.setData({ items: items.filter((x,i,a) => a.findIndex(y => y.id === x.id) === i), page,
        sources, sourceIndex: Math.max(0, sources.findIndex(x => x.id === source)), hasMore: result.has_more,
        briefing: result.briefing, date: result.date, total: result.total, limited: result.candidate_limit_reached });
    } catch (err) { if (version === this.version) this.setData({ error: err.message }); }
    finally { if (version === this.version) { this.setData({ loading: false }); wx.stopPullDownRefresh(); } }
  },
  retry() { this.load(this.data.page === 0 || this.data.items.length === 0); }
});
