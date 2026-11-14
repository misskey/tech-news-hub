const { apiBase } = require('../config');
function get(path, params = {}) {
  if (apiBase.includes('example.invalid')) return Promise.reject(new Error('请先配置服务地址'));
  return new Promise((resolve, reject) => {
    wx.request({ url: apiBase.replace(/\/$/, '') + '/api/v1' + path, data: params, timeout: 12000,
      success(res) {
        if (res.statusCode === 200 && res.data && typeof res.data === 'object') resolve(res.data);
        else reject(new Error(res.statusCode === 401 ? '本站为私有站点，暂不支持小程序访问' : res.statusCode === 404 ? '内容不存在或已下架' : '服务暂时不可用，请稍后重试'));
      }, fail() { reject(new Error('连接失败，请检查网络后重试')); }
    });
  });
}
module.exports = { get };
